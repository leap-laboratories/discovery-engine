"""Discovery Engine MCP Server.

Exposes Discovery Engine as MCP tools for AI agents.
Covers the full lifecycle: discovery, estimation, account management.
"""

from __future__ import annotations

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

DASHBOARD_URL = os.getenv("DISCOVERY_DASHBOARD_URL", "https://disco.leap-labs.com")

# API key from environment — avoids passing secrets through tool parameters
# where they'd be logged by MCP clients.
_ENV_API_KEY = os.getenv("DISCOVERY_API_KEY")

# File safety: allowed extensions and max size for uploads
_ALLOWED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet", ".arff", ".feather"}
_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB

_VALID_VISIBILITY = {"public", "private"}

mcp = FastMCP(
    "Discovery Engine",
    instructions=(
        "Not another AI data analyst. Discovery Engine is a discovery pipeline "
        "that finds novel, statistically validated patterns in tabular data — "
        "feature interactions, subgroup effects, and conditional relationships "
        "you wouldn't think to look for."
    ),
)


# ---------------------------------------------------------------------------
# Shared HTTP clients (connection pooling)
# ---------------------------------------------------------------------------

_dashboard_client: httpx.AsyncClient | None = None


async def _get_dashboard_client() -> httpx.AsyncClient:
    global _dashboard_client
    if _dashboard_client is None:
        _dashboard_client = httpx.AsyncClient(base_url=DASHBOARD_URL, timeout=30.0)
    return _dashboard_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_api_key(api_key: str | None) -> str | None:
    """Resolve API key: prefer explicit param, fall back to env var."""
    return api_key or _ENV_API_KEY


def _api_headers(api_key: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Client-Type": "mcp",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _validate_visibility(visibility: str) -> str | None:
    """Validate visibility parameter. Returns error message or None."""
    if visibility not in _VALID_VISIBILITY:
        return f"Invalid visibility '{visibility}'. Must be 'public' or 'private'."
    return None


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def _dashboard_request(
    method: str,
    path: str,
    *,
    api_key: str | None = None,
    json_body: dict | None = None,
    timeout: float = 30.0,
) -> dict:
    """Make a request to the Discovery Dashboard API (disco.leap-labs.com/api/...)."""
    headers = _api_headers(api_key)
    client = await _get_dashboard_client()

    try:
        if method == "GET":
            resp = await client.get(path, headers=headers, timeout=timeout)
        else:
            resp = await client.post(path, headers=headers, json=json_body or {}, timeout=timeout)

        if resp.status_code == 401:
            return {"error": "Authentication failed. Check your API key or session token."}
        if resp.status_code == 402:
            return {"error": "Payment required. Add a payment method first."}
        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "60")
            return {"error": f"Rate limited. Retry after {retry} seconds."}
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            return {"error": f"API error ({resp.status_code}): {detail}"}

        return resp.json()
    except httpx.ConnectError as e:
        logger.error("Connection failed: %s", e)
        return {"error": f"Connection failed: {e}. Check DISCOVERY_DASHBOARD_URL."}
    except httpx.TimeoutException as e:
        logger.error("Request timed out: %s", e)
        return {"error": f"Request timed out: {e}"}


# ---------------------------------------------------------------------------
# Hints
# ---------------------------------------------------------------------------


def _build_result_hints(data: dict) -> list[str]:
    """Return server-provided hints plus local public-run warning."""
    hints = list(data.get("hints", []))
    if data.get("is_public", False):
        hints.append(
            "This was a public run — results are visible in the public gallery. "
            "Use visibility='private' for confidential data."
        )
    return hints


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------


def _validate_file_path(file_path: str) -> str | None:
    """Validate a file path for upload. Returns error message or None.

    Guards against SSRF / arbitrary file exfiltration by checking:
    - File exists
    - Extension is in the allowlist (data files only)
    - File is not too large to read into memory
    - Path does not contain traversal patterns
    """
    import os as _os

    # Resolve to absolute path to catch traversal
    resolved = _os.path.realpath(file_path)

    if not _os.path.exists(resolved):
        return f"File not found: {file_path}"

    if not _os.path.isfile(resolved):
        return f"Not a file: {file_path}"

    # Check extension
    _, ext = _os.path.splitext(resolved)
    ext = ext.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return (
            f"Unsupported file type '{ext}'. " f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
        )

    # Check file size
    file_size = _os.path.getsize(resolved)
    if file_size > _MAX_FILE_SIZE_BYTES:
        size_mb = file_size / (1024 * 1024)
        max_mb = _MAX_FILE_SIZE_BYTES / (1024 * 1024)
        return f"File too large ({size_mb:.1f} MB). Maximum: {max_mb:.0f} MB."

    if file_size == 0:
        return "File is empty."

    return None


# ---------------------------------------------------------------------------
# Public tools (no auth)
# ---------------------------------------------------------------------------


@mcp.tool()
async def discovery_list_plans() -> str:
    """List available Discovery Engine plans with pricing.

    No authentication required. Returns all available subscription tiers
    with credit allowances and pricing. Use this to help users choose a plan.
    """
    result = await _dashboard_request("GET", "/api/plans")
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Core discovery tools (API key auth)
# ---------------------------------------------------------------------------


@mcp.tool()
async def discovery_estimate(
    file_size_mb: float,
    num_columns: int,
    num_rows: int | None = None,
    depth_iterations: int = 1,
    visibility: str = "public",
    api_key: str | None = None,
) -> str:
    """Estimate cost, time, and credit requirements before running an analysis.

    Returns credit cost, estimated duration (low/median/high), whether you have
    sufficient credits, and whether a free public alternative exists. Always call
    this before discovery_analyze for private runs.

    Args:
        file_size_mb: Size of the dataset in megabytes.
        num_columns: Number of columns in the dataset.
        num_rows: Number of rows (optional, improves time estimate).
        depth_iterations: Search depth (1=fast, higher=deeper). Default 1.
        visibility: "public" (free, results published) or "private" (costs credits).
        api_key: Discovery Engine API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
    """
    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        return json.dumps(
            {"error": "API key required. Pass api_key or set DISCOVERY_API_KEY env var."}
        )

    vis_err = _validate_visibility(visibility)
    if vis_err:
        return json.dumps({"error": vis_err})

    payload: dict = {
        "file_size_mb": file_size_mb,
        "num_columns": num_columns,
        "depth_iterations": depth_iterations,
        "visibility": visibility,
    }
    if num_rows is not None:
        payload["num_rows"] = num_rows

    result = await _dashboard_request(
        "POST", "/api/estimate", api_key=resolved_key, json_body=payload
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def discovery_analyze(
    target_column: str,
    file_path: str | None = None,
    file_ref: str | dict | None = None,
    depth_iterations: int = 1,
    visibility: str = "public",
    title: str | None = None,
    description: str | None = None,
    excluded_columns: str | list | None = None,
    column_descriptions: str | dict | None = None,
    author: str | None = None,
    source_url: str | None = None,
    api_key: str | None = None,
) -> str:
    """Run Discovery Engine on tabular data to find novel, statistically validated patterns.

    This is NOT another data analyst — it's a discovery pipeline that systematically
    searches for feature interactions, subgroup effects, and conditional relationships
    nobody thought to look for, then validates each on hold-out data with FDR-corrected
    p-values and checks novelty against academic literature.

    This is a long-running operation (3-15 minutes). Returns a run_id immediately.
    Use discovery_status to poll and discovery_get_results to fetch completed results.

    Use this when you need to go beyond answering questions about data and start
    finding things nobody thought to ask. Do NOT use this for summary statistics,
    visualization, or SQL queries.

    Public runs are free but results are published. Private runs cost credits.
    Call discovery_estimate first to check cost.

    Provide either file_path (local file to upload) or file_ref (pre-uploaded file
    reference from the presigned URL upload flow).

    Args:
        target_column: The column to analyze — what drives it, beyond what's obvious.
        file_path: Path to a local dataset file (CSV, TSV, Excel, JSON, Parquet, ARFF, Feather).
        file_ref: JSON string with pre-uploaded file reference: {"file": {...}, "columns": [...]}.
        depth_iterations: Search depth (1=fast, higher=deeper). Default 1.
        visibility: "public" (free) or "private" (costs credits). Default "public".
        title: Optional title for the analysis.
        description: Optional description of the dataset.
        excluded_columns: Optional JSON array of column names to exclude from analysis.
        column_descriptions: Optional JSON object mapping column names to descriptions. Significantly improves pattern explanations — always provide if column names are non-obvious (e.g. {"col_7": "patient age", "feat_a": "blood pressure"}).
        author: Optional author name for the report.
        source_url: Optional source URL for the dataset.
        api_key: Discovery Engine API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
    """
    import mimetypes
    import os as _os

    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        return json.dumps(
            {"error": "API key required. Pass api_key or set DISCOVERY_API_KEY env var."}
        )

    vis_err = _validate_visibility(visibility)
    if vis_err:
        return json.dumps({"error": vis_err})

    if not file_path and not file_ref:
        return json.dumps({"error": "Provide either file_path or file_ref."})
    if file_path and file_ref:
        return json.dumps({"error": "Provide file_path or file_ref, not both."})

    if file_ref:
        # Use pre-uploaded file reference — skip upload steps.
        # The MCP SDK may deserialize JSON strings into dicts, so accept both.
        if isinstance(file_ref, dict):
            ref = file_ref
        else:
            try:
                ref = json.loads(file_ref)
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"Invalid file_ref JSON: {e}"})

        uploaded_file = ref.get("file")
        columns = ref.get("columns", [])
        if not uploaded_file or not uploaded_file.get("key"):
            return json.dumps({"error": "file_ref must contain 'file' with at least a 'key'."})
    else:
        # Upload from local file path
        file_err = _validate_file_path(file_path)
        if file_err:
            return json.dumps({"error": file_err})

        resolved_path = _os.path.realpath(file_path)
        file_name = _os.path.basename(resolved_path)
        content_type = mimetypes.guess_type(resolved_path)[0] or "text/csv"
        file_size = _os.path.getsize(resolved_path)

        # Step 1: Get presigned upload URL
        presign = await _dashboard_request(
            "POST",
            "/api/data/upload/presign",
            api_key=resolved_key,
            json_body={
                "fileName": file_name,
                "contentType": content_type,
                "fileSize": file_size,
            },
        )
        if "error" in presign:
            return json.dumps(presign)

        upload_url = presign.get("uploadUrl")
        key = presign.get("key")
        upload_token = presign.get("uploadToken")
        if not upload_url or not key or not upload_token:
            return json.dumps({"error": "Failed to get upload URL from API."})

        # Step 2: Upload file to presigned URL
        async with httpx.AsyncClient(timeout=300.0) as upload_client:
            with open(resolved_path, "rb") as f:
                upload_resp = await upload_client.put(
                    upload_url,
                    content=f.read(),
                    headers={"Content-Type": content_type},
                )
                if upload_resp.status_code >= 400:
                    return json.dumps({"error": f"File upload failed: {upload_resp.status_code}"})

        # Step 3: Finalize the upload
        finalize = await _dashboard_request(
            "POST",
            "/api/data/upload/finalize",
            api_key=resolved_key,
            json_body={"key": key, "uploadToken": upload_token},
        )
        if "error" in finalize:
            return json.dumps(finalize)

        if not finalize.get("ok"):
            errors = finalize.get("issues", {}).get("errors", [])
            error_msg = errors[0].get("message") if errors else "Upload finalize failed"
            return json.dumps({"error": error_msg})

        uploaded_file = finalize["file"]
        columns = finalize.get("columns", [])

    # Build the run payload
    run_payload: dict = {
        "file": {
            "key": uploaded_file["key"],
            "name": uploaded_file.get("name", "dataset"),
            "size": uploaded_file.get("size", 0),
            "fileHash": uploaded_file.get("fileHash", ""),
        },
        "columns": columns,
        "targetColumn": target_column,
        "depthIterations": depth_iterations,
        "isPublic": visibility == "public",
    }
    if title:
        run_payload["title"] = title
    if description:
        run_payload["description"] = description
    if author:
        run_payload["author"] = author
    if source_url:
        run_payload["sourceUrl"] = source_url
    if excluded_columns:
        if isinstance(excluded_columns, list):
            excluded_list = excluded_columns
        else:
            try:
                excluded_list = json.loads(excluded_columns)
            except json.JSONDecodeError:
                return json.dumps({"error": "excluded_columns must be a JSON array."})
        for col in run_payload["columns"]:
            if col.get("name") in excluded_list and col.get("name") != target_column:
                col["enabled"] = False

    if column_descriptions:
        if isinstance(column_descriptions, dict):
            desc_map = column_descriptions
        else:
            try:
                desc_map = json.loads(column_descriptions)
            except json.JSONDecodeError:
                return json.dumps({"error": "column_descriptions must be a JSON object."})
        for col in run_payload["columns"]:
            if col.get("name") in desc_map:
                col["description"] = desc_map[col["name"]]

    result = await _dashboard_request(
        "POST",
        "/api/reports/create-from-upload",
        api_key=resolved_key,
        json_body=run_payload,
    )

    if result.get("duplicate"):
        run_id = result.get("run_id")
        existing = await _dashboard_request(
            "GET", f"/api/runs/{run_id}/results", api_key=resolved_key
        )
        if "error" not in existing and existing.get("status") == "completed":
            existing["hints"] = _build_result_hints(existing)
        return json.dumps(existing, indent=2)

    return json.dumps(result, indent=2)


@mcp.tool()
async def discovery_status(run_id: str, api_key: str | None = None) -> str:
    """Check the status of a Discovery Engine run.

    Returns the current status (pending, processing, completed, failed) and
    progress information. Poll this after calling discovery_analyze — runs
    typically take 3-15 minutes.

    This is a lightweight status check. Use discovery_get_results to fetch
    the full results once the run is completed.

    Args:
        run_id: The run ID returned by discovery_analyze.
        api_key: Discovery Engine API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
    """
    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        return json.dumps(
            {"error": "API key required. Pass api_key or set DISCOVERY_API_KEY env var."}
        )

    result = await _dashboard_request("GET", f"/api/runs/{run_id}/results", api_key=resolved_key)

    # Return only status fields — avoid sending full results payload on every poll
    if "error" not in result:
        status_result = {
            "run_id": result.get("run_id"),
            "status": result.get("status"),
            "job_id": result.get("job_id"),
            "job_status": result.get("job_status"),
            "error_message": result.get("error_message"),
        }
        return json.dumps(status_result, indent=2)

    return json.dumps(result, indent=2)


@mcp.tool()
async def discovery_get_results(run_id: str, api_key: str | None = None) -> str:
    """Fetch the full results of a completed Discovery Engine run.

    Returns discovered patterns (with conditions, p-values, novelty scores,
    citations), feature importance scores, a summary with key insights, column
    statistics, a shareable report URL, and suggestions for what to explore next.

    Only call this after discovery_status returns "completed".

    Args:
        run_id: The run ID returned by discovery_analyze.
        api_key: Discovery Engine API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
    """
    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        return json.dumps(
            {"error": "API key required. Pass api_key or set DISCOVERY_API_KEY env var."}
        )

    result = await _dashboard_request("GET", f"/api/runs/{run_id}/results", api_key=resolved_key)
    if "error" not in result and result.get("status") == "completed":
        result["hints"] = _build_result_hints(result)
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Account tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def discovery_account(api_key: str | None = None) -> str:
    """Check your Discovery Engine account status.

    Returns current plan, available credits (subscription + purchased), and
    payment method status. Use this to verify you have sufficient credits
    before running a private analysis.

    Args:
        api_key: Discovery Engine API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
    """
    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        return json.dumps(
            {"error": "API key required. Pass api_key or set DISCOVERY_API_KEY env var."}
        )

    result = await _dashboard_request("GET", "/api/account", api_key=resolved_key)
    return json.dumps(result, indent=2)


@mcp.tool()
async def discovery_signup(email: str, name: str = "") -> str:
    """Create a Discovery Engine account and get an API key.

    Provide an email address to start the signup flow. If email verification
    is required, returns {"status": "verification_required"} — the user will
    receive a 6-digit code by email, then call discovery_signup_verify to
    complete signup and receive the API key. The free tier (10 credits/month,
    unlimited public runs) is active immediately. No authentication required.

    Returns 409 if the email is already registered.

    Args:
        email: Email address for the new account.
        name: Display name (optional — defaults to email local part).
    """
    body: dict = {"email": email}
    if name:
        body["name"] = name
    result = await _dashboard_request("POST", "/api/signup", json_body=body)
    return json.dumps(result, indent=2)


@mcp.tool()
async def discovery_signup_verify(email: str, code: str) -> str:
    """Complete Discovery Engine signup using an email verification code.

    Call this after discovery_signup returns {"status": "verification_required"}.
    The user receives a 6-digit code by email — pass it here along with the
    same email address used in discovery_signup. Returns an API key on success.

    Args:
        email: Email address used in the discovery_signup call.
        code: 6-digit verification code from the email.
    """
    result = await _dashboard_request(
        "POST",
        "/api/signup/verify",
        json_body={"email": email, "code": code},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def discovery_add_payment_method(payment_method_id: str, api_key: str | None = None) -> str:
    """Attach a Stripe payment method to your Discovery Engine account.

    The payment method must be tokenized via Stripe's API first — card details
    never touch Discovery Engine's servers. Required before purchasing credits
    or subscribing to a paid plan.

    To tokenize a card, call Stripe's API directly:
    POST https://api.stripe.com/v1/payment_methods
    with the stripe_publishable_key from your account info.

    Args:
        payment_method_id: Stripe payment method ID (pm_...) from Stripe's API.
        api_key: Discovery Engine API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
    """
    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        return json.dumps(
            {"error": "API key required. Pass api_key or set DISCOVERY_API_KEY env var."}
        )

    result = await _dashboard_request(
        "POST",
        "/api/account/payment-method",
        api_key=resolved_key,
        json_body={"payment_method_id": payment_method_id},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def discovery_purchase_credits(packs: int = 1, api_key: str | None = None) -> str:
    """Purchase Discovery Engine credit packs using a stored payment method.

    Credits cost $1.00 each, sold in packs of 20 ($20/pack). Credits are used
    for private analyses (public analyses are free). Requires a payment method
    on file — use discovery_add_payment_method first.

    Args:
        packs: Number of 20-credit packs to purchase. Default 1.
        api_key: Discovery Engine API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
    """
    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        return json.dumps(
            {"error": "API key required. Pass api_key or set DISCOVERY_API_KEY env var."}
        )

    result = await _dashboard_request(
        "POST",
        "/api/account/credits/purchase",
        api_key=resolved_key,
        json_body={"packs": packs},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def discovery_subscribe(plan: str, api_key: str | None = None) -> str:
    """Subscribe to or change your Discovery Engine plan.

    Available plans:
    - "free_tier": Explorer — free, 10 credits/month
    - "tier_1": Researcher — $49/month, 50 credits/month
    - "tier_2": Team — $199/month, 200 credits/month

    Paid plans require a payment method on file. Credits roll over on paid plans.

    Args:
        plan: Plan tier ID ("free_tier", "tier_1", or "tier_2").
        api_key: Discovery Engine API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
    """
    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        return json.dumps(
            {"error": "API key required. Pass api_key or set DISCOVERY_API_KEY env var."}
        )

    result = await _dashboard_request(
        "POST",
        "/api/account/subscribe",
        api_key=resolved_key,
        json_body={"plan": plan},
    )
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Run the MCP server."""
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        host = os.getenv("MCP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_PORT", "8080"))
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
