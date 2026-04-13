# Disco Python SDK

Find novel, statistically validated patterns in tabular data — feature interactions, subgroup effects, and conditional relationships that correlation analysis and LLMs miss.

## Installation

```bash
pip install discovery-engine-api
```

For pandas DataFrame support:

```bash
pip install discovery-engine-api[pandas]
```

## Quick Start

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

print(f"Full report: {result.report_url}")
```

Get your API key from the [Developers page](https://disco.leap-labs.com/developers), or create one programmatically:

### Getting an API Key

`Engine.signup()` and `Engine.login()` are class methods — no instance needed.

```python
# New account (free tier — 10 credits/month, no card required)
engine = await Engine.signup(email="you@example.com")

# Existing account (lost your key, new session, etc.)
engine = await Engine.login(email="you@example.com")
```

Both methods send a 6-digit verification code to the email, prompt for it interactively, and return a configured `Engine` instance with a `disco_` API key.

```python
@classmethod
async def signup(cls, email: str, *, name: Optional[str] = None, quiet: bool = False) -> Engine
```
- Raises `ValueError` if the email is already registered (409)

```python
@classmethod
async def login(cls, email: str, *, quiet: bool = False) -> Engine
```
- Raises `ValueError` if no account exists (404)

**REST API (for automated agents):** If you don't have a terminal for the interactive prompt, use the two-step flow directly:

```
# Signup
POST /api/signup         → {"status": "verification_required"}
POST /api/signup/verify  → {"key": "disco_...", "tier": "free_tier", "credits": 10}

# Login
POST /api/login          → {"status": "verification_required"}
POST /api/login/verify   → {"key": "disco_...", ...}
```

## Parameters

```python
await engine.discover(
    file: str | Path | pd.DataFrame,  # Dataset to analyze
    target_column: str,                 # Column to predict/analyze
    analysis_depth: int = 2,            # 2=default, higher=deeper analysis
    visibility: str = "public",         # "public" (free) or "private" (credits)
    title: str | None = None,           # Dataset title
    description: str | None = None,     # Dataset description
    column_descriptions: dict[str, str] | None = None,  # Improves pattern explanations
    excluded_columns: list[str] | None = None,           # Columns to exclude — see below
    use_llms: bool = False,             # LLM explanations, novelty assessment, citations (costs more) — see below
    timeout: float = 1800,              # Max seconds to wait
    # Additional kwargs forwarded to run_async():
    # task, author, source_url, timeseries_groups, ...
)
```

> **Tip:** Providing `column_descriptions` significantly improves pattern explanations. If your columns have non-obvious names, always describe them.

> **`use_llms`:** Default `False`. Slower and more expensive, but you get smarter pre-processing, literature context and novelty assessment. Set to `True` if you want Disco-generated pattern descriptions, novelty assessment with citations, and report summaries. **Public runs always use LLMs regardless of this setting.** What changes when false: pattern descriptions fall back to generic text, novelty is not assessed (all patterns marked confirmatory, no citations), report summaries are omitted, integer columns with few unique values (e.g. "month" 1-12, "hour" 0-23) may be misclassified as categorical instead of continuous, and high-cardinality text columns get generic cluster names instead of descriptive ones. Use `engine.estimate()` to check credit cost before running.

> **Visibility:** `"public"` runs are free but results are published, and analysis depth is locked to 2. `"private"` runs keep results confidential and consume credits.

> **`excluded_columns`:** Always exclude identifiers (row IDs, UUIDs), data leakage (target renamed/reformatted), and tautological columns (alternative encodings of the same construct as the target). For example, if your target is `serious`, exclude `serious_outcome`, `not_serious`, `death` — they're part of the same classification system. See [SKILL.md](../SKILL.md#preparing-your-data) for full guidance.


## Examples

### Working with Pandas DataFrames

```python
import pandas as pd
from discovery import Engine

df = pd.read_csv("data.csv")

engine = Engine(api_key="disco_...")
result = await engine.discover(
    file=df,
    target_column="outcome",
    column_descriptions={
        "age": "Patient age in years",
        "bmi": "Body mass index",
    },
    excluded_columns=["patient_id", "timestamp", "outcome_text"],  # IDs + tautological
)
```

### Running in the Background

Runs take a few minutes. While waiting, the SDK logs progress automatically:

```
Waiting for run abc123 to complete...
  Status: waiting (position 2 in queue) | Est. wait: ~8 min | Upgrade at disco.leap-labs.com/account for priority processing
  Status: processing (preprocessing — Processing data...) | Elapsed: 34.2s | ETA: ~6 min
  Status: processing (training — Modelling data...) | Elapsed: 98.7s | ETA: ~4 min
  Status: processing (interpreting — Extracting patterns...) | Elapsed: 284.1s | ETA: ~2 min
  Status: processing (reporting — Building report...) | Elapsed: 412.3s | ETA: ~1 min
Run completed in 467.8s
```

If you need to do other work while Disco runs:

```python
import asyncio
from discovery import Engine

async def main():
    async with Engine(api_key="disco_...") as engine:
        # Submit without waiting
        run = await engine.run_async(
            file="data.csv",
            target_column="outcome",
            wait=False,
        )
        print(f"Submitted run {run.run_id}, continuing...")

        # ... do other work ...

        # Check back later
        result = await engine.wait_for_completion(run.run_id, timeout=1800)
        return result

result = asyncio.run(main())
```

### Inspecting Columns Before Running

If you need to see the dataset's columns before choosing a target column — e.g., when column names are not obvious — upload first, inspect, then run without re-uploading:

```python
# Upload once and get the server's parsed column list
upload = await engine.upload_file(file="data.csv", title="My dataset")
# upload["file"]    -> {"key": "uploads/abc123.csv", "name": "data.csv",
#                        "size": 1048576, "fileHash": "sha256:..."}
# upload["columns"] -> [{"name": "col1", "type": "continuous", ...}, ...]
# upload["rowCount"] -> 5000
print(upload["columns"])
print(upload["rowCount"])

# Pass the result to avoid re-uploading
result = await engine.run_async(
    file="data.csv",
    target_column="col1",
    wait=True,
    upload_result=upload,  # skips the upload step
)
```

### Synchronous Usage

For scripts and Jupyter notebooks:

```python
from discovery import Engine

engine = Engine(api_key="disco_...")

# Simple — wraps discover(), always waits for completion
result = engine.discover_sync(
    file="data.csv",
    target_column="outcome",
)

# More control — wraps run_async(), supports wait=False
result = engine.run(
    file="data.csv",
    target_column="outcome",
    wait=True,
)
```

For Jupyter notebooks, install the jupyter extra for `engine.run()` compatibility:

```bash
pip install discovery-engine-api[jupyter]
```

Or use `await engine.discover(...)` / `await engine.run_async(...)` directly in async notebook cells.


## Working with Results

```python
# Filter for significant novel patterns
novel = [p for p in result.patterns
         if p.p_value < 0.05 and p.novelty_type == "novel"]

# Get patterns that increase the target
increasing = [p for p in result.patterns if p.target_change_direction == "max"]

# Inspect conditions
for pattern in result.patterns:
    for cond in pattern.conditions:
        print(f"  {cond['feature']}: {cond}")

# Feature importance
if result.feature_importance:
    top = sorted(result.feature_importance.scores,
                 key=lambda s: abs(s.score), reverse=True)

# Share the interactive report
print(f"Explore: {result.report_url}")
```


## Credits and Pricing

- **Public runs**: Free. Results published to public gallery. Locked to depth=2.
- **Private runs**: Credits scale with file size, depth, and run configuration. $0.10 per credit. Use `engine.estimate()` to check cost before running.

```python
# Estimate cost before running
estimate = await engine.estimate(
    file_size_mb=10.5,
    num_columns=25,
    analysis_depth=2,
    visibility="private",
)
# estimate["cost"]["credits"]                    -> 55
# estimate["cost"]["price_usd"]                  -> 5.5
# estimate["limits"]["max_file_size_mb"]          -> 5120
# estimate["limits"]["max_analysis_depth"]        -> 23  (num_columns - 2)
# estimate["limits"]["supported_formats"]         -> ["csv", "parquet", ...]
# estimate["account"]["available_credits"]        -> 60   (only if authenticated)
# estimate["account"]["sufficient"]               -> True/False
```

Manage credits and plans at [disco.leap-labs.com/account](https://disco.leap-labs.com/account).


## Account Management

```python
# Check your account — plan, credits, payment method
account = await engine.get_account()
# account["plan"]["tier"]              -> "free_tier"
# account["plan"]["name"]              -> "Explorer"
# account["plan"]["monthly_credits"]   -> 10
# account["credits"]["subscription"]   -> 10
# account["credits"]["purchased"]      -> 0
# account["credits"]["total"]          -> 10
# account["payment_method"]["on_file"] -> False
# account["stripe_publishable_key"]    -> "pk_live_..."

# Attach a payment method (Stripe PaymentMethod ID — see below)
result = await engine.add_payment_method("pm_...")
# result["payment_method_attached"]  -> True
# result["card_brand"]               -> "visa"
# result["card_last4"]               -> "4242"

# Subscribe to a plan
result = await engine.subscribe("tier_1")
# Plans: "free_tier" ($0, 10 cr/mo), "tier_1" ($49, 50 cr/mo), "tier_2" ($199, 200 cr/mo)
# result["plan"]            -> "tier_1"
# result["price_usd"]       -> 49
# result["monthly_credits"] -> 50

# Purchase credit packs (100 credits per pack, $10/pack)
result = await engine.purchase_credits(packs=1)
# result["purchased_credits"]  -> 100
# result["total_credits"]      -> 110
# result["charge_amount_usd"]  -> 10.0

# Revert to free tier
result = await engine.subscribe("free_tier")
```

### Stripe Card Tokenization

`add_payment_method()` requires a Stripe `pm_...` token. Card data goes directly to Stripe — Disco never sees it.

```python
import requests

account = await engine.get_account()
pk = account["stripe_publishable_key"]

pm = requests.post(
    "https://api.stripe.com/v1/payment_methods",
    auth=(pk, ""),
    data={
        "type": "card",
        "card[number]": "4242424242424242",
        "card[exp_month]": "12",
        "card[exp_year]": "2028",
        "card[cvc]": "123",
    },
).json()

await engine.add_payment_method(pm["id"])
```

REST equivalents for all account endpoints are documented in [SKILL.md](../SKILL.md#paying-for-credits-programmatic).


## Expected Data Format

Disco expects a **flat table** — columns for features, rows for samples.

- **One row per observation** — a patient, a sample, a transaction, a measurement, etc.
- **One column per feature** — numeric, categorical, datetime, or free text are all fine
- **One target column** — the outcome to analyze. Must have at least 2 distinct values.
- **Missing values are OK** — Disco handles them automatically. Don't drop rows or impute beforehand.

Not supported: images, raw text documents, nested/hierarchical JSON, multi-sheet Excel (use the first sheet or export to CSV).

## File Size Limits

Uploads up to **5 GB**. Files are uploaded directly to cloud storage using presigned URLs.

Supported formats: **CSV**, **TSV**, **Excel (.xlsx)**, **JSON**, **Parquet**, **ARFF**, **Feather**.

### Direct Upload

For small files, skip the 3-step presign flow and upload inline with base64:

```
POST /api/data/upload/direct
Authorization: Bearer disco_...
{"fileName": "data.csv", "content": "<base64-encoded file>"}
→ {"ok": true, "file": {...}, "columns": [...], "rowCount": 5000}
```

For large files, use presigned uploads or the SDK (`engine.upload_file()`).


## Return Value

### EngineResult

```python
@dataclass
class EngineResult:
    run_id: str
    report_id: str | None                          # Report UUID (used in report_url)
    status: str                                    # "pending", "processing", "completed", "failed"
    dataset_title: str | None                      # Title of the dataset
    dataset_description: str | None                # Description of the dataset
    total_rows: int | None
    target_column: str | None                      # Column being predicted/analyzed
    task: str | None                               # "regression", "binary_classification", "multiclass_classification"
    summary: Summary | None                        # LLM-generated insights
    patterns: list[Pattern]                        # Discovered patterns (the core output)
    columns: list[Column]                          # Feature info and statistics
    correlation_matrix: list[CorrelationEntry]     # Feature correlations
    feature_importance: FeatureImportance | None   # Global importance scores
    job_id: str | None                             # Job ID for tracking
    job_status: str | None                         # Job queue status
    queue_position: int | None                     # Position in queue when pending (1 = next up)
    current_step: str | None                       # Active pipeline step (preprocessing, training, interpreting, reporting)
    current_step_message: str | None               # Human-readable description of the current step
    estimated_wait_seconds: int | None             # Estimated queue wait time in seconds (pending only)
    error_message: str | None
    report_url: str | None                         # Shareable link to interactive web report
    dashboard_urls: dict[str, dict[str, str]] | None  # Direct links to report sections (summary, patterns, territory, features)
    hints: list[str]                               # Upgrade hints (non-empty for free-tier users with hidden patterns)
    hidden_deep_count: int                         # Patterns hidden for free-tier accounts (upgrade to see all)
    hidden_deep_novel_count: int                   # Novel patterns hidden for free-tier accounts
```

### Pattern

```python
@dataclass
class Pattern:
    id: str
    task: str                           # "regression", "binary_classification", "multiclass_classification"
    target_column: str                  # Column being analyzed
    description: str                    # Human-readable description
    conditions: list[dict]              # Conditions defining the pattern
    p_value: float                      # FDR-adjusted p-value
    p_value_raw: float | None           # Raw p-value before adjustment
    novelty_type: str                   # "novel" or "confirmatory"
    novelty_explanation: str            # Why this is novel or confirmatory
    citations: list[dict]               # Academic citations
    target_change_direction: str        # "max" (increases target) or "min" (decreases)
    abs_target_change: float            # Magnitude of effect
    target_score: float                 # Mean target value (regression) or class fraction (classification) in the subgroup
    support_count: int                  # Rows matching this pattern
    support_percentage: float           # Percentage of dataset
    target_class: str | None            # For classification tasks
    target_mean: float | None           # For regression tasks
    target_std: float | None
```

#### Pattern Conditions

Each condition in `pattern.conditions` is a dict with a `type` field:

**Continuous condition** — a numeric range:
```python
{
    "type": "continuous",
    "feature": "age",
    "min_value": 45.0,
    "max_value": 65.0,
    "min_q": 0.35,   # quantile of min_value
    "max_q": 0.72    # quantile of max_value
}
```

**Categorical condition** — a set of values:
```python
{
    "type": "categorical",
    "feature": "region",
    "values": ["north", "east"]
}
```

**Datetime condition** — a time range:
```python
{
    "type": "datetime",
    "feature": "date",
    "min_value": 1609459200000,   # epoch ms
    "max_value": 1640995200000,
    "min_datetime": "2021-01-01", # human-readable
    "max_datetime": "2022-01-01"
}
```

### PatternGroup

```python
@dataclass
class PatternGroup:
    pattern_ids: list[str]              # IDs of patterns in this group
    explanation: str                    # Why these patterns are grouped
```

### Summary

```python
@dataclass
class Summary:
    overview: str                       # High-level summary of findings
    key_insights: list[str]             # Main takeaways
    novel_patterns: PatternGroup        # Novel pattern IDs and explanation
    selected_pattern_id: str | None     # ID of the highlighted/featured pattern
```

### CorrelationEntry

```python
@dataclass
class CorrelationEntry:
    feature_x: str
    feature_y: str
    value: float
```

### Column

```python
@dataclass
class Column:
    id: str
    name: str
    display_name: str
    type: str                           # "continuous" or "categorical"
    data_type: str                      # "int", "float", "string", "boolean", "datetime"
    enabled: bool
    description: str | None
    mean: float | None
    median: float | None
    std: float | None
    min: float | None
    max: float | None
    iqr_min: float | None               # 25th percentile
    iqr_max: float | None               # 75th percentile
    mode: str | None                    # Most common value (categorical columns)
    approx_unique: int | None           # Approximate distinct value count
    null_percentage: float | None
    feature_importance_score: float | None  # Signed importance score
```

### FeatureImportance

Scores are **signed** — positive means the feature increases the prediction, negative means it decreases it.

```python
@dataclass
class FeatureImportance:
    kind: str                           # "global" | "local"
    baseline: float                     # Baseline model output
    scores: list[FeatureImportanceScore]

@dataclass
class FeatureImportanceScore:
    feature: str
    score: float                        # Signed importance score
```


## Error Handling

```python
from discovery import Engine
from discovery.errors import (
    AuthenticationError,
    InsufficientCreditsError,
    RateLimitError,
    RunFailedError,
    RunNotFoundError,
    PaymentRequiredError,
)

try:
    result = await engine.discover(file="data.csv", target_column="target")
except AuthenticationError as e:
    print(e.suggestion)  # "Check your API key at https://disco.leap-labs.com/developers"
except InsufficientCreditsError as e:
    print(f"Need {e.credits_required}, have {e.credits_available}")
    print(e.suggestion)  # "Run with visibility='public' (free, results published) or purchase credits with engine.purchase_credits()."
except RateLimitError as e:
    print(f"Retry after {e.retry_after} seconds")
except RunFailedError as e:
    print(f"Run {e.run_id} failed: {e}")
except RunNotFoundError as e:
    print(f"Run {e.run_id} not found — may have been cleaned up")
except PaymentRequiredError as e:
    print(e.suggestion)  # "Attach a payment method with engine.add_payment_method(...)"
except TimeoutError:
    pass  # Retrieve later with engine.wait_for_completion(run_id)
```

All errors include a `suggestion` field with actionable instructions.


## MCP Server

Disco is available as an [MCP server](https://disco.leap-labs.com/.well-known/mcp.json) with tools for the full discovery lifecycle — estimate, analyze, check status, get results, manage account. To subscribe or purchase credits via MCP, call `discovery_add_payment_method` first to attach a Stripe payment method.

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

## Links

- **PyPI**: [discovery-engine-api](https://pypi.org/project/discovery-engine-api/)
- **API keys**: [disco.leap-labs.com/developers](https://disco.leap-labs.com/developers)
- **LLM-friendly docs**: [disco.leap-labs.com/llms-full.txt](https://disco.leap-labs.com/llms-full.txt)
- **MCP manifest**: [disco.leap-labs.com/.well-known/mcp.json](https://disco.leap-labs.com/.well-known/mcp.json)
- **Credits & billing**: [disco.leap-labs.com/account](https://disco.leap-labs.com/account)
- **Public reports**: [disco.leap-labs.com/discover](https://disco.leap-labs.com/discover)
