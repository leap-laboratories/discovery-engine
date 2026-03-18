# Discovery Engine Python SDK

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

Get your API key from the [Developers page](https://disco.leap-labs.com/developers).

## Parameters

```python
await engine.discover(
    file: str | Path | pd.DataFrame,  # Dataset to analyze
    target_column: str,                 # Column to predict/analyze
    depth_iterations: int = 1,          # 1=fast, higher=deeper search
    visibility: str = "public",         # "public" (free) or "private" (credits)
    title: str | None = None,           # Dataset title
    description: str | None = None,     # Dataset description
    column_descriptions: dict[str, str] | None = None,  # Improves pattern explanations
    excluded_columns: list[str] | None = None,           # Columns to exclude (e.g., IDs)
    task: str | None = None,            # "regression" | "binary_classification" | "multiclass_classification" (auto-detected)
    author: str | None = None,          # Dataset author attribution
    source_url: str | None = None,      # URL of the original data source
    timeout: float = 1800,              # Max seconds to wait
)
```

> **Tip:** Providing `column_descriptions` significantly improves pattern explanations. If your columns have non-obvious names, always describe them.

> **Depth and visibility:** Public runs are always `depth_iterations=1` regardless of settings. To use `depth_iterations > 1`, set `visibility="private"`. Private runs consume credits based on file size × depth.


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
    excluded_columns=["patient_id", "timestamp"],
)
```

### Running in the Background

Runs take 3–15 minutes. If you need to do other work while Discovery Engine runs:

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

- **Public runs**: Free. Results published to public gallery. Locked to depth=1.
- **Private runs**: 1 credit per MB per depth iteration. $1.00 per credit.
- **Formula**: `credits = max(1, ceil(file_size_mb * depth_iterations))`

```python
# Estimate cost before running
estimate = await engine.estimate(
    file_size_mb=10.5,
    num_columns=25,
    depth_iterations=2,
    visibility="private",
)
# estimate["cost"]["credits"]               -> 21
# estimate["cost"]["price_usd"]             -> 21.0
# estimate["cost"]["free_alternative"]      -> True
# estimate["cost"]["free_alternative_note"] -> "Run publicly for free (depth locked to 1, results published)"
# estimate["time_estimate"]["estimated_seconds"] -> 360
# estimate["account"]["sufficient"]         -> True/False
# estimate["limits"]["max_depth"]           -> 23  (num_columns - 2)
```

Manage credits and plans at [disco.leap-labs.com/account](https://disco.leap-labs.com/account).


## File Size Limits

Uploads up to **5 GB**. Files are uploaded directly to cloud storage using presigned URLs.

Supported formats: **CSV**, **TSV**, **Excel (.xlsx)**, **JSON**, **Parquet**, **ARFF**, **Feather**.


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
    error_message: str | None
    report_url: str | None                         # Shareable link to interactive web report
    hints: list[str]                               # Upgrade hints (non-empty for free-tier users with hidden patterns)
    hidden_deep_count: int                         # Patterns hidden due to depth limit (free tier)
    hidden_deep_novel_count: int                   # Novel patterns hidden due to depth limit
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

### Summary

```python
@dataclass
class Summary:
    overview: str                       # High-level summary of findings
    key_insights: list[str]             # Main takeaways
    novel_patterns: PatternGroup        # Novel pattern IDs and explanation
    selected_pattern_id: str | None     # ID of the highlighted/featured pattern
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

Computed using **Hierarchical Perturbation (HiPe)**, an ablation-based method. Scores are **signed** — positive means the feature increases the prediction, negative means it decreases it.

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
    print(e.suggestion)  # "Run with visibility='public' (free, depth=1) or purchase credits with engine.purchase_credits()."
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

Discovery Engine is available as an [MCP server](https://disco.leap-labs.com/.well-known/mcp.json) with tools for the full discovery lifecycle — estimate, analyze, check status, get results, manage account. To subscribe or purchase credits via MCP, call `discovery_add_payment_method` first to attach a Stripe payment method.

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
