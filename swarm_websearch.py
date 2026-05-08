"""Swarm web search — Google Programmable Search (Custom Search JSON API).

Returns title + snippet + URL. No full-page fetch (yet) to keep prompt-injection
surface area small. Rate-limited per session and per rolling 24h to keep cost
and noise bounded.

Required env vars:
  GOOGLE_CSE_ID         — your Programmable Search engine "cx" id
  GOOGLE_CSE_API_KEY    — API key with Custom Search JSON API enabled
                          (falls back to GOOGLE_API_KEY if unset)

Endpoint reference:
  https://developers.google.com/custom-search/v1/using_rest
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

_session_counts: dict[str, int] = {}
_recent_calls: deque[datetime] = deque()
_lock = threading.Lock()

_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


def _config_status() -> tuple[bool, str]:
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


def search(
    query: str,
    num_results: int = 5,
    site: str = "",
    session_id: str = "unknown",
    model: str = "unknown",
) -> dict:
    """Run a Google web search. Returns {ok, results: [{title, url, snippet}], ...}."""
    if not query or len(query.strip()) < 2:
        return {"ok": False, "error": "query too short (min 2 chars)"}

    ok, reason = _config_status()
    if not ok:
        return {"ok": False, "error": reason}

    allowed, reason = _check_rate_limits(session_id)
    if not allowed:
        return {"ok": False, "error": reason}

    num = max(1, min(int(num_results or 5), 10))
    q = query.strip()
    if site:
        q = f"{q} site:{site.strip()}"

    params = {
        "key": os.getenv("GOOGLE_CSE_API_KEY") or os.getenv("GOOGLE_API_KEY"),
        "cx": os.getenv("GOOGLE_CSE_ID"),
        "q": q,
        "num": num,
        "safe": "active",
    }

    try:
        resp = requests.get(_ENDPOINT, params=params, timeout=20)
    except requests.RequestException as e:
        logger.error(f"swarm_websearch request failed: {e}")
        return {"ok": False, "error": f"network error: {e}"}

    if resp.status_code != 200:
        # Don't count a failed call against the budget
        body = resp.text[:300]
        logger.warning(f"swarm_websearch http {resp.status_code}: {body}")
        return {"ok": False, "error": f"http {resp.status_code}: {body}"}

    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "error": "non-JSON response from Google CSE"}

    items = data.get("items") or []
    results = []
    for it in items:
        results.append({
            "title": it.get("title", ""),
            "url": it.get("link", ""),
            "snippet": it.get("snippet", ""),
            "source": (it.get("displayLink") or ""),
        })

    _record_call(session_id)
    logger.info(
        f"swarm_websearch ok — model={model} session={session_id} "
        f"q={q!r} hits={len(results)}"
    )
    return {
        "ok": True,
        "query": q,
        "results": results,
        "total_returned": len(results),
        "session_used": _session_counts.get(session_id, 0),
        "session_cap": MAX_PER_SESSION,
    }


def status() -> dict:
    ok, reason = _config_status()
    cutoff = datetime.now() - timedelta(hours=24)
    with _lock:
        recent_count = sum(1 for t in _recent_calls if t >= cutoff)
        per_session = dict(_session_counts)
    return {
        "configured": ok,
        "config_status": reason,
        "max_per_session": MAX_PER_SESSION,
        "max_per_24h": MAX_PER_24H,
        "calls_in_last_24h": recent_count,
        "per_session_counts": per_session,
        "provider": "Google Programmable Search (CSE)",
    }
