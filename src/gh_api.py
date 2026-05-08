"""GitHub API plumbing — HTTP, rate-limit gate, ETag cache, GraphQL, URL parsers,
endpoint fetchers, PR-review aggregation.

Self-contained: no imports from main. Module-level globals (etag cache, rate-limit
cooldown, username cache) hold shared state across all pollers.
"""

from __future__ import annotations

import functools
import re
import threading
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote, quote

import requests


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------
def _gh_headers(token: str) -> dict[str, str]:
    """Build standard GitHub API request headers."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ---------------------------------------------------------------------------
# URL parsers + builders
# ---------------------------------------------------------------------------
def parse_workflow_url(url: str) -> tuple[str, str, str, Optional[str]]:
    """
    Parse a GitHub workflow URL into (owner, repo, workflow_file, branch).
    Supports URLs like:
      https://github.com/owner/repo/actions/workflows/file.yml
      https://github.com/owner/repo/actions/workflows/file.yml?query=branch%3Amain
    """
    parsed = urlparse(url)
    parts  = parsed.path.strip("/").split("/")
    # parts: [owner, repo, 'actions', 'workflows', 'file.yml']
    if len(parts) < 5 or parts[2] != "actions" or parts[3] != "workflows":
        raise ValueError(f"Cannot parse workflow URL: {url}")
    owner         = parts[0]
    repo          = parts[1]
    workflow_file = parts[4]

    branch = None
    qs = parse_qs(parsed.query)
    # ?query=branch%3Amain  or  ?branch=main
    if "branch" in qs:
        branch = qs["branch"][0]
    elif "query" in qs:
        raw_query = unquote(qs["query"][0])
        m = re.search(r"branch[:\s]+(\S+)", raw_query)
        if m:
            branch = m.group(1)

    return owner, repo, workflow_file, branch


def _build_workflow_url(owner: str, repo: str, wf_file: str, branch: Optional[str] = None) -> str:
    """Construct a GitHub workflow overview URL, optionally filtered by branch."""
    if not (owner and repo and wf_file):
        return ""
    base = f"https://github.com/{owner}/{repo}/actions/workflows/{wf_file}"
    if branch:
        base += f"?query=branch%3A{quote(branch, safe='')}"
    return base


def _build_branch_url(owner: str, repo: str, branch: Optional[str]) -> str:
    """Construct a GitHub branch tree URL."""
    if not (owner and repo and branch):
        return ""
    return f"https://github.com/{owner}/{repo}/tree/{quote(branch, safe='/')}"


def parse_actor_url(url: str) -> tuple[str, str, Optional[str]]:
    """Parse a GitHub Actions actor URL like:
      https://github.com/owner/repo/actions?query=actor%3Ausername
    Returns (owner, repo, actor_username_or_None).
    """
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 3 or parts[2] != "actions":
        raise ValueError(f"Cannot parse actor URL: {url}")
    owner = parts[0]
    repo = parts[1]

    actor = None
    qs = parse_qs(parsed.query)
    if "query" in qs:
        raw_query = unquote(qs["query"][0])
        m = re.search(r"actor[:\s]+(\S+)", raw_query)
        if m:
            actor = m.group(1)

    return owner, repo, actor


def _github_api_get(url: str, token: str, session: Optional[requests.Session] = None,
                    params: Optional[dict] = None, timeout: int = 15):
    """GET with ETag conditional-request cache + rate-limit cooldown gate.

    - Sends `If-None-Match` when a prior ETag is cached; on 304 returns the
      cached JSON (these don't count against GitHub's primary rate limit).
    - On 429 or secondary 403 (rate-limit messages), or when X-RateLimit-Remaining
      hits 0, advances a module-level cooldown so all pollers throttle together.
    - While in cooldown, raises `RateLimited` without hitting the network.
    """
    # Cooldown short-circuit — skip the call entirely.
    remaining, reason = _cooldown_remaining()
    if remaining > 0:
        raise RateLimited(remaining, reason or "cooldown")

    cache_key = (url, _params_key(params))
    with _etag_lock:
        cached = _etag_cache.get(cache_key)

    headers = _gh_headers(token)
    if cached:
        headers["If-None-Match"] = cached[0]

    _get = (session or requests).get
    resp = _request_with_retry(_get, url, params=params, headers=headers, timeout=timeout)

    # 304 Not Modified — free, return cached payload.
    if resp.status_code == 304:
        if cached:
            return cached[1]
        # Server sent 304 but our cache is gone (race/protocol-violation) —
        # retry without If-None-Match so we get a real body back.
        headers.pop("If-None-Match", None)
        resp = _request_with_retry(_get, url, params=params, headers=headers, timeout=timeout)

    _check_rate_limit_response(resp)
    _invalidate_username_on_401(resp.status_code)

    resp.raise_for_status()
    data = resp.json()

    _track_remaining_header(resp)

    # Cache ETag + parsed body so the next identical request can 304.
    etag = resp.headers.get("ETag")
    if etag:
        with _etag_lock:
            _etag_cache[cache_key] = (etag, data)
            _prune_cache(_etag_cache, _ETAG_CACHE_MAX)
    return data


_DEFAULT_BOT_PATTERN = r"\[bot\]$"


@functools.lru_cache(maxsize=8)
def _compile_bot_regex(pattern: str) -> re.Pattern:
    """Compile bot-detection regex; silently fall back to default on bad input."""
    try:
        return re.compile(pattern or _DEFAULT_BOT_PATTERN)
    except re.error:
        return re.compile(_DEFAULT_BOT_PATTERN)


def _aggregate_review_status(reviews: list[dict],
                             bot_regex: Optional[re.Pattern] = None) -> tuple[str, bool]:
    """Collapse a PR reviews list to (status, by_bot).

    status ∈ 'approved' | 'changes_requested' | 'commented' | 'pending'.
    by_bot is True iff every reviewer whose latest state equals the winning state
    matches bot_regex. Human wins on mixed reviewers. Always False for
    commented/pending.
    """
    latest: dict[str, str] = {}
    has_comments = False
    for r in reviews:
        user = r.get("user", {}).get("login", "")
        state = r.get("state", "")
        if state in ("APPROVED", "CHANGES_REQUESTED"):
            latest[user] = state
        elif state == "COMMENTED":
            has_comments = True
    if not latest:
        return ("commented" if has_comments else "pending", False)
    winning = "CHANGES_REQUESTED" if "CHANGES_REQUESTED" in latest.values() else "APPROVED"
    status = "changes_requested" if winning == "CHANGES_REQUESTED" else "approved"
    if bot_regex is None:
        return (status, False)
    winners = [u for u, st in latest.items() if st == winning]
    by_bot = bool(winners) and all(bot_regex.search(u) for u in winners)
    return (status, by_bot)


def _cached_review_fetch(url: str, token: str, session: Optional[requests.Session],
                         cache: dict, key, ttl: float,
                         bot_regex: Optional[re.Pattern] = None
                         ) -> tuple[Optional[str], bool]:
    """Fetch+aggregate PR review status with per-key TTL cache. Returns stale value on API error."""
    cached = cache.get(key)
    if cached is not None:
        value, fetch_time = cached
        if time.monotonic() - fetch_time < ttl:
            return value
    try:
        reviews = _github_api_get(url, token, session)
        result = _aggregate_review_status(reviews, bot_regex)
        cache[key] = (result, time.monotonic())
        _prune_cache(cache, _REVIEW_CACHE_MAX)
        return result
    except Exception:
        return cached[0] if cached else (None, False)


# GraphQL query — counts unresolved review threads for a single PR.
# REST doesn't expose `isResolved`, so GraphQL is required here.
_UNRESOLVED_THREADS_QUERY = """
query($owner:String!,$repo:String!,$num:Int!){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$num){
      reviewThreads(first:100){nodes{isResolved}}
    }
  }
}
"""


def _cached_unresolved_fetch(owner: str, repo: str, pr_number: int, token: str,
                             session: Optional[requests.Session],
                             cache: dict, key, ttl: float) -> int:
    """Fetch count of unresolved review threads for a PR with per-key TTL cache.
    Returns stale value on API error, 0 when no prior value exists."""
    cached = cache.get(key)
    if cached is not None:
        count, fetch_time = cached
        if time.monotonic() - fetch_time < ttl:
            return count
    try:
        data = _github_graphql_post(
            _UNRESOLVED_THREADS_QUERY,
            {"owner": owner, "repo": repo, "num": pr_number},
            token, session,
        )
        pr = (data.get("repository") or {}).get("pullRequest") or {}
        nodes = ((pr.get("reviewThreads") or {}).get("nodes")) or []
        count = sum(1 for n in nodes if not n.get("isResolved"))
        cache[key] = (count, time.monotonic())
        _prune_cache(cache, _REVIEW_CACHE_MAX)
        return count
    except Exception:
        return cached[0] if cached else 0


# Cache caps — prevent unbounded growth over long sessions
_PR_CACHE_MAX = 200
_REVIEW_CACHE_MAX = 200
_ETAG_CACHE_MAX = 300


def _prune_cache(cache: dict, max_size: int):
    """Drop oldest entries (dict insertion order) until cache size <= max_size."""
    excess = len(cache) - max_size
    if excess <= 0:
        return
    for k in list(cache.keys())[:excess]:
        cache.pop(k, None)


# ETag / conditional-request cache — 304 responses don't count against
# GitHub's primary rate limit, so every hit here is a free poll.
# Keyed by (url, sorted-params-tuple) → (etag, parsed_json).
_etag_cache: dict = {}
_etag_lock = threading.Lock()

# Rate-limit cooldown gate. When GitHub returns 429 / secondary 403 /
# primary-limit exhaustion, _rate_limit_until (monotonic seconds) is advanced;
# subsequent _github_api_get calls short-circuit with RateLimited until it lapses.
_rate_limit_until: float = 0.0
_rate_limit_reason: str = ""
_rate_limit_lock = threading.Lock()


class RateLimited(Exception):
    """Raised by _github_api_get while the cooldown gate is active."""
    def __init__(self, retry_after: float, reason: str = ""):
        super().__init__(
            f"GitHub rate limited — retry in {int(retry_after)}s ({reason})"
        )
        self.retry_after = retry_after
        self.reason = reason


def _params_key(params: Optional[dict]) -> tuple:
    if not params:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in params.items()))


def _parse_retry_after(resp) -> float:
    """Seconds to wait before retrying. Prefers Retry-After, falls back to X-RateLimit-Reset."""
    ra = resp.headers.get("Retry-After")
    if ra:
        try:
            return max(0.0, float(ra))
        except ValueError:
            pass  # HTTP-date form — ignore, fall through to Reset
    reset = resp.headers.get("X-RateLimit-Reset")
    if reset:
        try:
            return max(0.0, int(reset) - time.time())
        except ValueError:
            pass
    return 60.0  # conservative default when GitHub gives no hint


def _set_cooldown(seconds: float, reason: str):
    global _rate_limit_until, _rate_limit_reason
    if seconds <= 0:
        return
    with _rate_limit_lock:
        new_until = time.monotonic() + seconds
        if new_until > _rate_limit_until:
            _rate_limit_until = new_until
            _rate_limit_reason = reason


def _cooldown_remaining() -> tuple[float, str]:
    with _rate_limit_lock:
        return max(0.0, _rate_limit_until - time.monotonic()), _rate_limit_reason


def _friendly_error(exc: BaseException) -> str:
    """Map a poller exception to a short, user-facing status string.

    Raw `str()` on a `requests.ConnectionError` yields the urllib3 tuple
    (e.g. ``('Connection aborted.', RemoteDisconnected(...))``) — that's the
    text that ends up in the row when GitHub drops a keep-alive socket.
    """
    if isinstance(exc, requests.ConnectionError):
        return "Connection lost — retrying"
    if isinstance(exc, requests.Timeout):
        return "Request timed out — retrying"
    if isinstance(exc, requests.RequestException):
        return "Network error — retrying"
    msg = str(exc) or exc.__class__.__name__
    return msg if len(msg) <= 120 else msg[:117] + "…"


# Exception classes worth retrying once: idle GitHub keep-alive sockets get
# RST'd routinely, and a single transparent retry kills the noise without
# hiding genuine outages.
_TRANSIENT_REQUEST_ERRORS = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _request_with_retry(fn, *args, retries: int = 1, backoff: float = 0.4, **kwargs):
    """Call `fn(*args, **kwargs)`; retry once on transient connection errors."""
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except _TRANSIENT_REQUEST_ERRORS:
            if attempt >= retries:
                raise
            time.sleep(backoff)


def _check_rate_limit_response(resp) -> None:
    """Trip cooldown + raise `RateLimited` on 429 or secondary-limit 403."""
    status = resp.status_code
    if status == 429 or (
        status == 403 and "rate limit" in (resp.text or "").lower()
    ):
        wait = _parse_retry_after(resp)
        _set_cooldown(wait, f"HTTP {status}")
        raise RateLimited(wait, f"HTTP {status}")


def _track_remaining_header(resp) -> None:
    """If X-RateLimit-Remaining hit 0, set cooldown until reset."""
    remaining_hdr = resp.headers.get("X-RateLimit-Remaining")
    if remaining_hdr is None:
        return
    try:
        if int(remaining_hdr) == 0:
            reset_hdr = resp.headers.get("X-RateLimit-Reset")
            if reset_hdr:
                wait = max(0.0, int(reset_hdr) - time.time())
                _set_cooldown(wait, "primary limit exhausted")
    except ValueError:
        pass


def _invalidate_username_on_401(status: int) -> None:
    """Clear cached GitHub username on 401 so a rotated token recovers next poll."""
    if status != 401:
        return
    global _cached_github_username
    with _github_username_lock:
        _cached_github_username = None


def _github_graphql_post(query: str, variables: dict, token: str,
                         session: Optional[requests.Session] = None,
                         timeout: int = 15) -> dict:
    """POST to GitHub's GraphQL API with the same cooldown gate + 401 handling
    as _github_api_get. No ETag cache — GraphQL doesn't honour If-None-Match.
    Returns the `data` payload; raises RateLimited when the cooldown is active
    and RuntimeError when the response contains `errors`."""
    remaining, reason = _cooldown_remaining()
    if remaining > 0:
        raise RateLimited(remaining, reason or "cooldown")

    _post = (session or requests).post
    resp = _request_with_retry(
        _post,
        "https://api.github.com/graphql",
        headers=_gh_headers(token),
        json={"query": query, "variables": variables},
        timeout=timeout,
    )

    _check_rate_limit_response(resp)
    _invalidate_username_on_401(resp.status_code)

    resp.raise_for_status()
    payload = resp.json()

    _track_remaining_header(resp)

    if "errors" in payload:
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload.get("data") or {}


def fetch_latest_run(
    owner: str,
    repo: str,
    workflow_file: str,
    branch: Optional[str],
    token: str,
    session: Optional[requests.Session] = None,
) -> Optional[dict]:
    """Fetch the latest workflow run from the GitHub API."""
    api_url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        f"/actions/workflows/{workflow_file}/runs"
    )
    params: dict = {"per_page": 1}
    if branch:
        params["branch"] = branch
    runs = _github_api_get(api_url, token, session, params).get("workflow_runs", [])
    return runs[0] if runs else None


# ---------------------------------------------------------------------------
# GitHub username (cached)
# ---------------------------------------------------------------------------
_cached_github_username: Optional[str] = None
_github_username_lock = threading.Lock()


def fetch_github_username(token: str, session: Optional[requests.Session] = None) -> Optional[str]:
    """Fetch the authenticated user's login via GET /user. Cached after first call."""
    global _cached_github_username
    if not token:
        return None
    with _github_username_lock:
        if _cached_github_username is not None:
            return _cached_github_username
        # Hold lock through fetch to prevent duplicate API calls from concurrent pollers
        login = _github_api_get("https://api.github.com/user", token, session).get("login")
        _cached_github_username = login
        return login


def fetch_pr_runs(
    owner: str,
    repo: str,
    workflow_file: str,
    actor: str,
    token: str,
    per_page: int = 10,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """Fetch recent workflow runs filtered by actor and pull_request event."""
    api_url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        f"/actions/workflows/{workflow_file}/runs"
    )
    params = {"actor": actor, "event": "pull_request", "per_page": per_page}
    return _github_api_get(api_url, token, session, params).get("workflow_runs", [])


def fetch_runs_by_sha(
    owner: str,
    repo: str,
    head_sha: str,
    token: str,
    per_page: int = 1,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """Fetch workflow runs for a specific commit SHA (newest first)."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    params: dict = {"head_sha": head_sha, "per_page": per_page}
    return _github_api_get(api_url, token, session, params).get("workflow_runs", [])


def fetch_actor_runs(
    owner: str,
    repo: str,
    actor: str,
    token: str,
    per_page: int = 20,
    conclusion: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """Fetch recent workflow runs for a user across all workflows in a repo."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    params: dict = {"actor": actor, "per_page": per_page}
    if conclusion:
        params["conclusion"] = conclusion
    return _github_api_get(api_url, token, session, params).get("workflow_runs", [])


# ---------------------------------------------------------------------------
# Public reset hook (called by main on config reload)
# ---------------------------------------------------------------------------
def reset_username_cache() -> None:
    """Drop the cached GitHub username. Used when the token may have changed."""
    global _cached_github_username
    with _github_username_lock:
        _cached_github_username = None
