# Analytics, experiments and reports

Everything here is computed from values saved in the local agency database. There is no
analytics connector (Matomo, Search Console, GA4, social APIs) yet: values arrive by manual
entry or CSV import. No engagement, revenue or performance figure is shown unless you
recorded it.

## Metrics

- **Metric definitions**: name, unit, direction, source label, formula note and how dated
  values combine (`sum`, `mean` or `last`).
- **Metric values**: metric, date, value, optional channel and variant, optional campaign.
- **CSV import** (Metric values tab): UTF-8 `.csv`, columns `date,metric,value` and optional
  `channel,variant`; 2 MB and 2,000 rows at most. Metric names must match existing
  definitions. The whole file is saved in one transaction or not at all.
- **KPI summary**: per metric, the dated series, first and latest value, change, change in
  percent, period total/average/latest and per-channel values, with a trend line when there
  are at least two dates. Values are not de-duplicated across platforms and no cross-platform
  attribution is inferred.

## Experiments

An experiment records hypothesis, variable, primary and guardrail metrics, decision rule and
variants (label, control flag, sample size, conversions). The result is computed on read and
cannot be edited: a two-sided two-proportion z-test of each treatment against the control
(pooled standard error), a 95% interval for the difference, and a Bonferroni-adjusted
threshold when several treatments share one control. It is only computed when every group has
at least 10 conversions and 10 non-conversions; otherwise the record says more data is
needed instead of reporting significance. The author's written conclusion is stored
separately and never changes a computed value.

## Reports

A report selects a period, metrics and experiments, plus the author's summary,
interpretation, recommendations and next actions. **Render report** downloads a ZIP with
`report.html` (printable), `data.csv` and `report.json`. Sections tagged FACT are generated
from stored values only (for example "Clicks increased from 120 on 2030-03-01 to 180 on
2030-03-15 (+50.0%)"); narrative sections are labelled as the author's words and are HTML
escaped. There is no AI-written commentary and no PDF renderer; print the HTML to PDF from a
browser.

## Learnings

A learning records a finding with category, confidence, audience/channel and tags. It can be
marked `validated` only when it links an experiment, report or research source.

## Not implemented

Provider connectors, automatic metric retrieval, attribution modelling, AI narrative,
dashboards beyond the KPI summary table, and tests other than the two-proportion z-test.
