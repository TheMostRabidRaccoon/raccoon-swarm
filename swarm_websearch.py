"""Swarm web search — multi-provider, defaults to Tavily.

Returns title + url + snippet for each hit. No full-page fetch (keeps the
prompt-injection surface area small). Per-session and rolling-24h rate
limits keep cost and noise bounded.

Providers (selected via WEBSEARCH_PROVIDER env var, default 'tavily'):

  tavily       — Tavily AI search (https://tavily.com). Designed for LLM
                 agent use; clean snippets, single API key, free tier
                 covers ~1000 queries/month. Required env: TAVILY_API_KEY.

  google_cse   — Google Programmable Search (Custom Search JSON API).
                 As of Jan 2026 new engines are limited to a 50-domain
                 allowlist, so this only makes sense for curated-corpus
                 search. Required env: GOOGLE_CSE_ID + GOOGLE_CSE_API_KEY
                 (falls back to GOOGLE_API_KEY).

Override the default per-call by passing provider='google_cse' / 'tavily'.
"""
from __future__ import annotations

import os
import logging
import threading
from collections import deque
from datetime import datetime, timedelta

import requests

logger = logging.getLogger("SwarmVault")

MAX_PER_SESSION = 30
MAX_PER_24H = 200

VALID_PROVIDERS = ("tavily", "google_cse")
DEFAULT_PROVIDER = "tavily"

_session_counts: dict[str, int] = {}
_recent_calls: deque[datetime] = deque()
_lock = threading.Lock()

_GOOGLE_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
_TAVILY_ENDPOINT = "https://api.tavily.com/search"


# ============================================================
# Provider config + rate limits
# ============================================================

def _resolved_provider(provider: str | None) -> tuple[str, str | None]:
    """Resolve which provider to use. Returns (provider, pivot_note).

    Resolution order:
      1. Explicit caller arg → honored verbatim, no auto-pivot. A model that
         asks for google_cse and finds it misconfigured gets a clean error.
      2. WEBSEARCH_PROVIDER env var.
      3. DEFAULT_PROVIDER ("tavily").

    For the env-var / default path, if the chosen provider isn't configured
    but another VALID_PROVIDERS entry is, auto-pivot to the configured one.
    This keeps a stale `WEBSEARCH_PROVIDER=google_cse` from before PR #30
    from breaking searches when only TAVILY_API_KEY is set.
    """
    explicit = bool(provider)
    raw = (provider or os.getenv("WEBSEARCH_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    chosen = raw if raw in VALID_PROVIDERS else DEFAULT_PROVIDER

    if explicit:
        return chosen, None

    ok, _ = _config_status(chosen)
    if ok:
        return chosen, None

    for alt in VALID_PROVIDERS:
        if alt == chosen:
            continue
        alt_ok, _ = _config_status(alt)
        if alt_ok:
            return alt, f"{chosen} not configured; routed to {alt}"

    return chosen, None


def _config_status_tavily() -> tuple[bool, str]:
    if not os.getenv("TAVILY_API_KEY"):
        return False, "missing env var: TAVILY_API_KEY"
    return True, "ok"


def _config_status_google_cse() -> tuple[bool, str]:
    cx = os.getenv("GOOGLE_CSE_ID")
    key = os.getenv("GOOGLE_CSE_API_KEY") or os.getenv("GOOGLE_API_KEY")
    missing = []
    if not cx:
        missing.append("GOOGLE_CSE_ID")
    if not key:
        missing.append("GOOGLE_CSE_API_KEY (or GOOGLE_API_KEY)")
    if missing:
        return False, f"missing env vars: {', '.join(missing)}"
    return True, "ok"


def _config_status(provider: str) -> tuple[bool, str]:
    if provider == "tavily":
        return _config_status_tavily()
    if provider == "google_cse":
        return _config_status_google_cse()
    return False, f"unknown provider: {provider}"


def _check_rate_limits(session_id: str) -> tuple[bool, str]:
    with _lock:
        if _session_counts.get(session_id, 0) >= MAX_PER_SESSION:
            return False, f"session limit ({MAX_PER_SESSION}) reached"
        cutoff = datetime.now() - timedelta(hours=24)
        while _recent_calls and _recent_calls[0] < cutoff:
            _recent_calls.popleft()
        if len(_recent_calls) >= MAX_PER_24H:
            return False, f"daily limit ({MAX_PER_24H}) reached"
    return True, "ok"


def _record_call(session_id: str) -> None:
    with _lock:
        _session_counts[session_id] = _session_counts.get(session_id, 0) + 1
        _recent_calls.append(datetime.now())


# ============================================================
# Provider implementations
# ============================================================

def _search_tavily(query: str, num_results: int, site: str) -> tuple[list[dict], str | None]:
    """Returns (results, error). On error, results=[]."""
    body = {
        "query": query,
        "max_results": num_results,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
    }
    if site:
        body["include_domains"] = [site.strip()]

    try:
        resp = requests.post(
            _TAVILY_ENDPOINT,
            json=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.getenv('TAVILY_API_KEY')}",
            },
            timeout=20,
        )
    except requests.RequestException as e:
        return [], f"network error: {e}"

    if resp.status_code != 200:
        return [], f"http {resp.status_code}: {resp.text[:300]}"

    try:
        data = resp.json()
    except ValueError:
        return [], "non-JSON response from Tavily"

    items = data.get("results") or []
    out = []
    for it in items:
        url = it.get("url", "")
        # Best-effort 'source' display from URL host
        source = ""
        if url:
            try:
                from urllib.parse import urlparse
                source = urlparse(url).netloc
            except Exception:
                source = ""
        out.append({
            "title": it.get("title", ""),
            "url": url,
            "snippet": it.get("content", ""),
            "source": source,
            "score": it.get("score"),
        })
    return out, None


def _search_google_cse(query: str, num_results: int, site: str) -> tuple[list[dict], str | None]:
    q = query
    if site:
        q = f"{q} site:{site.strip()}"
    params = {
        "key": os.getenv("GOOGLE_CSE_API_KEY") or os.getenv("GOOGLE_API_KEY"),
        "cx": os.getenv("GOOGLE_CSE_ID"),
        "q": q,
        "num": num_results,
        "safe": "active",
    }
    try:
        resp = requests.get(_GOOGLE_CSE_ENDPOINT, params=params, timeout=20)
    except requests.RequestException as e:
        return [], f"network error: {e}"

    if resp.status_code != 200:
        return [], f"http {resp.status_code}: {resp.text[:300]}"

    try:
        data = resp.json()
    except ValueError:
        return [], "non-JSON response from Google CSE"

    items = data.get("items") or []
    out = []
    for it in items:
        out.append({
            "title": it.get("title", ""),
            "url": it.get("link", ""),
            "snippet": it.get("snippet", ""),
            "source": it.get("displayLink") or "",
        })
    return out, None


_BACKENDS = {
    "tavily": _search_tavily,
    "google_cse": _search_google_cse,
}


# ============================================================
# Public entrypoint
# ============================================================

def search(
    query: str,
    num_results: int = 5,
    site: str = "",
    session_id: str = "unknown",
    model: str = "unknown",
    provider: str | None = None,
) -> dict:
    """Run a web search. Returns {ok, provider, results: [{title, url, snippet, source}], ...}."""
    if not query or len(query.strip()) < 2:
        return {"ok": False, "error": "query too short (min 2 chars)"}

    chosen, pivot_note = _resolved_provider(provider)
    if pivot_note:
        logger.info(f"swarm_websearch auto-pivot: {pivot_note}")
    ok, reason = _config_status(chosen)
    if not ok:
        return {"ok": False, "provider": chosen, "error": reason}

    allowed, reason = _check_rate_limits(session_id)
    if not allowed:
        return {"ok": False, "provider": chosen, "error": reason}

    num = max(1, min(int(num_results or 5), 10))
    q = query.strip()

    backend = _BACKENDS[chosen]
    try:
        results, err = backend(q, num, site)
    except Exception as e:
        logger.error(f"swarm_websearch {chosen} unexpected: {type(e).__name__}: {e}")
        return {"ok": False, "provider": chosen, "error": f"{type(e).__name__}: {e}"}

    if err:
        # Don't count failed calls against the per-session/24h budget
        logger.warning(f"swarm_websearch {chosen} failed: {err}")
        return {"ok": False, "provider": chosen, "error": err}

    _record_call(session_id)
    logger.info(
        f"swarm_websearch ok — provider={chosen} model={model} session={session_id} "
        f"q={q!r} hits={len(results)}"
    )
    return {
        "ok": True,
        "provider": chosen,
        "query": q,
        "results": results,
        "total_returned": len(results),
        "session_used": _session_counts.get(session_id, 0),
        "session_cap": MAX_PER_SESSION,
    }


def status() -> dict:
    cutoff = datetime.now() - timedelta(hours=24)
    with _lock:
        recent_count = sum(1 for t in _recent_calls if t >= cutoff)
        per_session = dict(_session_counts)

    providers = {}
    for name in VALID_PROVIDERS:
        ok, reason = _config_status(name)
        providers[name] = {"configured": ok, "status": reason}

    active, pivot_note = _resolved_provider(None)
    return {
        "active_provider": active,
        "default_provider": DEFAULT_PROVIDER,
        "active_configured": providers[active]["configured"],
        "active_status": providers[active]["status"],
        "auto_pivot_note": pivot_note,
        "providers": providers,
        "max_per_session": MAX_PER_SESSION,
        "max_per_24h": MAX_PER_24H,
        "calls_in_last_24h": recent_count,
        "per_session_counts": per_session,
    }
