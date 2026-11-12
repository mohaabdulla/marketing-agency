"""Stored metrics, CSV import, summaries and data-grounded reports.

Every number in a summary or report is computed from saved snapshots. Narrative fields are the
author's own words and are rendered in separate, labelled sections; they cannot alter a figure."""
import csv
import html
import io
import json
import zipfile
from collections import defaultdict
from datetime import date as Date
from .database import repository, uid, timestamp, packed, NotFound
from .production_schemas import Snapshot
from .production import experiment_statistics
from .services import service

MAX_CSV = 2 * 1024 ** 2
MAX_ROWS = 2000
ATTRIBUTION_NOTE = ('Figures are the values recorded per metric, date and channel. They are not de-duplicated across '
                    'platforms and no cross-platform attribution is inferred.')


def import_csv(client_id, upload, campaign_id=None, repo=repository):
    """Columns: date, metric, value and optionally channel, variant. All rows are saved, or none."""
    raw = upload.file.read(MAX_CSV + 1)
    if len(raw) > MAX_CSV:
        raise ValueError('CSV exceeds the 2 MB import limit')
    if not (upload.filename or '').lower().endswith('.csv'):
        raise ValueError('Import a .csv file')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('CSV must be UTF-8 encoded')
    reader = csv.DictReader(io.StringIO(text))
    fields = [f.strip().lower() for f in (reader.fieldnames or [])]
    if not {'date', 'metric', 'value'} <= set(fields):
        raise ValueError('CSV needs the columns: date, metric, value (optional: channel, variant)')
    rows = []
    for number, row in enumerate(reader, 2):
        if number - 1 > MAX_ROWS:
            raise ValueError(f'CSV exceeds the {MAX_ROWS} row import limit')
        rows.append((number, {k.strip().lower(): (v or '').strip() for k, v in row.items() if k}))
    if not rows:
        raise ValueError('CSV contains no data rows')
    with repo.connection(write=True) as db:
        repo.client(db, client_id, active=True)
        project_id = None
        if campaign_id:
            project_id = repo.record(db, client_id, campaign_id, 'campaigns')['project_id']
        metrics = {r['name'].casefold(): (r['id'], r['version']) for r in db.execute(
            "SELECT id,name,version FROM records WHERE client_id=? AND kind='metrics' AND archived=0", (client_id,))}
        unknown = sorted({row['metric'] for _, row in rows if row['metric'].casefold() not in metrics})
        if unknown:
            raise ValueError('Create these metric definitions first (names must match): ' + ', '.join(unknown[:10]))
        now, created = timestamp(), 0
        for number, row in rows:
            metric_id, metric_version = metrics[row['metric'].casefold()]
            try:
                data = Snapshot(metric_id=metric_id, date=row['date'], value=float(row['value'].replace(',', '')),
                                channel=row.get('channel', ''), variant=row.get('variant', ''), source='csv-import').model_dump(mode='json')
            except Exception:
                raise ValueError(f'Row {number}: use an ISO date (YYYY-MM-DD), a number, and short channel/variant labels')
            key = uid()
            name = f'{row["metric"]} · {data["date"]}' + (f' · {data["channel"]}' if data['channel'] else '')
            db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (key, client_id, 'snapshots', name[:160], project_id, campaign_id, packed(data), 1, 0, now, now))
            db.execute('INSERT INTO links VALUES (?,?,?,?,?)', (key, metric_id, client_id, 'metric_id', metric_version))
            item = repo.record(db, client_id, key, 'snapshots')
            item['reference_versions'] = [dict(id=metric_id, relation='metric_id', version=metric_version)]
            repo.revision(db, item, 'snapshots')
            created += 1
        repo.audit(db, client_id, campaign_id or client_id, 'analytics.csv-imported', 1, dict(rows=created, file=(upload.filename or '')[:120]))
    return dict(imported=created, metrics=sorted({row['metric'] for _, row in rows}), campaign_id=campaign_id)


def _aggregate(values, how):
    if not values:
        return None
    return sum(values) if how == 'sum' else sum(values) / len(values) if how == 'mean' else values[-1]


def summary(client_id, campaign_id=None, metric_ids=None, start=None, end=None, repo=repository):
    """Per metric: dated series, first/last period values, change, and totals by channel and variant."""
    with repo.connection() as db:
        repo.client(db, client_id)
        if campaign_id:
            repo.record(db, client_id, campaign_id, 'campaigns')
        metrics = [repo.unpack_record(r) for r in db.execute(
            "SELECT * FROM records WHERE client_id=? AND kind='metrics' AND archived=0 ORDER BY name", (client_id,))]
        if metric_ids:
            metrics = [m for m in metrics if m['id'] in set(metric_ids)]
        where, params = "client_id=? AND kind='snapshots' AND archived=0", [client_id]
        if campaign_id:
            where += ' AND campaign_id=?'
            params.append(campaign_id)
        snapshots = [json.loads(r['payload']) for r in db.execute('SELECT payload FROM records WHERE ' + where, params)]
    output = []
    for metric in metrics:
        how = metric['data']['aggregation']
        rows = sorted((s for s in snapshots if s['metric_id'] == metric['id']
                       and (not start or s['date'] >= start) and (not end or s['date'] <= end)), key=lambda s: s['date'])
        by_date, by_channel, by_variant = defaultdict(list), defaultdict(list), defaultdict(list)
        for s in rows:
            by_date[s['date']].append(s['value'])
            by_channel[s['channel'] or '(none)'].append(s['value'])
            if s['variant']:
                by_variant[s['variant']].append(s['value'])
        series = [dict(date=d, value=_aggregate(v, how)) for d, v in sorted(by_date.items())]
        first, last = (series[0], series[-1]) if series else (None, None)
        change = last['value'] - first['value'] if len(series) > 1 else None
        output.append(dict(
            metric_id=metric['id'], name=metric['name'], unit=metric['data']['unit'], direction=metric['data']['direction'],
            aggregation=how, source=metric['data']['source'], observations=len(rows), series=series,
            first=first, last=last, change=change,
            change_percent=(100 * change / first['value']) if change is not None and first['value'] else None,
            overall=_aggregate([s['value'] for s in rows], how),
            by_channel={k: _aggregate(v, how) for k, v in sorted(by_channel.items())},
            by_variant={k: _aggregate(v, how) for k, v in sorted(by_variant.items())}))
    return dict(metrics=output, campaign_id=campaign_id, period=dict(start=start, end=end), attribution=ATTRIBUTION_NOTE)


def _number(value):
    if value is None:
        return 'n/a'
    return f'{value:,.0f}' if abs(value) >= 100 and float(value).is_integer() else f'{value:,.2f}'.rstrip('0').rstrip('.')


def _chart(series, width=560, height=120):
    """Inline SVG line of the stored series; no chart is drawn without at least two points."""
    if len(series) < 2:
        return '<p class="muted">Not enough dated values for a trend line.</p>'
    values = [p['value'] for p in series]
    low, high = min(values), max(values)
    span = (high - low) or 1
    points = ' '.join(f'{12 + i * (width - 24) / (len(values) - 1):.1f},{height - 14 - (v - low) * (height - 28) / span:.1f}'
                      for i, v in enumerate(values))
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Trend from {series[0]["date"]} to {series[-1]["date"]}">'
            f'<polyline fill="none" stroke="#0f766e" stroke-width="2" points="{points}"/>'
            f'<text x="12" y="{height - 2}" font-size="10">{series[0]["date"]}</text>'
            f'<text x="{width - 12}" y="{height - 2}" font-size="10" text-anchor="end">{series[-1]["date"]}</text></svg>')


def fact_lines(metric):
    """Sentences generated only from stored values."""
    name, unit = metric['name'], (' ' + metric['unit']) if metric['unit'] else ''
    if not metric['observations']:
        return [f'{name}: no values were recorded in this period.']
    lines = []
    if metric['change'] is not None:
        direction = 'increased' if metric['change'] > 0 else 'decreased' if metric['change'] < 0 else 'did not change'
        percent = f' ({metric["change_percent"]:+.1f}%)' if metric['change_percent'] is not None else ''
        lines.append(f'{name} {direction} from {_number(metric["first"]["value"])}{unit} on {metric["first"]["date"]} '
                     f'to {_number(metric["last"]["value"])}{unit} on {metric["last"]["date"]}{percent}.')
    else:
        lines.append(f'{name}: {_number(metric["last"]["value"])}{unit} on {metric["last"]["date"]} (one dated value; no trend).')
    label = {'sum': 'Total', 'mean': 'Average', 'last': 'Latest'}[metric['aggregation']]
    lines.append(f'{label} for the period: {_number(metric["overall"])}{unit} from {metric["observations"]} recorded values.')
    return lines


def render_report(client_id, report_id, agency=service, repo=repository):
    """ZIP of report.html, data.csv and report.json built from the saved report and stored metrics."""
    report = agency.get(client_id, report_id, 'reports')
    d = report['data']
    data = summary(client_id, report['campaign_id'], d['metric_ids'] or None, d['period_start'], d['period_end'], repo)
    experiments = [agency.get(client_id, key, 'experiments') for key in d['experiment_ids']]
    with repo.connection() as db:
        client = repo.client(db, client_id)
    esc = html.escape
    sections = []
    for metric in data['metrics']:
        channels = ''.join(f'<tr><td>{esc(k)}</td><td>{_number(v)}</td></tr>' for k, v in metric['by_channel'].items())
        sections.append(f'<section><h3>{esc(metric["name"])}</h3>' + ''.join(f'<p>{esc(line)}</p>' for line in fact_lines(metric))
                        + _chart(metric['series'])
                        + (f'<table><tr><th>Channel</th><th>{esc(metric["aggregation"])}</th></tr>{channels}</table>' if channels else '')
                        + f'<p class="muted">Source: {esc(metric["source"])} · aggregation: {esc(metric["aggregation"])}</p></section>')
    tests = []
    for experiment in experiments:
        stats = experiment['computed']
        rows = ''
        for row in stats.get('comparisons', []):
            if row.get('computed'):
                verdict = ('statistically significant' if row['significant'] else 'not statistically significant') + f' at α={row["alpha"]:.4g}'
                detail = (f'{row["rate"]:.2%} vs control {row["control_rate"]:.2%}; difference {row["absolute_difference"]:+.2%} '
                          f'(95% CI {row["difference_ci95"][0]:+.2%} to {row["difference_ci95"][1]:+.2%}); p={row["p_value"]:.4f}; {verdict}')
            else:
                detail = 'Not computed: ' + row.get('reason', '')
            rows += f'<tr><td>{esc(row["label"])}</td><td>{esc(detail)}</td></tr>'
        tests.append(f'<section><h3>{esc(experiment["name"])}</h3><p><b>Hypothesis:</b> {esc(experiment["data"]["hypothesis"])}</p>'
                     + (f'<table><tr><th>Variant</th><th>Computed result</th></tr>{rows}</table><p class="muted">{esc(stats["method"])} {esc(stats.get("caveat", ""))}</p>'
                        if rows else f'<p class="muted">{esc(stats.get("reason", "No computed result."))}</p>')
                     + (f'<p><b>Author\'s conclusion:</b> {esc(experiment["data"]["conclusion"])}</p>' if experiment['data']['conclusion'] else '') + '</section>')

    def listing(items):
        return '<ul>' + ''.join(f'<li>{esc(x)}</li>' for x in items) + '</ul>' if items else '<p class="muted">None recorded.</p>'

    def prose(text):
        return ''.join(f'<p>{esc(p)}</p>' for p in text.split('\n') if p.strip()) or '<p class="muted">None recorded.</p>'

    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(report["name"])}</title><style>body{{font:15px/1.55 system-ui,sans-serif;max-width:860px;margin:32px auto;padding:0 18px;color:#17212f}}'
            'h1{font-size:26px;margin-bottom:4px}h2{margin-top:34px;border-bottom:2px solid #d6dee8;padding-bottom:6px;font-size:19px}h3{font-size:16px;margin:18px 0 6px}'
            'table{border-collapse:collapse;margin:10px 0}td,th{border:1px solid #cdd6e1;padding:5px 10px;text-align:left;font-size:13px}'
            '.muted{color:#5b6b7f;font-size:12.5px}.tag{display:inline-block;font-size:11px;letter-spacing:.08em;padding:2px 8px;border-radius:99px;background:#e6f4f1;color:#0f5f58;margin-left:8px;vertical-align:middle}'
            '.tag.o{background:#fdf1dd;color:#8a5a00}svg{width:100%;max-width:560px;height:auto;background:#f6f9fc;border-radius:6px}@media print{body{margin:0}}</style>'
            f'<h1>{esc(report["name"])}</h1><p class="muted">{esc(client["name"])} · {d["period_start"]} to {d["period_end"]} · report v{report["version"]} · generated {timestamp()[:16].replace("T", " ")} UTC</p>'
            f'<h2>Executive summary <span class="tag o">AUTHOR\'S WORDS</span></h2>{prose(d["executive_summary"])}'
            f'<h2>KPI performance <span class="tag">FACT · FROM STORED DATA</span></h2>{"".join(sections) or "<p class=muted>No metrics selected or recorded.</p>"}'
            f'<h2>Experiment results <span class="tag">FACT · COMPUTED</span></h2>{"".join(tests) or "<p class=muted>No experiments attached.</p>"}'
            f'<h2>Interpretation <span class="tag o">AUTHOR\'S INTERPRETATION</span></h2>{prose(d["interpretation"])}'
            f'<h2>Recommendations <span class="tag o">RECOMMENDATION</span></h2>{listing(d["recommendations"])}'
            f'<h2>Next actions</h2>{listing(d["next_actions"])}'
            f'<h2>Data sources and limits</h2><p class="muted">{esc(ATTRIBUTION_NOTE)} Values come from manual entry and CSV imports saved in the local agency database; '
            'sections marked FACT are generated from those values and cannot be edited in the report.</p></html>')
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['metric', 'unit', 'date', 'value', 'aggregation'])
    for metric in data['metrics']:
        for point in metric['series']:
            name = metric['name']
            writer.writerow([("'" + name) if name.lstrip().startswith(('=', '+', '-', '@')) else name, metric['unit'], point['date'], point['value'], metric['aggregation']])
    path = repo.home / 'exports' / (uid() + '.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr('report.html', page)
        bundle.writestr('data.csv', '﻿' + stream.getvalue())
        bundle.writestr('report.json', json.dumps(dict(report=report, metrics=data, experiments=experiments), ensure_ascii=False, indent=2, default=str))
    with repo.connection(write=True) as db:
        repo.audit(db, client_id, report_id, 'report.rendered', report['version'], dict(metrics=len(data['metrics']), experiments=len(experiments)))
    return path


def overview(client_id, repo=repository, agency=service):
    """Dashboard counts that exist in the database: nothing estimated."""
    with repo.connection() as db:
        repo.client(db, client_id)
        def count(sql, *params):
            return db.execute(sql, (client_id, *params)).fetchone()[0]
        today = Date.today().isoformat()
        return dict(
            awaiting_approval=count("SELECT count(*) FROM records WHERE client_id=? AND kind='approvals' AND archived=0 AND json_extract(payload,'$.state')='review-requested'"),
            changes_requested=count("SELECT count(*) FROM records WHERE client_id=? AND kind='approvals' AND archived=0 AND json_extract(payload,'$.state')='changes-requested'"),
            upcoming_content=count("SELECT count(*) FROM records WHERE client_id=? AND kind='calendar' AND archived=0 AND json_extract(payload,'$.scheduled_date')>=? AND json_extract(payload,'$.publish_status') IN ('planned','package-exported')", today),
            open_tasks=count("SELECT count(*) FROM records WHERE client_id=? AND kind='tasks' AND archived=0 AND json_extract(payload,'$.status') IN ('todo','in-progress','blocked')"),
            overdue_tasks=count("SELECT count(*) FROM records WHERE client_id=? AND kind='tasks' AND archived=0 AND json_extract(payload,'$.status') IN ('todo','in-progress','blocked') AND json_extract(payload,'$.due_date')<?", today),
            running_experiments=count("SELECT count(*) FROM records WHERE client_id=? AND kind='experiments' AND archived=0 AND json_extract(payload,'$.status')='running'"),
            failed_jobs=count("SELECT count(*) FROM jobs WHERE client_id=? AND state='failed'"),
            registered_assets=count("SELECT count(*) FROM records WHERE client_id=? AND kind='assets' AND archived=0"),
            assets_without_rights=count("SELECT count(*) FROM records WHERE client_id=? AND kind='assets' AND archived=0 AND json_extract(payload,'$.license_id') IS NULL"))
