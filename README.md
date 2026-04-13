# Disco

**Find novel, statistically validated patterns in tabular data** — feature interactions, subgroup effects, and conditional relationships that correlation analysis and LLMs miss.

[![PyPI](https://img.shields.io/pypi/v/discovery-engine-api)](https://pypi.org/project/discovery-engine-api/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Made by [Leap Laboratories](https://www.leap-labs.com).

---

## What it actually does

Most data analysis starts with a question. Disco starts with the data.

Without biases or assumptions, it finds combinations of feature conditions that significantly shift your target column — things like "patients aged 45–65 with low HDL *and* high CRP have 3× the readmission rate" — without you needing to hypothesise that interaction first.

Each pattern is:
- **Validated on a hold-out set** — increases the chance of generalisation
- **FDR-corrected** — p-values included, adjusted for multiple testing
- **Checked against academic literature** — to help you understand what you've found, and identify if it is novel.

The output is structured: conditions, effect sizes, p-values, citations, and a novelty classification for every pattern found.

**Use it when:** "which variables are most important with respect to X", "are there patterns we're missing?", "I don't know where to start with this data", "I need to understand how A and B affect C".

**Not for:** summary statistics, visualisation, filtering, SQL queries — use pandas for those

---

## Quickstart

```bash
pip install discovery-engine-api
```

Get an API key:

```bash
# Step 1: request verification code (no password, no card)
curl -X POST https://disco.leap-labs.com/api/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com"}'

# Step 2: submit code from email → get key
curl -X POST https://disco.leap-labs.com/api/signup/verify \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "code": "123456"}'
# → {"key": "disco_...", "credits": 10, "tier": "free_tier"}
```

Or create a key at [disco.leap-labs.com/developers](https://disco.leap-labs.com/developers).

Run your first analysis:

```python
from discovery import Engine

engine = Engine(api_key="disco_...")
result = await engine.discover(
    file="data.csv",
    target_column="outcome",
)

for pattern in result.patterns:
    if pattern.p_value < 0.05 and pattern.novelty_type == "novel":
        print(f"{pattern.description} (p={pattern.p_value:.4f})")

print(f"Explore: {result.report_url}")
```

Runs take a few minutes. `discover()` polls automatically and logs progress — queue position, estimated wait, current pipeline step, and ETA. For background runs, see [Running asynchronously](#running-asynchronously).

→ [Full Python SDK reference](docs/python-sdk.md) · [Example notebook](notebooks/quickstart.ipynb)

---

## What you get back

Each `Pattern` in `result.patterns` looks like this (real output from a crop yield dataset):

```python
Pattern(
    description="When humidity is between 72–89% AND wind speed is below 12 km/h, "
                "crop yield increases by 34% above the dataset average",
    conditions=[
        {"type": "continuous", "feature": "humidity_pct",
         "min_value": 72.0, "max_value": 89.0},
        {"type": "continuous", "feature": "wind_speed_kmh",
         "min_value": 0.0, "max_value": 12.0},
    ],
    p_value=0.003,              # FDR-corrected
    novelty_type="novel",
    novelty_explanation="Published studies examine humidity and wind speed as independent "
                        "predictors, but this interaction effect — where low wind amplifies "
                        "the benefit of high humidity within a specific range — has not been "
                        "reported in the literature.",
    citations=[
        {"title": "Effects of relative humidity on cereal crop productivity",
         "authors": ["Zhang, L.", "Wang, H."], "year": "2021",
         "journal": "Journal of Agricultural Science"},
    ],
    target_change_direction="max",
    abs_target_change=0.34,     # 34% increase
    support_count=847,          # rows matching this pattern
    support_percentage=16.9,
)
```

Key things to notice:

- **Patterns are combinations of conditions** — humidity AND wind speed together, not just "more humidity is better"
- **Specific thresholds** — 72–89%, not a vague correlation
- **Novel vs confirmatory** — every pattern is classified; confirmatory ones validate known science, novel ones are what you came for
- **Citations** — shows what IS known, so you can see what's genuinely new
- **`report_url`** links to an interactive web report with all patterns visualised

The `result.summary` gives an LLM-generated narrative overview:

```python
result.summary.overview
# "Disco identified 14 statistically significant patterns. 5 are novel.
#  The strongest driver is a previously unreported interaction between humidity
#  and wind speed at specific thresholds."

result.summary.key_insights
# ["Humidity × low wind speed at 72–89% humidity produces a 34% yield increase — novel.",
#  "Soil nitrogen above 45 mg/kg shows diminishing returns when phosphorus is below 12 mg/kg.",
#  ...]
```

---

## How it works

Disco is a pipeline, not prompt engineering over data. It:

1. Trains machine learning models on a subset of your data
2. Uses interpretability techniques to extract learned patterns
3. Validates every pattern on the held-out data with FDR correction (Benjamini-Hochberg)
4. Checks surviving patterns against academic literature via semantic search

You cannot replicate this by writing pandas code or asking an LLM to look at a CSV. It finds structure that hypothesis-driven analysis misses because it doesn't start with hypotheses.

---

## Preparing your data

Before running, exclude columns that would produce meaningless findings. Disco finds statistically real patterns — but if the input includes columns that are definitionally related to the target, the patterns will be tautological.

**Exclude:**
1. **Identifiers** — row IDs, UUIDs, patient IDs, sample codes
2. **Data leakage** — the target renamed or reformatted (e.g., `diagnosis_text` when the target is `diagnosis_code`)
3. **Tautological columns** — alternative encodings of the same construct as the target. If target is `serious`, then `serious_outcome`, `not_serious`, `death` are all part of the same classification. If target is `profit`, then `revenue` and `cost` together compose it. If target is a survey index, the sub-items are tautological.

> Full guidance with examples: [SKILL.md](SKILL.md#preparing-your-data)

---

## Parameters

```python
await engine.discover(
    file="data.csv",           # path, Path, or pd.DataFrame
    target_column="outcome",   # column to predict/explain
    analysis_depth=2,          # 2=default, higher=deeper analysis, lower = faster and cheaper
    visibility="public",       # "public" (always free, data and report is published) or "private" (costs credits)
    column_descriptions={      # improves pattern explanations and literature context
        "bmi": "Body mass index",
        "hdl": "HDL cholesterol in mg/dL",
    },
    excluded_columns=["id", "timestamp"],  # see "Preparing your data" above
    use_llms=False,                        # Defaults to False. If True, runs are slower and more expensive, but you get smarter pre-processing, summary page, literature context and novelty assessment. Public runs always use LLMs.
    title="My dataset",
    description="...", # improves pattern explanations and literature context
)
```

> Public runs are free but results are published. Set `visibility="private"` for private data — this costs credits.

---

## Running asynchronously

Runs take a few minutes. For agent workflows or scripts that do other work in parallel:

```python
# Submit without waiting
run = await engine.run_async(file="data.csv", target_column="outcome", wait=False)
print(f"Submitted {run.run_id}, continuing...")

# ... do other things ...

result = await engine.wait_for_completion(run.run_id, timeout=1800)
```

For synchronous scripts and Jupyter notebooks:

```python
result = engine.run(file="data.csv", target_column="outcome", wait=True)
# or: pip install discovery-engine-api[jupyter] for notebook compatibility
```

---

## MCP server

Disco is available as an MCP server — no local install required.

```json
{
  "mcpServers": {
    "discovery-engine": {
      "url": "https://disco.leap-labs.com/mcp",
      "env": { "DISCOVERY_API_KEY": "disco_..." }
    }
  }
}
```

Tools: `discovery_list_plans`, `discovery_estimate`, `discovery_upload`, `discovery_analyze`, `discovery_status`, `discovery_get_results`, `discovery_account`, `discovery_signup`, `discovery_signup_verify`, `discovery_login`, `discovery_login_verify`, `discovery_add_payment_method`, `discovery_subscribe`, `discovery_purchase_credits`.

→ [Full agent skill file](SKILL.md)

---

## Pricing

| | Cost |
|---|---|
| Public runs | Free — results and data are published |
| Private runs | Credits vary by file size and configuration — use `engine.estimate()` |
| Free tier | 10 credits/month, no card required |
| Researcher | $49/month — 50 credits |
| Team | $199/month — 200 credits |
| Credits | $0.10 per credit |

Estimate before running:

```python
estimate = await engine.estimate(file_size_mb=10.5, num_columns=25, analysis_depth=2, visibility="private")
# estimate["cost"]["credits"] → 55
# estimate["account"]["sufficient"] → True/False
```

Account management is fully programmatic — attach payment methods, subscribe to plans, and purchase credits via the SDK or REST API. See [Python SDK reference](docs/python-sdk.md#account-management) or [SKILL.md](SKILL.md#paying-for-credits-programmatic).

---

## Expected data format

Disco expects a **flat table** — columns for features, rows for samples.

```
| patient_id | age | bmi  | smoker | outcome |
|------------|-----|------|--------|---------|
| 001        | 52  | 28.3 | yes    | 1       |
| 002        | 34  | 22.1 | no     | 0       |
| ...        | ... | ...  | ...    | ...     |
```

- **One row per observation** — a patient, a sample, a transaction, a measurement, etc.
- **One column per feature** — numeric, categorical, datetime, or free text are all fine
- **One target column** — the outcome you want to understand. Must have at least 2 distinct values.
- **Missing values are OK** — Disco handles them automatically. Don't drop rows or impute beforehand.
- **No pivoting needed** — if your data is already in a flat table, it's ready to go

**Supported formats:** CSV, TSV, Excel (.xlsx), JSON, Parquet, ARFF, Feather. Max 5 GB.

**Not supported:** images, raw text documents, nested/hierarchical JSON, multi-sheet Excel (use the first sheet or export to CSV)

---

## Compared to other tools

| Goal | Tool |
|---|---|
| Summary statistics, data quality | ydata-profiling, sweetviz |
| Predictive model | AutoML (auto-sklearn, TPOT, H2O) |
| Quick correlations | pandas, seaborn |
| Answer a specific question about data | ChatGPT, Claude |
| **Find what you don't know to look for** | **Disco** |

Disco isn't a replacement for EDA or AutoML — it finds the patterns those tools miss. We [tested 18 data analysis tools](https://www.leap-labs.com/research/the-patterns-that-agents-miss) on a dataset with known ground-truth patterns. Most confidently reported wrong results. Disco was the only one that found every pattern.

---

## Links

- [Dashboard](https://disco.leap-labs.com)
- [API keys](https://disco.leap-labs.com/developers)
- [Python SDK on PyPI](https://pypi.org/project/discovery-engine-api/)
- [Python SDK reference](docs/python-sdk.md)
- [OpenAPI spec](https://disco.leap-labs.com/.well-known/openapi.json)
- [Agent / MCP docs](SKILL.md)
- [LLM-friendly reference](llms.txt)
- [OpenAPI spec](https://disco.leap-labs.com/.well-known/openapi.json)
- [OpenAPI spec (in-repo)](docs/openapi.json)
- [Public reports gallery](https://disco.leap-labs.com/discover)

---
