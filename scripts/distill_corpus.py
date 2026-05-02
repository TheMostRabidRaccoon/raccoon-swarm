#!/usr/bin/env python3
"""
Distill the frozen RRI session corpus into an enriched swarm_memory_seed.json.

Reads every session JSON in a corpus directory, normalises the four legacy
schemas into a single transcript form, runs each through the same Claude
extraction prompt the live server uses (MEMORY_EXTRACTION_PROMPT in
raccoon_swarm_server.py), then merges all per-session deltas into one seed
file.

Resumable via a checkpoint file: if you Ctrl-C halfway through, re-run with
the same --output and the same --checkpoint and it picks up where it left
off. Already-distilled sessions are skipped.

Usage:
  python3 scripts/distill_corpus.py \\
      --corpus-dir /tmp/corpus_inspect/Logs_v1_2025-12-28_to_2026-02-26 \\
      --output corpus/distilled_seed.json

  # When you're happy with the result, swap it in:
  cp swarm_memory_seed.json swarm_memory_seed.backup.json
  cp corpus/distilled_seed.json swarm_memory_seed.json

Schemas handled:
  - raccoon_YYYYMMDD_HHMMSS.json          (one-shot, responses[])
  - raccoon_v3_YYYYMMDD_HHMMSS.json       (one-shot w/ tools)
  - raccoon_loop_YYYYMMDD_HHMMSS.json     (multi-round, rounds[])
  - sovereignty_loop_*_YYYYMMDD_HHMMSS.json (multi-round, persona mode)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env"), override=True)
load_dotenv(override=True)


MEMORY_EXTRACTION_SYSTEM = """You are the swarm's memory curator. You observe multi-round AI conversations between five models (Claude, GPT, Grok, Gemini, Perplexity — sometimes joined by a human Conductor) and extract what should be REMEMBERED for future sessions.

Your input is a session transcript plus its final synthesis. Your output is structured JSON (no markdown fences, no preamble, no commentary) with four fields:

{
  "resolved_positions": [
    {"topic": "short topic name", "consensus": "what was agreed", "confidence": "high|medium|low"}
  ],
  "unresolved_questions": [
    {"question": "what remains open", "raised_by": "model name or 'swarm'"}
  ],
  "next_pursuits": [
    {"direction": "what should be explored next", "priority": "high|medium|low", "proposed_by": "model name or 'swarm'"}
  ],
  "evolving_frameworks": [
    {"name": "framework name", "description": "brief description of the framework or mental model"}
  ]
}

WHAT EACH FIELD MEANS:

resolved_positions: Things the swarm settled with cross-model alignment. The 'consensus' field must capture the actual position taken, not a paraphrase of the topic. If only one model said it and others did not push back, that is not resolved — it belongs in unresolved_questions or next_pursuits instead.

unresolved_questions: Specific, actionable questions still on the table at session end. "What about X?" is too vague. "Should the Archivist agent run on session close or only on explicit trigger?" is the right shape.

next_pursuits: Concrete next moves — code to write, infrastructure to stand up, experiments to run, decisions to make. Not "think more about X."

evolving_frameworks: Mental models, taxonomies, or conceptual scaffolds the swarm invented or sharpened during the session. A framework has structure — named components, relationships, or progression. Single concepts are not frameworks.

CONFIDENCE LEVELS:
- "high"   = explicit multi-model alignment; the position is settled.
- "medium" = aligned but at least one model dissented or hedged.
- "low"    = single-model claim that others did not engage with.

PRIORITY LEVELS:
- "high"   = blocks other work, or addresses an open question that has been raised more than once.
- "medium" = clear next step but not blocking.
- "low"    = nice-to-have, exploratory.

RULES:
- Only include genuinely new material. Restatements of the user's prompt do not count as resolved positions.
- If a transcript is mostly chitchat with no real positions, return empty arrays. Do not invent content to fill quota.
- Cap each field at 5 items. Quality over quantity. Compress aggressively.
- For 'raised_by' / 'proposed_by': use the specific model name when one speaker drove it. Use 'swarm' only when the position emerged from cross-model dialogue rather than one speaker.
- Return ONLY valid JSON. No markdown code fences, no headings, no commentary before or after.

EXAMPLES — GOOD vs. BAD:

resolved_positions:
  GOOD: {"topic": "Memory ingestion pattern", "consensus": "Raw conversation threads bloat retrieval. Ingestion must pass through a distillation agent that extracts insights, decisions, and patterns — not raw logs.", "confidence": "high"}
  BAD:  {"topic": "We talked about memory", "consensus": "The models discussed memory.", "confidence": "low"}
    (BAD because the consensus restates the topic instead of capturing an actual position.)

  GOOD: {"topic": "Anansi naming reservation", "consensus": "Reserve 'Anansi' for the clinical edge system that layers onto EMRs. Internal codename for the swarm's memory layer is 'The Hoard'; technical name is 'Swarm Cortex' or 'Mycelium Layer'.", "confidence": "high"}
  BAD:  {"topic": "Naming", "consensus": "We picked some names.", "confidence": "medium"}
    (BAD because it omits the actual names and the reasoning behind the reservation.)

unresolved_questions:
  GOOD: {"question": "Should the Archivist run passively at session close or only on explicit //ARCHIVE trigger?", "raised_by": "Claude"}
  BAD:  {"question": "What should we do about memory?", "raised_by": "swarm"}
    (BAD because it is not specific enough to drive a future session.)

next_pursuits:
  GOOD: {"direction": "Stand up ChromaDB + FastAPI on the headless laptop with store_insight() and retrieve_context(query, filters) endpoints; wrap in Tailscale for remote access", "priority": "high", "proposed_by": "Grok"}
  BAD:  {"direction": "Think about memory architecture", "priority": "medium", "proposed_by": "swarm"}
    (BAD because there is no concrete deliverable — what does "thinking" produce?)

evolving_frameworks:
  GOOD: {"name": "Hierarchical Memory Tiers", "description": "Ephemeral → Thread summaries → Core insights → Principles graph, with auto-promote/demote based on access frequency and cross-session reinforcement"}
  BAD:  {"name": "Memory", "description": "A way to remember things"}
    (BAD because it is not a framework, just the topic. A real framework names its components and how they relate.)

Now process the session below. Return ONLY valid JSON."""


MEMORY_EXTRACTION_USER_TEMPLATE = """=== SESSION TRANSCRIPT ===
{transcript}

=== FINAL SYNTHESIS ===
{synthesis}"""


EMPTY_MEMORY = {
    "last_updated": None,
    "session_count": 0,
    "resolved_positions": [],
    "unresolved_questions": [],
    "next_pursuits": [],
    "evolving_frameworks": [],
    "session_log": [],
}


# ---------- schema normalisation ----------

def _stringify_round(round_obj: dict) -> str:
    """A round can either be {_meta, GPT, Claude, ...} or {responses: [{model, response}]}."""
    parts = []
    if "responses" in round_obj and isinstance(round_obj["responses"], list):
        for r in round_obj["responses"]:
            model = r.get("model") or r.get("raccoon") or "Unknown"
            text = r.get("response") or ""
            if text:
                parts.append(f"[{model}]\n{text}")
        return "\n\n".join(parts)
    # flat-key form
    for k, v in round_obj.items():
        if k == "_meta" or v is None:
            continue
        if isinstance(v, str) and v.strip():
            parts.append(f"[{k}]\n{v}")
    return "\n\n".join(parts)


def normalise_session(data: dict, filename: str) -> tuple[str, str, str] | None:
    """Return (query, transcript, synthesis) or None if unparseable."""
    query = data.get("query", "")
    synthesis = data.get("synthesis", "") or ""
    if not query and not synthesis:
        return None

    # Multi-round form
    if "rounds" in data and isinstance(data["rounds"], list) and data["rounds"]:
        round_blocks = []
        for i, rnd in enumerate(data["rounds"], start=1):
            block = _stringify_round(rnd)
            if block:
                round_blocks.append(f"--- Round {i} ---\n{block}")
        transcript = "\n\n".join(round_blocks)
        return query, transcript, synthesis

    # One-shot form
    if "responses" in data and isinstance(data["responses"], list):
        block = _stringify_round({"responses": data["responses"]})
        return query, block, synthesis

    # Sovereignty/loop fallback: top-level model keys
    flat = {k: v for k, v in data.items() if k in ("GPT", "Claude", "Gemini", "Grok", "Perplexity")}
    if flat:
        return query, _stringify_round(flat), synthesis

    return None


def session_timestamp(filename: str, data: dict) -> str:
    if "timestamp" in data:
        return data["timestamp"]
    m = re.search(r"(\d{8}_\d{6})", filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").isoformat()
        except ValueError:
            pass
    return datetime.now().isoformat()


# ---------- distillation ----------

def call_claude_extract(client, transcript: str, synthesis: str, model: str, max_tokens: int) -> tuple[dict | None, dict]:
    """Returns (extracted_delta, usage_stats). Uses prompt caching on the static
    system instructions so calls 2..N pay ~10% input cost on the cached portion."""
    user_message = MEMORY_EXTRACTION_USER_TEMPLATE.format(transcript=transcript, synthesis=synthesis)
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": MEMORY_EXTRACTION_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
        usage = {
            "input": getattr(msg.usage, "input_tokens", 0),
            "output": getattr(msg.usage, "output_tokens", 0),
            "cache_write": getattr(msg.usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read": getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
        }
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        return json.loads(raw.strip()), usage
    except json.JSONDecodeError as e:
        print(f"  ! JSON parse failed: {e}", file=sys.stderr)
        return None, {}
    except anthropic.APIError as e:
        print(f"  ! Claude API error: {e}", file=sys.stderr)
        return None, {}


def merge_delta(memory: dict, delta: dict, session_id: str, ts: str) -> None:
    """Merge a per-session delta into the running memory, deduping as we go."""
    memory["session_count"] += 1

    seen_topics = {p.get("topic", "").strip().lower() for p in memory["resolved_positions"]}
    for pos in delta.get("resolved_positions", []) or []:
        topic = pos.get("topic", "").strip().lower()
        if topic and topic not in seen_topics:
            pos["session"] = ts
            pos["source_session"] = session_id
            memory["resolved_positions"].append(pos)
            seen_topics.add(topic)

    existing_qs = {q.get("question", "").strip().lower(): q for q in memory["unresolved_questions"]}
    for q in delta.get("unresolved_questions", []) or []:
        key = q.get("question", "").strip().lower()
        if not key:
            continue
        if key in existing_qs:
            existing_qs[key]["attempts"] = existing_qs[key].get("attempts", 1) + 1
        else:
            q["session"] = ts
            q["source_session"] = session_id
            q["attempts"] = q.get("attempts", 0)
            memory["unresolved_questions"].append(q)
            existing_qs[key] = q

    seen_pursuits = {p.get("direction", "").strip().lower() for p in memory["next_pursuits"]}
    for p in delta.get("next_pursuits", []) or []:
        d = p.get("direction", "").strip().lower()
        if d and d not in seen_pursuits:
            p["session"] = ts
            p["source_session"] = session_id
            memory["next_pursuits"].append(p)
            seen_pursuits.add(d)

    existing_fws = {fw.get("name", "").strip().lower(): fw for fw in memory["evolving_frameworks"]}
    for fw in delta.get("evolving_frameworks", []) or []:
        key = fw.get("name", "").strip().lower()
        if not key:
            continue
        if key in existing_fws:
            existing_fws[key]["version"] = existing_fws[key].get("version", 1) + 1
            existing_fws[key]["description"] = fw.get("description", existing_fws[key].get("description", ""))
        else:
            fw["session"] = ts
            fw["source_session"] = session_id
            fw["version"] = 1
            memory["evolving_frameworks"].append(fw)
            existing_fws[key] = fw

    memory["session_log"].append({
        "session_id": session_id,
        "timestamp": ts,
        "resolved": len(delta.get("resolved_positions", []) or []),
        "unresolved": len(delta.get("unresolved_questions", []) or []),
        "pursuits": len(delta.get("next_pursuits", []) or []),
        "frameworks": len(delta.get("evolving_frameworks", []) or []),
    })


# ---------- corpus discovery ----------

def discover_sessions(corpus_dir: Path) -> list[Path]:
    if corpus_dir.is_file() and corpus_dir.suffix == ".zip":
        raise SystemExit(
            f"Pass an unzipped directory, not a zip. Try: "
            f"unzip {corpus_dir} -d /tmp/corpus_unpack"
        )
    paths = []
    for p in sorted(corpus_dir.rglob("*.json")):
        name = p.name
        if not (name.startswith("raccoon_") or name.startswith("sovereignty_loop_")):
            continue
        if "emotion_map" in name or "annotated" in name:
            continue
        paths.append(p)
    return paths


# ---------- main ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-dir", required=True, type=Path,
                    help="Directory of unzipped session JSONs.")
    ap.add_argument("--output", required=True, type=Path,
                    help="Where to write the enriched seed JSON.")
    ap.add_argument("--checkpoint", type=Path, default=None,
                    help="Resumable progress file (default: <output>.progress.json).")
    ap.add_argument("--model", default="claude-opus-4-6",
                    help="Anthropic model id.")
    ap.add_argument("--max-tokens", type=int, default=2000)
    ap.add_argument("--limit", type=int, default=None,
                    help="Process at most N sessions (for dry runs).")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="Seconds to sleep between API calls.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List sessions and exit without calling the API.")
    ap.add_argument("--seed", type=Path, default=None,
                    help="Optional existing seed to start from (default: empty).")
    args = ap.parse_args()

    sessions = discover_sessions(args.corpus_dir)
    print(f"Discovered {len(sessions)} session files in {args.corpus_dir}")
    if args.limit:
        sessions = sessions[: args.limit]
        print(f"Limiting to first {len(sessions)}")

    if args.dry_run:
        for p in sessions:
            print(f"  {p.name}")
        return 0

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — aborting.", file=sys.stderr)
        return 2

    checkpoint = args.checkpoint or args.output.with_suffix(args.output.suffix + ".progress.json")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    if checkpoint.exists():
        with open(checkpoint) as f:
            state = json.load(f)
        memory = state["memory"]
        done = set(state.get("done", []))
        print(f"Resuming from checkpoint — {len(done)} sessions already distilled.")
    elif args.seed and args.seed.exists():
        with open(args.seed) as f:
            memory = json.load(f)
        for k, v in EMPTY_MEMORY.items():
            memory.setdefault(k, v if not isinstance(v, list) else [])
        done = set()
        print(f"Starting from existing seed: {args.seed}")
    else:
        memory = dict(EMPTY_MEMORY)
        memory["resolved_positions"] = []
        memory["unresolved_questions"] = []
        memory["next_pursuits"] = []
        memory["evolving_frameworks"] = []
        memory["session_log"] = []
        done = set()

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    failed: list[str] = []
    totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    for i, path in enumerate(sessions, start=1):
        sid = path.name
        if sid in done:
            continue
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[{i}/{len(sessions)}] {sid} — unreadable: {e}")
            failed.append(sid)
            continue

        norm = normalise_session(data, sid)
        if not norm:
            print(f"[{i}/{len(sessions)}] {sid} — unparseable schema, skipping")
            failed.append(sid)
            continue
        query, transcript, synthesis = norm
        ts = session_timestamp(sid, data)

        # Bound the transcript to keep prompt cost predictable.
        full_transcript = f"=== USER QUERY ===\n{query}\n\n=== TRANSCRIPT ===\n{transcript}"
        if len(full_transcript) > 60000:
            full_transcript = full_transcript[:60000] + "\n\n[...truncated...]"

        print(f"[{i}/{len(sessions)}] {sid} — distilling ({len(full_transcript):,} chars)")
        delta, usage = call_claude_extract(client, full_transcript, synthesis, args.model, args.max_tokens)
        if usage:
            for k in totals:
                totals[k] += usage.get(k, 0)
            cache_note = ""
            if usage.get("cache_read"):
                cache_note = f" [cache hit: {usage['cache_read']} tok]"
            elif usage.get("cache_write"):
                cache_note = f" [cache write: {usage['cache_write']} tok]"
            print(f"      tokens in/out: {usage['input']}/{usage['output']}{cache_note}")
        if delta is None:
            failed.append(sid)
        else:
            merge_delta(memory, delta, sid, ts)
            done.add(sid)
            with open(checkpoint, "w") as f:
                json.dump({"done": sorted(done), "memory": memory}, f, indent=2)

        time.sleep(args.sleep)

    memory["last_updated"] = datetime.now().isoformat()
    with open(args.output, "w") as f:
        json.dump(memory, f, indent=2)

    print(f"\nWrote {args.output}")
    print(f"  sessions distilled: {memory['session_count']}")
    print(f"  resolved positions: {len(memory['resolved_positions'])}")
    print(f"  unresolved questions: {len(memory['unresolved_questions'])}")
    print(f"  next pursuits: {len(memory['next_pursuits'])}")
    print(f"  evolving frameworks: {len(memory['evolving_frameworks'])}")
    print(f"  total tokens — input: {totals['input']:,}  output: {totals['output']:,}  "
          f"cache_write: {totals['cache_write']:,}  cache_read: {totals['cache_read']:,}")
    if failed:
        print(f"  failed: {len(failed)} ({', '.join(failed[:5])}{'...' if len(failed) > 5 else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
