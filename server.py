"""Disco MCP Server.

Exposes Disco as MCP tools for AI agents.
Covers the full lifecycle: discovery, estimation, account management.

NOTE: A public copy of this file lives at github.com/leap-laboratories/discovery-engine.
It is synced automatically on every staging → main merge via .github/workflows/sync-public-repo.yml.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http import TransportSecuritySettings
from mcp.types import ToolAnnotations

logger = logging.getLogger(__name__)

DASHBOARD_URL = os.getenv("DISCOVERY_DASHBOARD_URL") or os.getenv(
    "DASHBOARD_BASE_URL", "https://disco.leap-labs.com"
)

# API key from environment — avoids passing secrets through tool parameters
# where they'd be logged by MCP clients.
_ENV_API_KEY = os.getenv("DISCOVERY_API_KEY")

# OAuth signing secret — enables OAuth 2.0 auth when set.
# Shared between MCP server and Dashboard for stateless token signing.
_OAUTH_SECRET = os.getenv("MCP_OAUTH_SECRET")

# MCP server's public URL (for OAuth callback routing)
_SERVER_URL = os.getenv("MCP_SERVER_URL", "")

_VALID_VISIBILITY = {"public", "private"}

# 8 MB chunks — bounded memory for multi-GB uploads (avoids the _ssl.c:2426
# crash from passing the full file body to httpx as a single bytes object).
_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024


async def _stream_file_chunks(path: Path, chunk_size: int = _UPLOAD_CHUNK_SIZE):
    """Yield file contents in fixed-size chunks for streaming uploads.

    Reads via run_in_executor so the event loop isn't blocked on read syscalls.
    Memory stays bounded to one chunk regardless of file size.
    """
    loop = asyncio.get_event_loop()
    with path.open("rb") as f:
        while True:
            chunk = await loop.run_in_executor(None, f.read, chunk_size)
            if not chunk:
                break
            yield chunk


# ---------------------------------------------------------------------------
# OAuth setup (only when MCP_OAUTH_SECRET is configured)
# ---------------------------------------------------------------------------

_oauth_provider = None
_oauth_auth_settings = None

if _OAUTH_SECRET and _SERVER_URL:
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions

    from .auth import DiscoOAuthProvider, create_callback_routes

    _oauth_provider = DiscoOAuthProvider(
        signing_secret=_OAUTH_SECRET,
        dashboard_url=DASHBOARD_URL,
        server_url=_SERVER_URL,
    )

    _oauth_auth_settings = AuthSettings(
        issuer_url=_SERVER_URL,
        service_documentation_url="https://docs.disco.leap-labs.com",
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["discovery"],
            default_scopes=["discovery"],
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[],
        resource_server_url=_SERVER_URL,
    )

# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Disco",
    instructions=(
        "Not another AI data analyst. Disco is a discovery pipeline "
        "that finds novel, statistically validated patterns in tabular data — "
        "feature interactions, subgroup effects, and conditional relationships "
        "you wouldn't think to look for. "
        "When displaying results, render interactive visualizations following "
        "the Disco style guide at https://disco.leap-labs.com/visualization-spec"
    ),
    stateless_http=True,
    # Pass OAuth provider for /authorize, /token, /register, /revoke endpoints.
    # We do NOT set token_verifier — our DualAuthMiddleware handles bearer
    # validation permissively (allows unauthenticated API key requests through).
    auth_server_provider=_oauth_provider,
    auth=_oauth_auth_settings,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "localhost:*",
            "127.0.0.1:*",
            "[::1]:*",
            # Public-facing URL (proxied via Vercel)
            "disco.leap-labs.com",
        ],
    ),
)

# Add OAuth callback route if OAuth is enabled
if _oauth_provider:
    mcp._custom_starlette_routes.extend(create_callback_routes())


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
    """Resolve API key: OAuth bearer token first, then explicit param, then env var.

    When a Claude.ai user connects via OAuth, their API key is embedded in
    the bearer token. This function checks for it automatically so tool
    functions don't need OAuth-specific logic.
    """
    # Check OAuth context (set by DualAuthMiddleware when bearer token is present)
    if _OAUTH_SECRET:
        from mcp.server.auth.middleware.auth_context import get_access_token

        token = get_access_token()
        if token and hasattr(token, "api_key") and token.api_key:
            return token.api_key
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
    """Make a request to Disco Dashboard API (disco.leap-labs.com/api/...)."""
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
# Public tools (no auth)
# ---------------------------------------------------------------------------


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def discovery_list_plans() -> str:
    """List available Disco plans with pricing.

    No authentication required. Returns all available subscription tiers
    with credit allowances and pricing. Use this to help users choose a plan.
    """
    result = await _dashboard_request("GET", "/api/plans")
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Core discovery tools (API key auth)
# ---------------------------------------------------------------------------


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def discovery_estimate(
    file_size_mb: float,
    num_columns: int,
    analysis_depth: int = 2,
    visibility: str = "public",
    use_llms: bool = False,
    api_key: str | None = None,
) -> str:
    """Estimate the credit cost of an analysis before running it.

    Returns credit cost, whether you have sufficient credits, and whether a free
    public alternative exists. Always call this before discovery_analyze for
    private runs.

    Args:
        file_size_mb: Size of the dataset in megabytes.
        num_columns: Number of columns in the dataset.
        analysis_depth: Search depth (1=fast, higher=deeper). Default 1.
        visibility: "public" (free, results published) or "private" (costs credits).
        use_llms: Slower and more expensive, but you get smarter pre-processing, summary page, literature context and pattern novelty assessment. Only applies to private runs — public runs always use LLMs. Default false.
        api_key: Disco API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
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
        "analysis_depth": analysis_depth,
        "visibility": visibility,
        "use_llms": use_llms,
    }

    result = await _dashboard_request(
        "POST", "/api/estimate", api_key=resolved_key, json_body=payload
    )
    return json.dumps(result, indent=2)


_MIME_TYPES = {
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".parquet": "application/vnd.apache.parquet",
    ".arff": "text/plain",
    ".feather": "application/octet-stream",
}


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False))
async def discovery_upload(
    file_content: str | None = None,
    file_name: str = "data.csv",
    file_path: str | None = None,
    file_url: str | None = None,
    api_key: str | None = None,
) -> str:
    """Upload a dataset file and return a file reference for use with discovery_analyze.

    Call this before discovery_analyze. Pass the returned result directly to
    discovery_analyze as the file_ref argument.

    Provide exactly one of: file_url, file_path, or file_content.

    Args:
        file_url: A publicly accessible http/https URL. The server downloads it directly.
                  Best option for remote datasets.
        file_path: Absolute path to a local file. Only works when running the MCP server
                   locally (not the hosted version). Streams the file directly — no size limit.
        file_content: File contents, base64-encoded. For small files when a URL or path
                      isn't available. Limited by the model's context window.
        file_name: Filename with extension (e.g. "data.csv"), for format detection.
                   Only used with file_content. Default: "data.csv".
        api_key: Disco API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
    """
    import base64

    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        return json.dumps(
            {"error": "API key required. Pass api_key or set DISCOVERY_API_KEY env var."}
        )

    if file_url is not None:
        # URL-based upload — server downloads directly
        result = await _dashboard_request(
            "POST",
            "/api/data/upload/from-url",
            api_key=resolved_key,
            json_body={"url": file_url},
            timeout=300.0,
        )
        if "error" in result:
            return json.dumps(result)
        if not result.get("ok"):
            errors = result.get("issues", {}).get("errors", [])
            msg = errors[0].get("message") if errors else "Upload failed"
            return json.dumps({"error": msg})
        return json.dumps(
            {
                "file": result["file"],
                "columns": result.get("columns", []),
                "rowCount": result.get("rowCount"),
            }
        )

    if file_path is not None:
        # Local file path — presign, upload directly to storage, finalize
        path = Path(file_path)
        if not path.exists():
            return json.dumps({"error": f"File not found: {file_path}"})
        if not path.is_file():
            return json.dumps({"error": f"Not a file: {file_path}"})

        file_size = path.stat().st_size
        filename = path.name
        mime_type = _MIME_TYPES.get(path.suffix.lower(), "text/csv")

        presign = await _dashboard_request(
            "POST",
            "/api/data/upload/presign",
            api_key=resolved_key,
            json_body={"fileName": filename, "contentType": mime_type, "fileSize": file_size},
        )
        if "error" in presign:
            return json.dumps(presign)

        # Stream from disk rather than loading the whole file into memory.
        # GCS XML API rejects chunked transfer encoding on PUT, so we must
        # send an explicit Content-Length header alongside the streamed body.
        try:
            async with httpx.AsyncClient(timeout=1800.0) as upload_client:
                upload_resp = await upload_client.put(
                    presign["uploadUrl"],
                    content=_stream_file_chunks(path),
                    headers={
                        "Content-Type": mime_type,
                        "Content-Length": str(file_size),
                    },
                )
                if upload_resp.status_code >= 400:
                    return json.dumps(
                        {"error": f"Storage upload failed ({upload_resp.status_code})"}
                    )
        except Exception as e:
            return json.dumps({"error": f"Storage upload failed: {e}"})

        finalize = await _dashboard_request(
            "POST",
            "/api/data/upload/finalize",
            api_key=resolved_key,
            json_body={"key": presign["key"], "uploadToken": presign["uploadToken"]},
            timeout=300.0,
        )
        if "error" in finalize:
            return json.dumps(finalize)
        if not finalize.get("ok"):
            errors = finalize.get("issues", {}).get("errors", [])
            msg = errors[0].get("message") if errors else "Finalize failed"
            return json.dumps({"error": msg})

        return json.dumps(
            {
                "file": finalize["file"],
                "columns": finalize.get("columns", []),
                "rowCount": finalize.get("rowCount"),
            }
        )

    if file_content is not None:
        # Base64 file content — limited by context window size
        try:
            raw_bytes = base64.b64decode(file_content)
        except Exception as e:
            return json.dumps({"error": f"Invalid file_content (base64 decode failed): {e}"})

        mime_type = _MIME_TYPES.get(Path(file_name).suffix.lower(), "text/csv")

        presign = await _dashboard_request(
            "POST",
            "/api/data/upload/presign",
            api_key=resolved_key,
            json_body={"fileName": file_name, "contentType": mime_type, "fileSize": len(raw_bytes)},
        )
        if "error" in presign:
            return json.dumps(presign)

        try:
            async with httpx.AsyncClient(timeout=1800.0) as upload_client:
                upload_resp = await upload_client.put(
                    presign["uploadUrl"],
                    content=raw_bytes,
                    headers={"Content-Type": mime_type},
                )
                if upload_resp.status_code >= 400:
                    return json.dumps(
                        {"error": f"Storage upload failed ({upload_resp.status_code})"}
                    )
        except Exception as e:
            return json.dumps({"error": f"Storage upload failed: {e}"})

        finalize = await _dashboard_request(
            "POST",
            "/api/data/upload/finalize",
            api_key=resolved_key,
            json_body={"key": presign["key"], "uploadToken": presign["uploadToken"]},
            timeout=300.0,
        )
        if "error" in finalize:
            return json.dumps(finalize)
        if not finalize.get("ok"):
            errors = finalize.get("issues", {}).get("errors", [])
            msg = errors[0].get("message") if errors else "Finalize failed"
            return json.dumps({"error": msg})

        return json.dumps(
            {
                "file": finalize["file"],
                "columns": finalize.get("columns", []),
                "rowCount": finalize.get("rowCount"),
            }
        )

    return json.dumps(
        {
            "error": "Provide one of: file_url (remote URL), file_path (local path), or file_content (base64)."
        }
    )


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False))
async def discovery_analyze(
    target_column: str,
    file_ref: str | dict | None = None,
    analysis_depth: int = 2,
    visibility: str = "public",
    title: str | None = None,
    description: str | None = None,
    excluded_columns: str | list | None = None,
    column_descriptions: str | dict | None = None,
    author: str | None = None,
    source_url: str | None = None,
    use_llms: bool = False,
    api_key: str | None = None,
) -> str:
    """Run Disco on tabular data to find novel, statistically validated patterns.

    This is NOT another data analyst — it's a discovery pipeline that systematically
    searches for feature interactions, subgroup effects, and conditional relationships
    nobody thought to look for, then validates each on hold-out data with FDR-corrected
    p-values and checks novelty against academic literature.

    This is a long-running operation. Returns a run_id immediately.
    Use discovery_status to poll and discovery_get_results to fetch completed results.

    Use this when you need to go beyond answering questions about data and start
    finding things nobody thought to ask. Do NOT use this for summary statistics,
    visualization, or SQL queries.

    Public runs are free but results are published. Private runs cost credits.
    Call discovery_estimate first to check cost. Private report URLs require
    sign-in — tell the user to sign in at the dashboard with the same email
    address used to create the account (email code, no password needed).

    Call discovery_upload first to upload your file, then pass the returned file_ref here.

    Args:
        target_column: The column to analyze — what drives it, beyond what's obvious.
        file_ref: The file reference returned by discovery_upload.
        analysis_depth: Search depth (1=fast, higher=deeper). Default 1.
        visibility: "public" (free) or "private" (costs credits). Default "public".
        title: Optional title for the analysis.
        description: Optional description of the dataset.
        excluded_columns: Optional JSON array of column names to exclude from analysis.
        column_descriptions: Optional JSON object mapping column names to descriptions. Significantly improves pattern explanations — always provide if column names are non-obvious (e.g. {"col_7": "patient age", "feat_a": "blood pressure"}).
        author: Optional author name for the report.
        source_url: Optional source URL for the dataset.
        use_llms: Slower and more expensive, but you get smarter pre-processing, summary page, literature context and pattern novelty assessment. Only applies to private runs — public runs always use LLMs. Default false.
        api_key: Disco API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
    """
    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        return json.dumps(
            {"error": "API key required. Pass api_key or set DISCOVERY_API_KEY env var."}
        )

    vis_err = _validate_visibility(visibility)
    if vis_err:
        return json.dumps({"error": vis_err})

    if not file_ref:
        return json.dumps(
            {"error": "file_ref is required. Call discovery_upload first to upload your file."}
        )

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
        "analysisDepth": analysis_depth,
        "isPublic": visibility == "public",
        "useLlms": use_llms,
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
        "/api/run-analysis",
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


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def discovery_status(run_id: str, api_key: str | None = None) -> str:
    """Check the status of a Disco run.

    Returns current status and progress details:
    - status: "pending" | "processing" | "completed" | "failed"
    - job_status: underlying job queue status
    - queue_position: position in queue when pending (1 = next up)
    - current_step: active pipeline step (preprocessing, training, interpreting, reporting)
    - estimated_wait_seconds: estimated queue wait time in seconds (pending only)

    Poll this after calling discovery_analyze.
    Use discovery_get_results to fetch full results once status is "completed".

    Args:
        run_id: The run ID returned by discovery_analyze.
        api_key: Disco API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
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
            "queue_position": result.get("queue_position"),
            "current_step": result.get("current_step"),
            "estimated_wait_seconds": result.get("estimated_wait_seconds"),
            "error_message": result.get("error_message"),
        }
        return json.dumps(status_result, indent=2)

    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def discovery_get_results(run_id: str, api_key: str | None = None) -> str:
    """Fetch the full results of a completed Disco run.

    Returns discovered patterns (with conditions, p-values, novelty scores,
    citations), feature importance scores, a summary with key insights, column
    statistics, and suggestions for what to explore next.

    The response includes a `dashboard_urls` object with direct links to each
    page of the interactive report — use these to direct the user to the most
    relevant view:
    - **summary**: AI-generated overview with key insights, novel findings, and plain-language explanation of the most important findings
    - **patterns**: Full list of discovered patterns with conditions, effect sizes, p-values, novelty scores, citations, and interactive visualisations
    - **features**: Feature importances, feature statistics and distribution plots, and correlation matrix
    - **territory**: Interactive 3D map showing how patterns select different regions of the data

    Only call this after discovery_status returns "completed".

    Args:
        run_id: The run ID returned by discovery_analyze.
        api_key: Disco API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
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


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def discovery_account(api_key: str | None = None) -> str:
    """Check your Disco account status.

    Returns current plan, available credits (subscription + purchased), and
    payment method status. Use this to verify you have sufficient credits
    before running a private analysis.

    Args:
        api_key: Disco API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
    """
    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        return json.dumps(
            {"error": "API key required. Pass api_key or set DISCOVERY_API_KEY env var."}
        )

    result = await _dashboard_request("GET", "/api/account", api_key=resolved_key)
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
async def discovery_signup(email: str, name: str = "") -> str:
    """Create a Disco account and get an API key.

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


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
async def discovery_signup_verify(email: str, code: str) -> str:
    """Complete Disco signup using an email verification code.

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


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
async def discovery_login(email: str) -> str:
    """Get a new API key for an existing Disco account.

    Sends a 6-digit verification code to the email address. Call
    discovery_login_verify with the code to receive a new API key.
    Use this when you need an API key for an account that already exists
    (e.g. the key was lost or this is a new agent session).

    Returns 404 if no account exists with this email — use discovery_signup instead.

    Args:
        email: Email address of the existing account.
    """
    result = await _dashboard_request("POST", "/api/login", json_body={"email": email})
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
async def discovery_login_verify(email: str, code: str) -> str:
    """Complete login and receive a new API key.

    Call this after discovery_login returns {"status": "verification_required"}.
    The user receives a 6-digit code by email — pass it here along with the
    same email address. Returns a new API key on success.

    Args:
        email: Email address used in the discovery_login call.
        code: 6-digit verification code from the email.
    """
    result = await _dashboard_request(
        "POST",
        "/api/login/verify",
        json_body={"email": email, "code": code},
    )
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
async def discovery_add_payment_method(payment_method_id: str, api_key: str | None = None) -> str:
    """Attach a Stripe payment method to your Disco account.

    The payment method must be tokenized via Stripe's API first — card details
    never touch Disco's servers. Required before purchasing credits
    or subscribing to a paid plan.

    To tokenize a card, call Stripe's API directly:
    POST https://api.stripe.com/v1/payment_methods
    with the stripe_publishable_key from your account info.

    Args:
        payment_method_id: Stripe payment method ID (pm_...) from Stripe's API.
        api_key: Disco API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
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


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False))
async def discovery_purchase_credits(packs: int = 1, api_key: str | None = None) -> str:
    """Purchase Disco credit packs using a stored payment method.

    Credits cost $0.10 each, sold in packs of 100 ($10/pack). Credits are used
    for private analyses (public analyses are free). Requires a payment method
    on file — use discovery_add_payment_method first.

    Args:
        packs: Number of 100-credit packs to purchase. Default 1.
        api_key: Disco API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
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


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True))
async def discovery_subscribe(plan: str, api_key: str | None = None) -> str:
    """Subscribe to or change your Disco plan.

    Available plans:
    - "free_tier": Explorer — free, 10 credits/month
    - "tier_1": Researcher — $49/month, 50 credits/month
    - "tier_2": Team — $199/month, 200 credits/month

    Paid plans require a payment method on file. Credits roll over on paid plans.

    Args:
        plan: Plan tier ID ("free_tier", "tier_1", or "tier_2").
        api_key: Disco API key (disco_...). Optional if DISCOVERY_API_KEY env var is set.
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


def create_app():
    """Create the ASGI app with OAuth middleware if configured.

    Returns a Starlette app suitable for Modal's @modal.asgi_app().
    When MCP_OAUTH_SECRET is set, wraps the app with DualAuthMiddleware
    for bearer token validation. Otherwise returns the plain MCP app.
    """
    starlette_app = mcp.streamable_http_app()

    if _oauth_provider:
        from .auth import DualAuthMiddleware

        # Store provider on the Starlette app so the callback route can access it
        starlette_app.state.oauth_provider = _oauth_provider
        # Wrap with middleware that validates bearer tokens permissively
        return DualAuthMiddleware(starlette_app, _oauth_provider)

    return starlette_app


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
