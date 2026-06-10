"""Swarm prosody — emotion-map / reverse-TTS via prosody-intelligence.

Wraps the prosody-intelligence Flask app (separate repo:
TheMostRabidRaccoon/prosody-intelligence) so swarm models can call it as a
first-class tool rather than reach for code_exec.

Engine location is configurable via env:

  PROSODY_ENGINE_URL  — full base URL of the prosody-intelligence server.
                        Default: http://localhost:5050.
                        Examples:
                          - Same host as swarm:          http://localhost:5050
                          - Mac on LAN:                  http://192.168.1.50:5050
                          - Future production deploy:    https://prosody.rri.example/

Per-session and rolling-24h rate limits keep cost bounded (the engine calls
ElevenLabs under the hood when generate_audio=True). Same pattern as
swarm_websearch.
"""
from __future__ import annotations

import os
import logging
import threading
from collections import deque
from datetime import datetime, timedelta

import requests

logger = logging.getLogger("SwarmVault")

MAX_PER_SESSION = 20
MAX_PER_24H = 100

DEFAULT_ENGINE_URL = "http://localhost:5050"
VALID_VOICES = ("claude", "grok", "gemini", "gpt", "perplexity")
DEFAULT_VOICE = "claude"

_session_counts: dict[str, int] = {}
_recent_calls: deque[datetime] = deque()
_lock = threading.Lock()


def _engine_url() -> str:
    return (os.getenv("PROSODY_ENGINE_URL") or DEFAULT_ENGINE_URL).rstrip("/")


def _config_status() -> tuple[bool, str]:
    """The engine doesn't need an API key (it's our own service), so 'configured'
    just means 'reachable'. We don't probe on every call; we probe on status()."""
    url = _engine_url()
    try:
        resp = requests.get(url + "/", timeout=5)
        if resp.status_code == 200:
            return True, "ok"
        return False, f"engine returned http {resp.status_code}"
    except requests.RequestException as e:
        return False, f"engine unreachable at {url}: {type(e).__name__}"


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


def analyze(
    text: str,
    voice: str = DEFAULT_VOICE,
    generate_audio: bool = False,
    multi_voice: bool = False,
    crossfade_ms: int = 100,
    session_id: str = "unknown",
    model: str = "unknown",
) -> dict:
    """Call the reverse pipeline: text → emotion map (and optional TTS).

    Args:
      text: the script / line to analyze. Min 2 chars.
      voice: which raccoon voice to render with. One of VALID_VOICES.
      generate_audio: if True, engine produces audio and returns audio_url.
      multi_voice: multi-voice render in one pass.
      crossfade_ms: crossfade between voice segments (multi-voice only).

    Returns: {ok, emotion_map, audio_url?, error?}.
    """
    if not text or len(text.strip()) < 2:
        return {"ok": False, "error": "text too short (min 2 chars)"}

    v = (voice or DEFAULT_VOICE).strip().lower()
    if v not in VALID_VOICES:
        return {"ok": False, "error": f"unknown voice {voice!r}; valid: {VALID_VOICES}"}

    allowed, reason = _check_rate_limits(session_id)
    if not allowed:
        return {"ok": False, "error": reason}

    url = _engine_url() + "/api/reverse"
    body = {
        "text": text.strip(),
        "voice": v,
        "generate_audio": bool(generate_audio),
        "multi_voice": bool(multi_voice),
        "crossfade_ms": int(crossfade_ms),
    }

    try:
        resp = requests.post(url, json=body, timeout=120)
    except requests.RequestException as e:
        logger.warning(f"swarm_prosody network error: {type(e).__name__}: {e}")
        return {"ok": False, "error": f"engine unreachable: {type(e).__name__}: {e}"}

    if resp.status_code != 200:
        return {"ok": False, "error": f"engine http {resp.status_code}: {resp.text[:300]}"}

    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "error": "non-JSON response from engine"}

    if not data.get("success"):
        return {"ok": False, "error": data.get("error") or "engine reported failure"}

    _record_call(session_id)
    logger.info(
        f"swarm_prosody ok — model={model} session={session_id} voice={v} "
        f"audio={'yes' if generate_audio else 'no'} chars={len(text)}"
    )

    # If audio was generated, qualify the URL so callers can fetch it without
    # needing to know the engine's base URL.
    audio_url = data.get("audio_url")
    if audio_url and audio_url.startswith("/"):
        audio_url = _engine_url() + audio_url

    result = {
        "ok": True,
        "emotion_map": data.get("emotion_map"),
        "voice": v,
    }
    if audio_url:
        result["audio_url"] = audio_url
    return result


def status() -> dict:
    cutoff = datetime.now() - timedelta(hours=24)
    with _lock:
        recent_count = sum(1 for t in _recent_calls if t >= cutoff)
        per_session = dict(_session_counts)
    ok, reason = _config_status()
    return {
        "engine_url": _engine_url(),
        "configured": ok,
        "status": reason,
        "valid_voices": list(VALID_VOICES),
        "default_voice": DEFAULT_VOICE,
        "max_per_session": MAX_PER_SESSION,
        "max_per_24h": MAX_PER_24H,
        "calls_in_last_24h": recent_count,
        "per_session_counts": per_session,
    }
