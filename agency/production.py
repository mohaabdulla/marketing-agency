"""Rules and deterministic calculations for production records.

Nothing here calls a model. Estimates are labelled as estimates; statistics are only reported
when their assumptions hold; pricing uses the operator's own inputs.
"""
import json
import math
import re
from datetime import date
from pathlib import Path
from .database import NotFound, Conflict, packed, timestamp
from .production_schemas import CAMPAIGN_SCOPED, APPROVABLE

CHANNEL_SPECS_PATH = Path(__file__).with_name('channel_specs.json')
ASSET_IMMUTABLE = ('sha256', 'size', 'mime', 'stored_name', 'original_url', 'width', 'height', 'duration_seconds', 'asset_type', 'parent_asset_version')
OPEN_APPROVAL_STATES = {'review-requested', 'changes-requested', 'approved'}


def channel_specs():
    """Editable configuration (agency/channel_specs.json); read on each call so edits apply."""
    return json.loads(CHANNEL_SPECS_PATH.read_text(encoding='utf-8'))


# ---------------------------------------------------------------- save-time rules
def prepare(db, repo, client_id, kind, data, body):
    """Called inside the record-save transaction, before scope and reference resolution."""
    if kind == 'shots':
        # A shot always lives in its storyboard's project and campaign.
        board = repo.record(db, client_id, data['storyboard_id'], 'storyboards')
        body.campaign_id, body.project_id = board['campaign_id'], board['project_id']
    if kind in CAMPAIGN_SCOPED and not body.campaign_id:
        raise ValueError('Choose a campaign for this record')


def rules(db, repo, client_id, kind, data, body, old, resolved, references, file_change=False):
    """Called inside the record-save transaction, after generic reference resolution."""
    if kind == 'landing-pages' and data['brand_id']:
        # Copy the selected brand token into this page revision; later brand edits do not silently change an export.
        data['primary_color'] = resolved[data['brand_id']]['data']['primary_color']
    if kind == 'audio-projects' and resolved[data['asset_id']]['data']['asset_type'] not in {'audio', 'video'}:
        raise ValueError('Audio projects require a registered audio or video asset')
    if kind == 'subtitles':
        if not old and data['timing_origin'] != 'operator' and not file_change:
            raise ValueError('Local ASR provenance is recorded only by the transcription job')
        if old and data['timing_origin'] != old['data']['timing_origin']:
            raise ValueError('Subtitle timing provenance cannot be rewritten')
    if kind == 'copy':
        if data['format'] not in channel_specs()['formats']:
            raise ValueError('Unknown copy format; choose one from the channel specification registry')
        from .services import effective_claim
        for claim_id in data['claim_ids']:
            if effective_claim(resolved[claim_id]['data']) not in {'verified', 'client-approved'}:
                raise ValueError('Only current verified or client-approved claims may be selected')
    if kind == 'shots':
        for field, allowed in (('image_asset_id', {'image', 'logo', 'product-reference'}), ('video_asset_id', {'video', 'gif'})):
            if data[field] and resolved[data[field]]['data']['asset_type'] not in allowed:
                raise ValueError('The selected asset type does not fit this shot field')
    if kind == 'assets':
        if old and old['data'].get('parent_asset_version') is not None and data['parent_asset_id'] != old['data']['parent_asset_id']:
            raise Conflict('A processed asset retains its original source; create a separate derivative')
        if data['parent_asset_version'] is not None and not old:
            if not data['parent_asset_id'] or resolved[data['parent_asset_id']]['version'] != data['parent_asset_version']:
                raise Conflict('Source asset changed during processing; rerun against its current version')
        if old and not file_change and any(old['data'].get(f) != data.get(f) for f in ASSET_IMMUTABLE):
            raise Conflict('File details are set when a file is registered; add a new file version instead')
        if data['parent_asset_id'] and old and data['parent_asset_id'] == old['id']:
            raise ValueError('An asset cannot be derived from itself')
    if kind == 'approvals':
        if data['target_kind'] not in APPROVABLE:
            raise ValueError('This record type cannot be sent for approval')
        target = repo.record(db, client_id, data['target_id'], data['target_kind'], include_archived=True)
        if not db.execute('SELECT 1 FROM revisions WHERE resource_id=? AND client_id=? AND version=?',
                          (target['id'], client_id, data['target_version'])).fetchone():
            raise NotFound('Approval target revision not found in this client')
        # The link freezes the reviewed version, not whatever is current later.
        references.append((data['target_id'], 'target_id', data['target_version']))
    if kind == 'calendar' and data['copy_id'] and resolved[data['copy_id']]['campaign_id'] != body.campaign_id:
        raise ValueError('The selected copy belongs to another campaign')
    if kind == 'paid-plans' and data['copy_id'] and resolved[data['copy_id']]['campaign_id'] != body.campaign_id:
        raise ValueError('The selected copy belongs to another campaign')
    if kind == 'snapshots' and data['variant'] and len(data['variant']) > 80:
        raise ValueError('Variant labels are limited to 80 characters')
    if kind == 'tasks' and old and old['id'] in data['depends_on_ids']:
        raise ValueError('A task cannot depend on itself')
    if kind == 'tasks' and old:
        for dependency in data['depends_on_ids']:
            cycle = db.execute("WITH RECURSIVE deps(id) AS (SELECT target_id FROM links WHERE source_id=? AND client_id=? "
                               "AND relation='depends_on_ids' UNION SELECT l.target_id FROM links l JOIN deps d ON l.source_id=d.id "
                               "WHERE l.client_id=? AND l.relation='depends_on_ids') SELECT 1 FROM deps WHERE id=? LIMIT 1",
                               (dependency, client_id, client_id, old['id'])).fetchone()
            if cycle:
                raise ValueError('Task dependencies cannot form a cycle')


def after_save(db, repo, client_id, item):
    """A changed record is a new version: open approvals of older versions are superseded."""
    if item['kind'] == 'approvals':
        return
    rows = db.execute("SELECT r.* FROM records r JOIN links l ON l.source_id=r.id AND l.client_id=r.client_id "
                      "WHERE l.target_id=? AND l.relation='target_id' AND r.client_id=? AND r.kind='approvals'",
                      (item['id'], client_id)).fetchall()
    for row in rows:
        approval = repo.unpack_record(row)
        data = approval['data']
        if data['state'] in OPEN_APPROVAL_STATES and data['target_version'] < item['version']:
            data = dict(data, state='superseded')
            db.execute('UPDATE records SET payload=?,version=version+1,updated_at=? WHERE id=? AND client_id=?',
                       (packed(data), timestamp(), approval['id'], client_id))
            saved = repo.record(db, client_id, approval['id'], 'approvals', include_archived=True)
            repo.revision(db, saved, 'approvals')
            repo.audit(db, client_id, approval['id'], 'approval.superseded', saved['version'],
                       dict(target_id=item['id'], new_target_version=item['version']))


# ---------------------------------------------------------------- read-time computed values
def decorate(item):
    kind, data = item['kind'], item['data']
    if kind == 'scripts':
        return dict(item, computed=script_estimate(data))
    if kind == 'experiments':
        return dict(item, computed=experiment_statistics(data['variants']))
    if kind == 'pricing':
        return dict(item, computed=pricing_summary(data))
    if kind == 'licenses':
        expired = bool(data.get('expires')) and data['expires'] < date.today().isoformat()
        return dict(item, effective_status='expired' if expired else 'current')
    return item


WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)


def script_estimate(data):
    """Spoken-length estimate from word counts at the configured speaking rate for the language."""
    rates = channel_specs()['speech_words_per_minute']
    rate = rates.get(data['language'], rates.get(data['language'].split('-')[0], rates['en']))
    scenes, total_words, total_seconds = [], 0, 0.0
    hook_words = len(WORD.findall(data['hooks'][0])) if data['hooks'] else 0
    for index, scene in enumerate(data['scenes'], 1):
        words = len(WORD.findall(scene['narration'] + ' ' + scene['dialogue'])) + (hook_words if index == 1 else 0)
        spoken = words * 60 / rate
        seconds = max(spoken, scene['duration_seconds'] or 0)
        scenes.append(dict(scene=index, words=words, spoken_seconds=round(spoken, 1), planned_seconds=round(seconds, 1)))
        total_words += words
        total_seconds += seconds
    target = data['target_duration_seconds']
    return dict(method=f'Estimate: {rate} spoken words per minute for {data["language"]} (agency/channel_specs.json); '
                       'a scene lasts the longer of its speech and its entered duration. Verify against a read-through.',
                words=total_words, estimated_seconds=round(total_seconds, 1), target_seconds=target,
                over_target_seconds=round(max(0.0, total_seconds - target), 1), scenes=scenes)


def _normal_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def experiment_statistics(variants):
    """Two-proportion z-test of each treatment against the control, only where it is valid."""
    method = 'Two-sided two-proportion z-test against the control (pooled standard error); 95% interval for the difference (unpooled).'
    control = next((v for v in variants if v['is_control']), None)
    treatments = [v for v in variants if not v['is_control']]
    if not control or not treatments:
        return dict(computed=False, reason='Add one control and at least one treatment variant.', method=method)

    def counted(v):
        return v['sample_size'] is not None and v['conversions'] is not None and v['sample_size'] > 0

    if not counted(control):
        return dict(computed=False, reason='Record the control sample size and conversions.', method=method)
    alpha = 0.05 / len(treatments)      # Bonferroni when several treatments share one control
    n1, x1 = control['sample_size'], control['conversions']
    p1 = x1 / n1
    results = []
    for v in treatments:
        if not counted(v):
            results.append(dict(label=v['label'], computed=False, reason='Sample size and conversions are missing.'))
            continue
        n2, x2 = v['sample_size'], v['conversions']
        p2 = x2 / n2
        row = dict(label=v['label'], sample_size=n2, conversions=x2, rate=p2, control_rate=p1,
                   absolute_difference=p2 - p1, relative_lift=(p2 - p1) / p1 if p1 else None)
        # Normal approximation: at least 10 conversions and 10 non-conversions in each group.
        if min(x1, n1 - x1, x2, n2 - x2) < 10:
            results.append(dict(row, computed=False, significant=None,
                                reason='Too few conversions or non-conversions (under 10 in a group) for this test; collect more data.'))
            continue
        pooled = (x1 + x2) / (n1 + n2)
        se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
        z = (p2 - p1) / se
        p_value = 2 * (1 - _normal_cdf(abs(z)))
        half = 1.959963984540054 * math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
        results.append(dict(row, computed=True, z=z, p_value=p_value, alpha=alpha, significant=p_value < alpha,
                            difference_ci95=[p2 - p1 - half, p2 - p1 + half]))
    return dict(computed=any(r.get('computed') for r in results), method=method, alpha_per_comparison=alpha,
                control=dict(label=control['label'], sample_size=n1, conversions=x1, rate=p1), comparisons=results,
                caveat='Assumes independent users, a fixed sample decided in advance and one primary metric. '
                       'It says nothing about causes outside the test.')


def pricing_summary(d):
    """Fee, cost and margin arithmetic for one scenario. Media spend is the client's money, not revenue."""
    components = dict(
        hourly=d['billable_rate'] * d['expected_hours'],
        fixed=d['fixed_fee'],
        retainer=d['monthly_retainer'] * d['retainer_months'],
        packages=d['package_price'] * d['package_quantity'],
        media_management=d['media_spend'] * d['media_fee_percent'] / 100,
        performance=d['performance_fee'],
    )
    gross_fees = sum(components.values())
    discount = gross_fees * d['discount_percent'] / 100
    markup = d['pass_through_costs'] * d['pass_through_markup_percent'] / 100
    revenue = gross_fees - discount + markup
    labor = d['internal_hourly_cost'] * d['expected_hours']
    cost = labor + d['other_internal_costs']
    margin = revenue - cost
    target = d['target_margin_percent'] / 100
    return dict(currency=d['currency'], fee_components={k: round(v, 3) for k, v in components.items()},
                gross_fees=round(gross_fees, 3), discount=round(discount, 3), pass_through_markup=round(markup, 3),
                agency_revenue=round(revenue, 3), internal_labor_cost=round(labor, 3), internal_cost=round(cost, 3),
                gross_margin=round(margin, 3), gross_margin_percent=round(100 * margin / revenue, 2) if revenue else None,
                revenue_needed_for_target_margin=round(cost / (1 - target), 3) if target else None,
                meets_target=(margin / revenue >= target) if revenue and target else None,
                client_invoice_total=round(revenue + d['pass_through_costs'], 3),
                external_spend_not_revenue=round(d['media_spend'], 3),
                note='Arithmetic on the entered values only. Media spend and pass-through costs are external money, not agency income.')
