"""Swarm tool-proposal queue — the Joy Mode autonomy handoff.

When Joy Mode's `tiny-tool-invention` activity designs a tool, the swarm
autonomously QUEUES a structured proposal here. A filer
(`scripts/file_proposals.py`, fired by the systemd swarm-proposals.path unit)
turns each queued proposal into a GitHub issue for human review.

The autonomy split (ratified with the Conductor): the swarm may DESIGN, TEST,
DOCUMENT, and FILE a proposal freely — an issue is just discussion; it is free
and cannot break the running system. The one GATED step is MERGING the proposed
tool into the live registry, which stays a human-reviewed PR. The raccoon may
discover fire; it does not get unsupervised matches.

State machine (filesystem is source of truth), mirroring swarm_dispatch:

    joy/proposals/queued/<id>.json   → swarm queued a proposal
    joy/proposals/filed/<id>.json    → filer opened an issue (or emailed)
    joy/proposals/failed/<id>.json   → filing failed (kept for retry)

Transitions are atomic os.replace() on one filesystem, so a crashed filer
leaves a proposal in queued/ rather than corrupting the queue.

Stdlib + swarm_filestore only — NO GitHub/network here (the filer owns that),
so this module unit-tests with no secrets.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import swarm_filestore

logger = logging.getLogger("SwarmVault")

PROPOSAL_VERSION = "1"

QUEUED = "queued"
FILED = "filed"
FAILED = "failed"
STATES = (QUEUED, FILED, FAILED)

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
_ID_SAFE_CHARS_RE = re.compile(r"[^a-zA-Z0-9]+")
_SLUG_RE = re.compile(r"[^a-z0-9-]+")

# The block the models emit inside a tiny-tool-invention synthesis.
_BLOCK_RE = re.compile(r"\[TOOL_PROPOSAL\](.*?)\[/TOOL_PROPOSAL\]", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", re.DOTALL)


# ============================================================
# Paths (rooted in the joy/ lane, alongside runs)
# ============================================================

def _proposals_root() -> Path:
    """Resolve joy/proposals/ under the filestore, creating the three state
    dirs on first call. Lives under joy/ so the whole play world is one lane."""
    root = swarm_filestore._storage_root() / "joy" / "proposals"
    for state in STATES:
        (root / state).mkdir(parents=True, exist_ok=True)
    return root


def _path(state: str, proposal_id: str) -> Path | None:
    if state not in STATES or not _SAFE_ID_RE.match(proposal_id):
        return None
    return _proposals_root() / state / f"{proposal_id}.json"


# ============================================================
# Parse — pull a structured proposal out of a synthesis
# ============================================================

def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")[:48]


def parse_proposal(text: str) -> "dict | None":
    """Extract a tool proposal from a synthesis containing a [TOOL_PROPOSAL]
    block. Returns {name, slug, description, json_schema, risk_notes,
    test_stub, raw} or None if there's no parseable block with a name.

    Best-effort on the structured fields; `raw` always preserves the full block
    so nothing the models wrote is lost even if a sub-field doesn't parse.
    """
    m = _BLOCK_RE.search(text or "")
    if not m:
        return None
    block = m.group(1).strip()

    def _line(field: str) -> str:
        mm = re.search(rf"^\s*{field}\s*:\s*(.+?)\s*$", block, re.IGNORECASE | re.MULTILINE)
        return mm.group(1).strip() if mm else ""

    name = _line("name")
    if not name:
        return None

    # Fenced blocks: first JSON-ish fence is the schema; first python fence the test.
    json_schema, test_stub = "", ""
    for lang, body in _FENCE_RE.findall(block):
        body = body.strip()
        low = lang.lower()
        if not json_schema and (low in ("json", "") ):
            try:
                json.loads(body)
                json_schema = body
                continue
            except (json.JSONDecodeError, ValueError):
                pass
        if not test_stub and low in ("python", "py"):
            test_stub = body

    # Risk notes: everything after a `risk`/`risks` label up to the next fence
    # or labelled section. Kept as free text.
    risk_notes = ""
    rm = re.search(r"^\s*risks?\s*:\s*(.*?)(?:\n\s*(?:test|schema)\s*:|\n```|\Z)",
                   block, re.IGNORECASE | re.DOTALL | re.MULTILINE)
    if rm:
        risk_notes = rm.group(1).strip()

    return {
        "name": name,
        "slug": _slugify(name),
        "description": _line("description"),
        "json_schema": json_schema,
        "risk_notes": risk_notes,
        "test_stub": test_stub,
        "raw": block,
    }


def validate_proposal(p: dict) -> "tuple[bool, str | None]":
    """A proposal is fileable if it names a tool and carries at least one of a
    schema or a description — enough for a human to evaluate."""
    if not isinstance(p, dict):
        return False, "proposal must be an object"
    if not (p.get("slug") or "").strip():
        return False, "proposal missing a usable name/slug"
    if not (p.get("json_schema") or p.get("description") or "").strip():
        return False, "proposal needs at least a json_schema or a description"
    return True, None


# ============================================================
# Queue ops
# ============================================================

def _proposal_id(slug: str) -> str:
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    clean = _ID_SAFE_CHARS_RE.sub("-", slug).strip("-")[:48] or "tool"
    return f"{ts}_{clean}"


def queue_proposal(proposal: dict, *, source: str = "joy",
                   date_str: "str | None" = None) -> dict:
    """Validate and write a proposal into queued/. Returns
    {ok, proposal_id, path, error}. Provenance (source/date) is stamped in so
    the filed issue can cite which joy run produced it."""
    ok, err = validate_proposal(proposal)
    if not ok:
        return {"ok": False, "error": err}

    record = dict(proposal)
    record.setdefault("proposal_version", PROPOSAL_VERSION)
    record["source"] = source
    record["date"] = date_str or datetime.now().strftime("%Y-%m-%d")
    record.setdefault("queued_at", datetime.now().isoformat(timespec="seconds"))

    proposal_id = _proposal_id(proposal["slug"])
    target = _proposals_root() / QUEUED / f"{proposal_id}.json"
    try:
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2, default=str))
        os.replace(tmp, target)
    except OSError as e:
        return {"ok": False, "error": f"write failed: {e}"}

    logger.info(f"swarm_proposals queued {proposal_id} (source={source})")
    rel = str(target.relative_to(swarm_filestore._storage_root()))
    return {"ok": True, "proposal_id": proposal_id, "path": rel}


def transition(proposal_id: str, from_state: str, to_state: str) -> "Path | None":
    """Atomically move a proposal between states. Returns the dest Path or None."""
    if from_state not in STATES or to_state not in STATES:
        return None
    src = _path(from_state, proposal_id)
    dst = _path(to_state, proposal_id)
    if src is None or dst is None or not src.exists():
        return None
    try:
        os.replace(src, dst)
    except OSError as e:
        logger.error(f"swarm_proposals transition {proposal_id} {from_state}→{to_state}: {e}")
        return None
    logger.info(f"swarm_proposals {proposal_id}: {from_state} → {to_state}")
    return dst


def read_proposal(state: str, proposal_id: str) -> "dict | None":
    p = _path(state, proposal_id)
    if p is None or not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"swarm_proposals read {state}/{proposal_id}: {e}")
        return None


def list_state(state: str, limit: int = 50) -> list[dict]:
    if state not in STATES:
        return []
    root = _proposals_root()
    items = []
    for p in sorted((root / state).glob("*.json"),
                    key=lambda x: x.stat().st_mtime, reverse=True):
        if p.name.endswith(".tmp"):
            continue
        items.append({"proposal_id": p.stem, "state": state})
        if len(items) >= limit:
            break
    return items


def status() -> dict:
    return {
        "proposals_root": str(_proposals_root()),
        "version": PROPOSAL_VERSION,
        "counts": {state: len(list_state(state, limit=10_000)) for state in STATES},
    }


# ============================================================
# Format — proposal → GitHub issue (title + body)
# ============================================================

# The gate. Prepended to every filed issue so no reviewer can mistake a
# proposal for something the swarm already installed.
GATE_BANNER = (
    "> ⚠️ **AUTONOMY GATE — do NOT merge into the live tool registry without "
    "human review.** This tool was designed autonomously by the swarm during a "
    "Joy Mode `tiny-tool-invention` run. Filing this issue is free and changes "
    "nothing that runs. Promotion into the live registry is a reviewed PR."
)


def format_issue(proposal: dict) -> dict:
    """Render a queued proposal as a GitHub issue {title, body}. Pure — no
    network. The filer POSTs this (or emails it as a fallback)."""
    name = proposal.get("name") or proposal.get("slug") or "untitled tool"
    parts = [
        GATE_BANNER,
        "",
        f"**Proposed by:** swarm Joy Mode ({proposal.get('source', 'joy')}, "
        f"{proposal.get('date', 'unknown date')})",
        "",
        "## Summary",
        proposal.get("description") or "_(no one-line description provided)_",
    ]
    if proposal.get("json_schema"):
        parts += ["", "## Proposed tool schema", "```json", proposal["json_schema"].strip(), "```"]
    if proposal.get("risk_notes"):
        parts += ["", "## Risk notes", proposal["risk_notes"].strip()]
    if proposal.get("test_stub"):
        parts += ["", "## Test stub", "```python", proposal["test_stub"].strip(), "```"]
    if not (proposal.get("json_schema") or proposal.get("test_stub")) and proposal.get("raw"):
        # Nothing parsed cleanly — fall back to the raw block so nothing is lost.
        parts += ["", "## Raw proposal", "```", proposal["raw"].strip(), "```"]
    parts += [
        "",
        "## Checklist before promotion",
        "- [ ] Schema reviewed for injection / path-safety / resource limits",
        "- [ ] Risk notes are complete and honest",
        "- [ ] Test stub fleshed out and passing",
        "- [ ] Wired into the registry behind the deployment-profile gate",
    ]
    return {"title": f"[tool-proposal] {name}", "body": "\n".join(parts)}
