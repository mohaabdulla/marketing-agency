"""Scenario arithmetic and draft planning exports; never authorizes external spend."""
import csv
import io
import json
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .acquisition import bundle


def paid_scenario(data):
    spend = data['daily_budget'] * data['days']
    clicks = spend / data['assumed_cpc'] if data['assumed_cpc'] else None
    conversions = clicks * data['assumed_conversion_percent'] / 100 if clicks is not None and data['assumed_conversion_percent'] is not None else None
    url = ''
    if data['destination_url']:
        parsed = urlsplit(data['destination_url'])
        parameters = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith('utm_')]
        parameters += [('utm_' + key, data['utm_' + key]) for key in ('source', 'medium', 'campaign', 'content') if data['utm_' + key]]
        url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(parameters), parsed.fragment))
    return dict(planned_external_ad_spend=round(spend, 3), currency=data['currency'], scenario_clicks=clicks,
                scenario_conversions=conversions, tracked_url=url,
                notice='AD SPEND IS EXTERNAL. Planning only: no advertising account is connected and no budget is authorized. '
                       'Clicks/conversions are arithmetic from your assumptions, not measured performance or a forecast.')


def planning_bundle(item):
    data = item['data']
    result = paid_scenario(data) if item['kind'] == 'paid-plans' else {}
    text = io.StringIO(newline='')
    writer = csv.writer(text)
    writer.writerow(['field', 'value'])
    for key, value in {**data, **result}.items():
        value = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value) if value is not None else ''
        if value.startswith(('=', '+', '-', '@', '\t', '\r')):
            value = "'" + value
        writer.writerow([key, value])
    return bundle({'plan.json': json.dumps(dict(record=item, computed=result), ensure_ascii=False, indent=2),
                   'plan.csv': text.getvalue(),
                   'review-checklist.txt': 'DRAFT PLANNING EXPORT. Nothing was sent or published. No spend was authorized.\n'
                   'Review evidence, approved wording, asset licenses, creator usage rights, disclosure, placement specs, budget assumptions '
                   'and destination page. A person must authorize external account actions separately.'})
