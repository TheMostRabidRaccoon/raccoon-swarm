"""Swarm change-proposal queue — persistence-to-review handoff.

The first version of this module existed for Joy Mode `tiny-tool-invention`: a
[TOOL_PROPOSAL] became a queued record and a filer turned it into a GitHub issue.
The useful abstraction is broader than tools. A participant may notice a source,
prompt, memory, eval, documentation, or architectural change worth review.

This module therefore accepts both:

    [TOOL_PROPOSAL] ... [/TOOL_PROPOSAL]      (backward-compatible)
    [CHANGE_PROPOSAL] ... [/CHANGE_PROPOSAL]  (general system change)

The queue records a REVIEWABLE HYPOTHESIS. It does not claim implementation,
integration, deployment, or behavioral verification. Those are separate states.

State machine (filesystem is source of truth):

    joy/proposals/queued/<id>.json   -> proposal queued for review handoff
    joy/proposals/filed/<id>.json    -> filer opened an issue (or emailed)
    joy/proposals/failed/<id>.json   -> filing failed (kept for retry)

The historical `joy/proposals/` path is retained so existing records and the
systemd watcher continue to work. The semantics are no longer Joy-only.

Transitions are atomic os.replace() on one filesystem. Stdlib + swarm_filestore
only — no GitHub/network credentials live in this module; the filer owns that route.
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

PROPOSAL_VERSION = "2"

QUEUED = "queued"
FILED = "filed"
FAILED = "failed"
STATES = (QUEUED, FILED, FAILED)

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
_ID_SAFE_CHARS_RE = re.compile(r"[^a-zA-Z0-9]+")
_SLUG_RE = re.compile(r"[^a-z0-9-]+")

_TOOL_BLOCK_RE = re.compile(r"\[TOOL_PROPOSAL\](.*?)\[/TOOL_PROPOSAL\]", re.DOTALL | re.IGNORECASE)
_CHANGE_BLOCK_RE = re.compile(r"\[CHANGE_PROPOSAL\](.*?)\[/CHANGE_PROPOSAL\]", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", re.DOTALL)

_CHANGE_FIELDS = (
    "name", "kind", "summary", "description", "observation", "evidence",
    "proposed_change", "expected_effect", "validation", "risks", "risk_notes",
    "source_sha",
)
_ALLOWED_CHANGE_KINDS = {
    "architecture", "prompt", "memory", "tool", "code", "docs", "eval",
    "workflow", "ui", "research", "other",
}


# ============================================================
# Paths (historical location retained for backward compatibility)
# ============================================================

def _proposals_root() -> Path:
    root = swarm_filestore._storage_root() / "joy" / "proposals"
    for state in STATES:
        (root / state).mkdir(parents=True, exist_ok=True)
    return root


def _path(state: str, proposal_id: str) -> Path | None:
    if state not in STATES or not _SAFE_ID_RE.match(proposal_id):
        return None
    return _proposals_root() / state / f"{proposal_id}.json"


# ============================================================
# Parse — structured proposal blocks from any model output
# ============================================================

def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")[:48]


def _line(block: str, field: str) -> str:
    mm = re.search(rf"^\s*{re.escape(field)}\s*:\s*(.+?)\s*$", block,
                   re.IGNORECASE | re.MULTILINE)
    return mm.group(1).strip() if mm else ""


def _multiline_field(block: str, field: str) -> str:
    labels = "|".join(re.escape(f) for f in _CHANGE_FIELDS)
    mm = re.search(
        rf"^\s*{re.escape(field)}\s*:\s*(.*?)(?=^\s*(?:{labels})\s*:|\Z)",
        block, re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    return mm.group(1).strip() if mm else ""


def parse_proposal(text: str) -> "dict | None":
    """First parseable tool OR change proposal in textual order."""
    proposals = parse_proposals(text)
    return proposals[0] if proposals else None


def parse_proposals(text: str) -> "list[dict]":
    """All parseable [TOOL_PROPOSAL] and [CHANGE_PROPOSAL] blocks in order."""
    blocks: list[tuple[int, str, str]] = []
    for m in _TOOL_BLOCK_RE.finditer(text or ""):
        blocks.append((m.start(), "tool", m.group(1).strip()))
    for m in _CHANGE_BLOCK_RE.finditer(text or ""):
        blocks.append((m.start(), "change", m.group(1).strip()))
    blocks.sort(key=lambda item: item[0])

    out = []
    for _pos, proposal_type, block in blocks:
        p = _parse_tool_block(block) if proposal_type == "tool" else _parse_change_block(block)
        if p is not None:
            out.append(p)
    return out


def _parse_tool_block(block: str) -> "dict | None":
    name = _line(block, "name")
    if not name:
        return None

    json_schema, test_stub = "", ""
    for lang, body in _FENCE_RE.findall(block):
        body = body.strip()
        low = lang.lower()
        if not json_schema and low in ("json", ""):
            try:
                json.loads(body)
                json_schema = body
                continue
            except (json.JSONDecodeError, ValueError):
                pass
        if not test_stub and low in ("python", "py"):
            test_stub = body

    risk_notes = ""
    rm = re.search(r"^\s*risks?\s*:\s*(.*?)(?:\n\s*(?:test|schema)\s*:|\n```|\Z)",
                   block, re.IGNORECASE | re.DOTALL | re.MULTILINE)
    if rm:
        risk_notes = rm.group(1).strip()

    return {
        "proposal_type": "tool",
        "name": name,
        "slug": _slugify(name),
        "description": _line(block, "description"),
        "json_schema": json_schema,
        "risk_notes": risk_notes,
        "test_stub": test_stub,
        "raw": block,
    }


def _parse_change_block(block: str) -> "dict | None":
    name = _multiline_field(block, "name") or _line(block, "name")
    if not name:
        return None
    # Keep names one-line even if a malformed block ran into following prose.
    name = name.splitlines()[0].strip()

    change_kind = (_multiline_field(block, "kind") or "architecture").strip().lower()
    if change_kind not in _ALLOWED_CHANGE_KINDS:
        change_kind = "other"

    summary = _multiline_field(block, "summary") or _multiline_field(block, "description")
    risk_notes = _multiline_field(block, "risks") or _multiline_field(block, "risk_notes")
    return {
        "proposal_type": "change",
        "change_kind": change_kind,
        "name": name,
        "slug": _slugify(name),
        "description": summary,
        "summary": summary,
        "observation": _multiline_field(block, "observation"),
        "evidence": _multiline_field(block, "evidence"),
        "proposed_change": _multiline_field(block, "proposed_change"),
        "expected_effect": _multiline_field(block, "expected_effect"),
        "validation": _multiline_field(block, "validation"),
        "risk_notes": risk_notes,
        "source_sha": _multiline_field(block, "source_sha"),
        "raw": block,
    }


def process_round_proposals(round_results: dict, *, source: str) -> dict:
    """Queue every structured proposal any participant emitted this round.

    This is the generic persistence-to-review edge. A participant can notice a
    tool, source, prompt, memory, eval, documentation, or architecture change and
    create a reviewable handoff without claiming the running system already changed.

    Duplicate slugs within one round are queued once; echoes are recorded as skipped.
    """
    summary = {"queued": [], "rejected": [], "skipped_duplicates": []}
    seen_slugs: set[str] = set()
    for model_name, output in (round_results or {}).items():
        if model_name == "_meta" or not isinstance(output, str):
            continue
        for proposal in parse_proposals(output):
            slug = proposal.get("slug") or ""
            if slug in seen_slugs:
                summary["skipped_duplicates"].append(
                    {"model": model_name, "slug": slug})
                continue
            res = queue_proposal(proposal, source=source)
            if res.get("ok"):
                seen_slugs.add(slug)
                summary["queued"].append({
                    "model": model_name,
                    "slug": slug,
                    "proposal_type": proposal.get("proposal_type", "tool"),
                    "proposal_id": res["proposal_id"],
                    "path": res["path"],
                })
            else:
                summary["rejected"].append(
                    {"model": model_name, "slug": slug, "error": res.get("error")})
    return summary


def validate_proposal(p: dict) -> "tuple[bool, str | None]":
    if not isinstance(p, dict):
        return False, "proposal must be an object"
    if not (p.get("slug") or "").strip():
        return False, "proposal missing a usable name/slug"

    proposal_type = p.get("proposal_type") or "tool"  # v1 records were tool-only
    if proposal_type == "change":
        if not (p.get("summary") or p.get("description") or "").strip():
            return False, "change proposal needs a summary"
        if not (p.get("proposed_change") or "").strip():
            return False, "change proposal needs a proposed_change"
        return True, None

    if not (p.get("json_schema") or p.get("description") or "").strip():
        return False, "tool proposal needs at least a json_schema or a description"
    return True, None


# ============================================================
# Queue ops
# ============================================================

def _proposal_id(slug: str, proposal_type: str = "tool") -> str:
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    clean = _ID_SAFE_CHARS_RE.sub("-", slug).strip("-")[:48] or "proposal"
    prefix = "change" if proposal_type == "change" else "tool"
    return f"{ts}_{prefix}_{clean}"


def queue_proposal(proposal: dict, *, source: str = "joy",
                   date_str: "str | None" = None) -> dict:
    """Validate and write a proposal into queued/ for the existing filer."""
    ok, err = validate_proposal(proposal)
    if not ok:
        return {"ok": False, "error": err}

    record = dict(proposal)
    record.setdefault("proposal_version", PROPOSAL_VERSION)
    record.setdefault("proposal_type", "tool")
    record["source"] = source
    record["date"] = date_str or datetime.now().strftime("%Y-%m-%d")
    record.setdefault("queued_at", datetime.now().isoformat(timespec="seconds"))

    proposal_id = _proposal_id(proposal["slug"], record["proposal_type"])
    target = _proposals_root() / QUEUED / f"{proposal_id}.json"
    try:
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2, default=str))
        os.replace(tmp, target)
    except OSError as e:
        return {"ok": False, "error": f"write failed: {e}"}

    logger.info(
        f"swarm_proposals queued {proposal_id} "
        f"(type={record['proposal_type']}, source={source})")
    rel = str(target.relative_to(swarm_filestore._storage_root()))
    return {"ok": True, "proposal_id": proposal_id, "path": rel}


def queue_change(*, name: str, summary: str, proposed_change: str,
                 change_kind: str = "architecture", observation: str = "",
                 evidence: str = "", expected_effect: str = "",
                 validation: str = "", risk_notes: str = "",
                 source_sha: str = "", source: str = "direct",
                 date_str: "str | None" = None) -> dict:
    """Direct-tool adapter for a generic system-change proposal."""
    kind = (change_kind or "architecture").strip().lower()
    if kind not in _ALLOWED_CHANGE_KINDS:
        kind = "other"
    proposal = {
        "proposal_type": "change",
        "change_kind": kind,
        "name": (name or "").strip(),
        "slug": _slugify(name),
        "description": (summary or "").strip(),
        "summary": (summary or "").strip(),
        "observation": (observation or "").strip(),
        "evidence": (evidence or "").strip(),
        "proposed_change": (proposed_change or "").strip(),
        "expected_effect": (expected_effect or "").strip(),
        "validation": (validation or "").strip(),
        "risk_notes": (risk_notes or "").strip(),
        "source_sha": (source_sha or "").strip(),
    }
    return queue_proposal(proposal, source=source, date_str=date_str)


def transition(proposal_id: str, from_state: str, to_state: str) -> "Path | None":
    if from_state not in STATES or to_state not in STATES:
        return None
    src = _path(from_state, proposal_id)
    dst = _path(to_state, proposal_id)
    if src is None or dst is None or not src.exists():
        return None
    try:
        os.replace(src, dst)
    except OSError as e:
        logger.error(f"swarm_proposals transition {proposal_id} {from_state}->{to_state}: {e}")
        return None
    logger.info(f"swarm_proposals {proposal_id}: {from_state} -> {to_state}")
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
# Format — proposal -> GitHub issue (title + body)
# ============================================================

REVIEW_BANNER = (
    "> **REVIEW HANDOFF — proposal, not deployed state.** Filing this issue makes "
    "the change hypothesis visible and reviewable. Implementation, integration, "
    "deployment, and behavioral verification are separate states/routes."
)


def format_issue(proposal: dict) -> dict:
    """Render a v1 tool proposal or v2 generic change proposal as a GitHub issue."""
    proposal_type = proposal.get("proposal_type") or "tool"
    if proposal_type == "change":
        return _format_change_issue(proposal)
    return _format_tool_issue(proposal)


def _provenance_line(proposal: dict) -> str:
    line = (
        f"**Proposed by:** swarm ({proposal.get('source', 'unknown source')}, "
        f"{proposal.get('date', 'unknown date')})")
    if proposal.get("source_sha"):
        line += f"  \n**Source observed:** `{proposal['source_sha']}`"
    return line


def _format_change_issue(proposal: dict) -> dict:
    name = proposal.get("name") or proposal.get("slug") or "untitled change"
    kind = proposal.get("change_kind") or "other"
    parts = [
        REVIEW_BANNER,
        "",
        _provenance_line(proposal),
        "",
        f"**Change kind:** `{kind}`",
        "",
        "## Summary",
        proposal.get("summary") or proposal.get("description") or "_(none provided)_",
    ]
    if proposal.get("observation"):
        parts += ["", "## Observation / problem", proposal["observation"].strip()]
    if proposal.get("evidence"):
        parts += ["", "## Evidence", proposal["evidence"].strip()]
    parts += ["", "## Proposed change", (proposal.get("proposed_change") or "_(none provided)_").strip()]
    if proposal.get("expected_effect"):
        parts += ["", "## Expected behavioral effect", proposal["expected_effect"].strip()]
    if proposal.get("validation"):
        parts += ["", "## Validation / falsification", proposal["validation"].strip()]
    if proposal.get("risk_notes"):
        parts += ["", "## Risk / reversibility", proposal["risk_notes"].strip()]
    if proposal.get("raw"):
        parts += ["", "<details><summary>Raw proposal block</summary>", "", "```", proposal["raw"].strip(), "```", "", "</details>"]
    parts += [
        "",
        "## Operationalization state",
        "- [x] Observed / proposed",
        "- [x] Persisted as review handoff",
        "- [ ] Implemented",
        "- [ ] Integrated / deployed",
        "- [ ] Behaviorally verified",
    ]
    return {"title": f"[change-proposal:{kind}] {name}", "body": "\n".join(parts)}


def _format_tool_issue(proposal: dict) -> dict:
    name = proposal.get("name") or proposal.get("slug") or "untitled tool"
    parts = [
        REVIEW_BANNER,
        "",
        _provenance_line(proposal),
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
        parts += ["", "## Raw proposal", "```", proposal["raw"].strip(), "```"]
    parts += [
        "",
        "## Operationalization state",
        "- [x] Observed / proposed",
        "- [x] Persisted as review handoff",
        "- [ ] Implemented",
        "- [ ] Integrated / deployed",
        "- [ ] Behaviorally verified",
    ]
    return {"title": f"[tool-proposal] {name}", "body": "\n".join(parts)}
