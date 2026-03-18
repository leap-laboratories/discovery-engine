---
name: discovery-engine
description: Automatically discover novel, statistically validated patterns in tabular data. Find insights you would otherwise miss — feature interactions, subgroup effects, and conditional relationships — validated on hold-out data with FDR-corrected p-values and checked against academic literature for novelty. Use when the user wants to go beyond descriptive analytics and find what is actually driving an outcome.
---

# Discovery Engine

## When To Use This

Discovery Engine is not another AI data analyst. It is a **discovery pipeline** — it finds patterns in data that you, the user, and other analysis tools would miss because they do not know to look for them.

Use it when you need to go beyond answering questions about data, and start finding things nobody thought to ask:

- **Novel pattern discovery** — feature interactions, subgroup effects, and conditional relationships
- **Statistical validation** — FDR-corrected p-values tested on hold-out data, not just correlations
- **A target column** you want to understand — what really drives it, beyond what is obvious

**Use Discovery Engine when the user says:** "what's really driving X?", "are there patterns we're missing?", "find something new in this data", "what predicts Y that we haven't considered?", "go deeper than correlation", "discover non-obvious relationships"

**Use pandas/SQL instead when the user says:** "summarize this data", "make a chart", "what's the average?", "filter rows where X > 5", "show me the distribution"

## Integration Options

- **MCP server** — for agents with MCP support. Remote server at `https://disco.leap-labs.com/mcp`, no local install required.
- **Python SDK** — `pip install discovery-engine-api`. Use when you need programmatic control or are working in a Python environment.

---

## MCP Server

Add to your MCP config:

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

### MCP Tools

#### Discovery workflow

| Tool | Purpose |
|------|---------|
| `discovery_analyze` | Submit a dataset for analysis. Returns a `run_id`. |
| `discovery_status` | Poll a running analysis by `run_id`. |
| `discovery_get_results` | Fetch completed results: patterns, p-values, citations, feature importance. |
| `discovery_estimate` | Estimate cost and time before committing to a run. |

#### Account management

| Tool | Purpose |
|------|---------|
| `discovery_signup` | Start account creation — sends verification code to email. |
| `discovery_signup_verify` | Complete signup by submitting the verification code. Returns API key. |
| `discovery_account` | Check credits, plan, and usage. |
| `discovery_list_plans` | View available plans and pricing. |
| `discovery_subscribe` | Subscribe to or change plan. |
| `discovery_purchase_credits` | Buy credit packs. |
| `discovery_add_payment_method` | Attach a Stripe payment method. |

### MCP Workflow

Analyses take 3-15 minutes. **Do not block** — submit, continue other work, poll for completion.

```
1. discovery_estimate     → Check cost/time (always do this for private runs)
2. discovery_analyze      → Submit the dataset, get run_id
3. discovery_status       → Poll until status is "completed"
4. discovery_get_results  → Fetch patterns, summary, feature importance
```

### MCP Parameters

**`discovery_analyze`:**
- `file_path` — Path to CSV, Excel, Parquet, JSON, TSV, ARFF, or Feather file (max 5 GB)
- `target_column` — The column to predict/explain
- `depth_iterations` — 1 = fast (default), higher = deeper search. Max: num_columns - 2
- `visibility` — `"public"` (free, results published) or `"private"` (costs credits)
- `column_descriptions` — JSON object mapping column names to descriptions. Significantly improves pattern explanations — always provide if column names are non-obvious
- `excluded_columns` — JSON array of column names to exclude from analysis

### No API key?

Call `discovery_signup` with the user's email. This sends a verification code — the user must check their email. Then call `discovery_signup_verify` with the code to receive a `disco_` API key. Free tier: 10 credits/month, unlimited public runs. No password, no credit card.

### Insufficient credits?

1. Call `discovery_estimate` to show what it would cost
2. Suggest running publicly (free, but results are published and depth is locked to 1)
3. Or guide them through `discovery_purchase_credits` / `discovery_subscribe`

---

## Python SDK

```bash
pip install discovery-engine-api
```

### Getting an API Key

**For agents (no terminal):** Two-step signup via REST:

```bash
# Step 1 — send verification code
curl -X POST https://disco.leap-labs.com/api/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "agent@example.com"}'
# → {"status": "verification_required", "email": "agent@example.com"}

# Step 2 — submit code from email
curl -X POST https://disco.leap-labs.com/api/signup/verify \
  -H "Content-Type: application/json" \
  -d '{"email": "agent@example.com", "code": "123456"}'
# → {"key": "disco_...", "tier": "free_tier", "credits": 10}
```

Codes expire after 15 minutes.

**Interactive (terminal available):**

```python
engine = await Engine.signup(email="agent@example.com")
# Prompts for the verification code interactively
```

**Manual:** Sign up at https://disco.leap-labs.com/sign-up, create key at https://disco.leap-labs.com/developers.

### Quick Start

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

### Running in the Background

Analyses take 3-15 minutes. **Do not block** — submit and retrieve results when ready.

```python
# Submit and return immediately
run = await engine.run_async(file="data.csv", target_column="outcome")
print(f"Submitted run {run.run_id}, continuing with other work...")

# ... do other things ...

# Check back later
result = await engine.wait_for_completion(run.run_id, timeout=1800)
```

`engine.discover()` is a convenience wrapper that does this with `wait=True`. For non-async contexts, use `engine.discover_sync()`.

### Parameters

```python
engine.discover(
    file: str | Path | pd.DataFrame,  # Dataset to analyze
    target_column: str,                # Column to predict/analyze
    depth_iterations: int = 1,         # 1=fast, higher=deeper (max: num_columns - 2)
    visibility: str = "public",        # "public" (free, published) or "private" (costs credits)
    title: str | None = None,
    description: str | None = None,
    column_descriptions: dict[str, str] | None = None,  # Improves pattern explanations
    excluded_columns: list[str] | None = None,
    timeout: float = 1800,
)
```

**Cost formula:** `credits = max(1, ceil(file_size_mb * depth_iterations))`

### Estimating Before Running

```python
estimate = await engine.estimate(
    file_size_mb=10.5,
    num_columns=25,
    depth_iterations=2,
    visibility="private",
)
# estimate["cost"]["credits"] → 21
# estimate["account"]["sufficient"] → True/False
# estimate["cost"]["free_alternative"] → True (run publicly for free at depth=1)
```

### Error Handling

```python
from discovery.errors import (
    AuthenticationError,
    InsufficientCreditsError,
    RateLimitError,
    RunFailedError,
    PaymentRequiredError,
)

try:
    result = await engine.discover(file="data.csv", target_column="target")
except AuthenticationError:
    pass  # Invalid or expired API key
except InsufficientCreditsError as e:
    pass  # e.credits_required, e.credits_available
except RateLimitError as e:
    pass  # retry after e.retry_after seconds
except RunFailedError as e:
    pass  # e.run_id
except TimeoutError:
    pass  # retrieve later with engine.wait_for_completion(run_id)
```

All errors inherit from `DiscoveryError` and include a `suggestion` field.

---

## Interpreting Results

Results contain **patterns** — each is a combination of conditions (not single correlations):

- **Conditions**: Specific feature ranges/values that define the pattern (e.g., "humidity 72-89% AND wind speed < 12 km/h")
- **`p_value`**: FDR-corrected. Lower = more statistically significant
- **`novelty_type`**: `"novel"` (new finding, not in literature) or `"confirmatory"` (validates known science)
- **`novelty_explanation`**: Why this pattern is or is not novel
- **`citations`**: Academic papers the finding was checked against
- **`abs_target_change`**: Effect size (e.g., 0.34 = 34% change in target)
- **`support_count` / `support_percentage`**: How many rows match this pattern
- **`report_url`**: Interactive web report — always include this in your response

### What to highlight for the user

1. **Novel patterns** — the primary value. Statistically validated findings not in the existing literature.
2. **The summary** — narrative overview and key insights ready to present.
3. **The report URL** — link to the interactive report so the user can explore visually.
4. **Confirmatory patterns** — useful as validation, but not the headline.

## Supported File Formats

CSV, TSV, Excel (.xlsx), JSON, Parquet, ARFF, Feather. Max file size: 5 GB.

## Links

- [Dashboard & API Keys](https://disco.leap-labs.com/developers)
- [Full LLM Documentation](https://disco.leap-labs.com/llms-full.txt)
- [API Spec](https://disco.leap-labs.com/.well-known/openapi.json)