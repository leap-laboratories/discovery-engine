# MCP Server

Discovery Engine is available as an MCP server — add it to Claude, Cursor, Windsurf, or any MCP-compatible client in one config block.

**For AI agents:** use [`SKILL.md`](../SKILL.md) instead — it's written for agents, not humans.

## Setup

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

Get an API key at [disco.leap-labs.com/docs](https://disco.leap-labs.com/docs) or via [`discovery_signup`](#discovery_signup).

---

## Tools

### Discovery

#### `discovery_estimate`

Estimate cost and time before committing to a run. Always call this before private runs.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_size_mb` | float | required | File size in MB |
| `num_columns` | int | required | Number of columns |
| `num_rows` | int | optional | Row count — improves time estimate |
| `depth_iterations` | int | `1` | Depth of search |
| `visibility` | string | `"public"` | `"public"` or `"private"` |

Returns cost in credits, time estimate (low/median/high seconds), and whether your account has sufficient credits.

```python
estimate = await engine.estimate(
    file_size_mb=10.5,
    num_columns=25,
    num_rows=5000,
    depth_iterations=2,
    visibility="private",
)
# estimate["cost"]["credits"]                     → 21
# estimate["cost"]["free_alternative"]            → True
# estimate["time_estimate"]["estimated_seconds"]  → 360
# estimate["account"]["sufficient"]               → True/False
```

#### `discovery_analyze`

Submit a dataset for analysis. Returns a `run_id` immediately — poll with `discovery_status`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `target_column` | string | required | Column to predict/analyze |
| `file_path` | string | optional | Path to dataset file |
| `file_ref` | string/object | optional | Pre-uploaded file reference (avoids re-uploading) |
| `depth_iterations` | int | `1` | `1` = fast, higher = deeper. Max: `num_columns − 2` |
| `visibility` | string | `"public"` | `"public"` (free, results published) or `"private"` (costs credits) |
| `title` | string | optional | Dataset title |
| `description` | string | optional | Dataset description |
| `column_descriptions` | object | optional | `{"col": "description"}` — significantly improves pattern explanations |
| `excluded_columns` | array | optional | Columns to exclude from analysis |
| `author` | string | optional | Dataset author |
| `source_url` | string | optional | Original data source URL |

Supported formats: CSV, TSV, Excel (.xlsx/.xls), JSON, Parquet, ARFF, Feather. Max 5 GB.

Provide `file_path` or `file_ref`, not both.

#### `discovery_status`

Poll a running analysis. Call every 30–60 seconds — runs take 3–15 minutes.

| Parameter | Type | Description |
|-----------|------|-------------|
| `run_id` | string | Run ID from `discovery_analyze` |

Returns: `status` (`"pending"`, `"running"`, `"completed"`, `"failed"`), `error_message`.

#### `discovery_get_results`

Fetch complete results. Only call after `discovery_status` returns `"completed"`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `run_id` | string | Run ID from `discovery_analyze` |

Returns: patterns (with p-values, conditions, citations, novelty scores), feature importance scores, LLM-generated summary, and `report_url`.

---

### Account

#### `discovery_signup`

Start account creation. Sends a 6-digit verification code to the provided email.

| Parameter | Type | Description |
|-----------|------|-------------|
| `email` | string | Email for the new account |
| `name` | string | Optional display name |

Returns `{"status": "verification_required"}`. The user must check their email for the code.

#### `discovery_signup_verify`

Complete account creation with the verification code.

| Parameter | Type | Description |
|-----------|------|-------------|
| `email` | string | Same email used in `discovery_signup` |
| `code` | string | 6-digit code from the verification email |

Returns: API key (`disco_...`), tier, and initial credit balance.

#### `discovery_account`

Check plan, credit balance, and payment method status.

#### `discovery_list_plans`

List available subscription plans with pricing and monthly credit allowances.

#### `discovery_subscribe`

Subscribe to or change a plan. Requires a payment method on file.

| Parameter | Type | Description |
|-----------|------|-------------|
| `plan` | string | `"free_tier"`, `"tier_1"` (Researcher, $49/mo), or `"tier_2"` (Team, $199/mo) |

#### `discovery_purchase_credits`

Buy credit packs. 20 credits per pack, $20/pack. Requires a payment method on file.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `packs` | int | `1` | Number of packs to purchase |

#### `discovery_add_payment_method`

Attach a Stripe payment method. Required before purchasing credits or subscribing to a paid plan.

| Parameter | Type | Description |
|-----------|------|-------------|
| `payment_method_id` | string | Stripe `pm_...` token |

For programmatic card tokenization without a browser, see [Python SDK — Paying for Credits](python-sdk.md#paying-for-credits-programmatic).

---

## Workflow

Runs take 3–15 minutes. **Don't block on them** — submit and continue other work.

```
1. discovery_estimate     → check cost before committing (always do this for private runs)
2. discovery_analyze      → submit dataset, get run_id
3. discovery_status       → poll every 30–60s until "completed"
4. discovery_get_results  → fetch patterns, summary, feature importance
```

---

## Error Handling

| Situation | What to do |
|-----------|------------|
| Run failed | Check `error_message` from `discovery_status`. Surface to user — don't retry automatically. |
| Insufficient credits | Offer free public run (depth=1) or ask permission before calling `discovery_purchase_credits`. Never purchase autonomously without user authorization. |
| No payment method | Call `discovery_add_payment_method` to attach a card, then retry. |
| Signup failed | Retry once. If it fails again, surface the error to the user — don't loop. |

---

## Pricing

| | Cost |
|---|---|
| Public runs (depth=1) | Free — results published to public gallery |
| Private runs | `ceil(file_size_mb × depth_iterations)` credits |
| Free tier | 10 credits/month, no card required |
| Researcher | $49/month, 50 credits |
| Team | $199/month, 200 credits |
| Credit packs | $20/pack (20 credits, $1/credit) |

---

## Links

- [API keys & docs](https://disco.leap-labs.com/docs)
- [Agent skill file](../SKILL.md)
- [Python SDK reference](python-sdk.md)
- [OpenAPI spec](https://disco.leap-labs.com/.well-known/openapi.json)
