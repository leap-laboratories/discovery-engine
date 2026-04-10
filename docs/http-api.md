# Disco HTTP API Reference

Base URL: `https://disco.leap-labs.com`

All endpoints use the `/api/` prefix. Authenticated endpoints require `Authorization: Bearer disco_...` header. Request and response bodies are JSON.

---

## Authentication

### POST /api/signup

Create a new account. Sends a 6-digit verification code to the email.

```
POST /api/signup
Content-Type: application/json

{"email": "you@example.com", "name": "Optional Name"}
```

**Responses:**
- `200` — Code sent: `{"status": "verification_required", "email": "you@example.com"}`
- `201` — Direct provisioning (trusted domain): `{"key": "disco_...", "tier": "free_tier", "credits": 10}`
- `409` — Email already registered
- `422` — Invalid email format

### POST /api/signup/verify

Complete signup by submitting the verification code.

```
POST /api/signup/verify
Content-Type: application/json

{"email": "you@example.com", "code": "123456"}
```

**Responses:**
- `201` — `{"key": "disco_...", "key_id": "...", "organization_id": "...", "tier": "free_tier", "credits": 10}`
- `400` — Invalid or expired code

### POST /api/login

Request a new API key for an existing account. Sends a verification code.

```
POST /api/login
Content-Type: application/json

{"email": "you@example.com"}
```

**Responses:**
- `200` — Code sent: `{"status": "verification_required"}`
- `200` — Trusted domain bypass: `{"key": "disco_...", ...}`
- `404` — No account with this email

### POST /api/login/verify

Complete login by submitting the verification code.

```
POST /api/login/verify
Content-Type: application/json

{"email": "you@example.com", "code": "123456"}
```

**Responses:**
- `200` — `{"key": "disco_...", "tier": "..."}`
- `400` — Invalid or expired code

---

## Public Endpoints (No Auth)

### GET /api/health

```
GET /api/health
```

**Response:** `200` — `{"status": "ok"}`

### POST /api/health

```
POST /api/health
Content-Type: application/json

{"ping": true}
```

**Response:** `200` — `{"status": "ok", "checks": {"database": "ok"}}`

### GET /api/plans

```
GET /api/plans
```

**Response:** `200` — `{"plans": [...], "credit_price_usd": 0.10, "credit_pack_size": 100, "credit_pack_price_usd": 10.0}`

### GET /api/stats/novel-patterns

```
GET /api/stats/novel-patterns
```

**Response:** `200` — `{"totalNovelPatterns": 1234, ...}`

### GET /api/public-reports

```
GET /api/public-reports?pageSize=10
```

**Response:** `200` — `{"reports": [...], "totalCount": 456}`

---

## Account

All account endpoints require `Authorization: Bearer disco_...`.

### GET /api/account

```
GET /api/account
Authorization: Bearer disco_...
```

**Response:** `200`
```json
{
  "plan": "free_tier",
  "tier": "free_tier",
  "credits": {"total": 10, "used": 3},
  "payment_method": {"on_file": false},
  "stripe_publishable_key": "pk_live_...",
  "stripe_customer_id": "cus_..."
}
```

**Errors:** `401` — Invalid API key

### POST /api/estimate

Estimate cost and time before running an analysis.

```
POST /api/estimate
Authorization: Bearer disco_...
Content-Type: application/json

{
  "file_size_mb": 10.5,
  "num_columns": 25,
  "num_rows": 5000,
  "analysis_depth": 2,
  "visibility": "private",
  "use_llms": false
}
```

**Response:** `200`
```json
{
  "cost": {"credits": 55, "price_usd": 5.5},
  "time_estimate": {"estimated_seconds": 360},
  "limits": {"max_analysis_depth": 23},
  "account": {"sufficient": true}
}
```

---

## Billing

All billing endpoints require `Authorization: Bearer disco_...`.

### POST /api/account/payment-method

Attach a Stripe PaymentMethod. Card data goes to Stripe directly — Disco never sees it.

To get a `pm_...` token, call Stripe's API with the `stripe_publishable_key` from `GET /api/account`:

```bash
curl -X POST https://api.stripe.com/v1/payment_methods \
  -u "pk_live_...:"\
  -d "type=card" \
  -d "card[number]=4242424242424242" \
  -d "card[exp_month]=12" \
  -d "card[exp_year]=2028" \
  -d "card[cvc]=123"
# -> {"id": "pm_..."}
```

Then attach it:

```
POST /api/account/payment-method
Authorization: Bearer disco_...
Content-Type: application/json

{"payment_method_id": "pm_..."}
```

**Response:** `200` — `{"payment_method_attached": true, "card_brand": "visa", "card_last4": "4242"}`

**Errors:** `400` — Invalid PaymentMethod ID (Stripe validation)

### POST /api/account/subscribe

Subscribe to or change plan.

```
POST /api/account/subscribe
Authorization: Bearer disco_...
Content-Type: application/json

{"plan": "tier_1"}
```

Plans: `free_tier` ($0, 10 cr/mo), `tier_1` ($49, 50 cr/mo), `tier_2` ($199, 200 cr/mo).

**Response:** `200` — `{"plan": "tier_1", "name": "Researcher", "monthly_credits": 50, "price_usd": 49}`

**Errors:**
- `402` — No payment method on file (required for paid plans)
- `422` — Invalid plan name

### POST /api/account/credits/purchase

Buy credit packs. Each pack is 100 credits for $10.

```
POST /api/account/credits/purchase
Authorization: Bearer disco_...
Content-Type: application/json

{"packs": 1}
```

**Response:** `200` — `{"purchased_credits": 100, "total_credits": 110, "charge_amount_usd": 10.0}`

**Errors:**
- `402` — No payment method on file
- `422` — Invalid packs value (must be > 0)

---

## Upload

All upload endpoints require `Authorization: Bearer disco_...`.

### Presigned Upload (3 steps — any file size)

**Step 1: Get presigned URL**

```
POST /api/data/upload/presign
Authorization: Bearer disco_...
Content-Type: application/json

{"fileName": "data.csv", "contentType": "text/csv", "fileSize": 1048576}
```

**Response:** `200` — `{"uploadUrl": "https://storage.googleapis.com/...", "key": "uploads/abc/data.csv", "uploadToken": "tok_..."}`

**Step 2: Upload file to presigned URL**

```
PUT <uploadUrl>
Content-Type: text/csv

<binary file content>
```

No auth header needed — the URL is pre-signed.

**Response:** `200` or `204`

**Step 3: Finalize**

```
POST /api/data/upload/finalize
Authorization: Bearer disco_...
Content-Type: application/json

{"key": "uploads/abc/data.csv", "uploadToken": "tok_..."}
```

**Response:** `200`
```json
{
  "ok": true,
  "file": {"key": "uploads/abc/data.csv", "name": "data.csv", "size": 1048576, "fileHash": "sha256:..."},
  "columns": [{"name": "col1", "type": "continuous", ...}, ...],
  "rowCount": 5000
}
```

### Direct Upload (1 step — small files)

```
POST /api/data/upload/direct
Authorization: Bearer disco_...
Content-Type: application/json

{"fileName": "data.csv", "content": "<base64-encoded file content>"}
```

**Response:** `200`
```json
{
  "ok": true,
  "file": {"key": "...", "name": "data.csv", "size": 1048576, "fileHash": "..."},
  "columns": [...],
  "rowCount": 5000
}
```

Simpler than presigned upload but the entire file must fit in the request body. For large files, use the presigned flow.

---

## Analysis

### POST /api/reports/create-from-upload

Submit a dataset for analysis. Use the `file` and `columns` from the upload response.

```
POST /api/reports/create-from-upload
Authorization: Bearer disco_...
Content-Type: application/json

{
  "file": {
    "key": "uploads/abc/data.csv",
    "name": "data.csv",
    "size": 1048576,
    "fileHash": "sha256:..."
  },
  "columns": [...],
  "targetColumn": "outcome",
  "analysisDepth": 2,
  "isPublic": true,
  "useLlms": true,
  "title": "My analysis",
  "description": "Optional description",
  "columnDescriptions": {
    "age": "Patient age in years",
    "bmi": "Body mass index"
  },
  "excludedColumns": ["patient_id", "timestamp"]
}
```

**Parameters:**
- `targetColumn` (required) — Column to predict/analyze
- `analysisDepth` — 2 = default, higher = deeper. Max: num_columns - 2
- `isPublic` — `true` = free (results published, depth locked to 2), `false` = costs credits
- `useLlms` — LLM explanations, novelty, citations. Public runs always use LLMs. Default: false
- `columnDescriptions` — Improves pattern explanations. Always provide for non-obvious column names
- `excludedColumns` — Remove identifiers, leakage, and tautological columns

**Response:** `200` — `{"run_id": "abc123", "report_id": "def456"}`

### GET /api/runs/{run_id}/results

Fetch results for a run. Poll this endpoint until `status` is `completed` or `failed`.

```
GET /api/runs/abc123/results
Authorization: Bearer disco_...
```

**While processing:**
```json
{
  "status": "processing",
  "current_step": "training",
  "current_step_message": "Modelling data...",
  "estimated_seconds": 360,
  "queue_position": null
}
```

**When pending (queued):**
```json
{
  "status": "pending",
  "queue_position": 2,
  "estimated_wait_seconds": 120
}
```

**When completed:**
```json
{
  "status": "completed",
  "patterns": [
    {
      "id": "p-1",
      "description": "When humidity is between 72-89% AND wind speed is below 12 km/h...",
      "conditions": [
        {"type": "continuous", "feature": "humidity_pct", "min_value": 72.0, "max_value": 89.0},
        {"type": "continuous", "feature": "wind_speed_kmh", "min_value": 0.0, "max_value": 12.0}
      ],
      "p_value": 0.003,
      "novelty_type": "novel",
      "novelty_explanation": "...",
      "citations": [{"title": "...", "authors": [...], "year": "2021", "journal": "..."}],
      "target_change_direction": "max",
      "abs_target_change": 0.34,
      "support_count": 847,
      "support_percentage": 16.9
    }
  ],
  "summary": {
    "overview": "...",
    "key_insights": ["...", "..."],
    "novel_patterns": {"pattern_ids": ["p-1", "p-2"], "explanation": "..."}
  },
  "feature_importance": {
    "kind": "global",
    "baseline": 6.5,
    "scores": [{"feature": "humidity_pct", "score": 1.82}, ...]
  },
  "columns": [...],
  "correlation_matrix": [...],
  "report_url": "https://disco.leap-labs.com/reports/def456",
  "hints": [],
  "hidden_deep_count": 0,
  "hidden_deep_novel_count": 0
}
```

**Errors:** `404` — Run not found

**When failed:**
```json
{
  "status": "failed",
  "error_message": "..."
}
```

---

## Supported File Formats

CSV, TSV, Excel (.xlsx), JSON, Parquet, ARFF, Feather. Max 5 GB.

## Content Types for Upload

| Format | Content-Type |
|--------|-------------|
| CSV | `text/csv` |
| TSV | `text/tab-separated-values` |
| Excel | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| JSON | `application/json` |
| Parquet | `application/octet-stream` |
| ARFF | `text/plain` |
| Feather | `application/octet-stream` |

---

## Links

- [Python SDK reference](python-sdk.md)
- [Agent / MCP skill file](../SKILL.md)
- [OpenAPI spec](https://disco.leap-labs.com/.well-known/openapi.json)
- [OpenAPI spec (in-repo)](openapi.json)
