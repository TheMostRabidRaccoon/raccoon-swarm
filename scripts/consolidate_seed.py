#!/usr/bin/env python3
"""Consolidate near-duplicates in a distilled seed file.

Reads distilled_seed.json, runs each category through a single Claude call
that merges near-duplicate items and ranks by importance, writes the result
to consolidated_seed.json.
"""
from __future__ import annotations
import argparse, json, os, sys
from datetime import datetime
from pathlib import Path
import anthropic
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env"), override=True)
load_dotenv(override=True)

CATEGORY_SCHEMAS = {
    "resolved_positions": {
        "fields": ["topic", "consensus", "confidence"],
        "key": "topic",
        "max": 50,
        "guidance": "Group items whose topics describe the same underlying subject. Merge each group into ONE canonical item: keep the most specific consensus statement, take the highest confidence, list all source sessions in 'sources'. Order by importance (foundational architectural decisions first, narrow tactical positions last).",
    },
    "unresolved_questions": {
        "fields": ["question", "raised_by"],
        "key": "question",
        "max": 30,
        "guidance": "Group questions that ask the same underlying thing in different words. Merge each group into ONE canonical question: pick the most specific phrasing, sum all the 'attempts' counts, preserve original 'raised_by'. Order by how blocking each question is.",
    },
    "next_pursuits": {
        "fields": ["direction", "priority", "proposed_by"],
        "key": "direction",
        "max": 20,
        "guidance": "Group pursuits that describe the same next move. Merge each group into ONE: keep the most concrete actionable direction, take the highest priority, preserve original 'proposed_by'. Order by priority then specificity.",
    },
    "evolving_frameworks": {
        "fields": ["name", "description"],
        "key": "name",
        "max": 25,
        "guidance": "Group frameworks that describe the same mental model under different names. Merge each group into ONE: pick the most evocative name, write the most complete description (don't truncate), bump version to the count of merged sources. Order by how often the framework would be useful as a thinking tool.",
    },
}

CONSOLIDATION_SYSTEM = """You are consolidating a list of items extracted across many AI conversations. Your job: identify near-duplicates, merge each group into ONE canonical item, and rank the result by importance.

You will receive a category name, schema fields, item-specific guidance, and a JSON array of items. Each item also has a 'source_session' field tracing back to its original session.

OUTPUT: a JSON array of the consolidated items. No markdown fences, no commentary. Just JSON.

Each output item must include:
- The schema fields specified for the category
- A 'sources' field: an array of all source_session filenames that contributed to this consolidated item
- Any other fields that were standard for the category (e.g., 'attempts', 'version', 'session')

RULES:
- Merge aggressively when items describe the same underlying thing in different words.
- Do NOT merge items that have genuine semantic distinction (e.g., 'CDS Risk Ladder' and 'CDS Compliance Stack' are related but distinct frameworks; do not collapse).
- Cap the output at the max_items count specified.
- The output array order IS the importance ranking — first item = most important.
- If you discard an item entirely, that's allowed, but only if it's a true duplicate of another (its source_session goes into the keeper's sources list)."""

def consolidate_category(client, category, items, model, max_tokens):
    schema = CATEGORY_SCHEMAS[category]
    user_prompt = f"""CATEGORY: {category}
SCHEMA FIELDS: {schema['fields']}
MAX ITEMS IN OUTPUT: {schema['max']}
GUIDANCE: {schema['guidance']}

INPUT ({len(items)} items):
{json.dumps(items, indent=2)}

Return the consolidated array as JSON."""

    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=CONSOLIDATION_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    consolidated = json.loads(raw.strip())
    usage = {
        "input": getattr(msg.usage, "input_tokens", 0),
        "output": getattr(msg.usage, "output_tokens", 0),
    }
    return consolidated, usage

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--max-tokens", type=int, default=8000)
    args = ap.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2

    with open(args.input) as f:
        seed = json.load(f)

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    totals = {"input": 0, "output": 0}
    consolidated_seed = dict(seed)

    for category in CATEGORY_SCHEMAS:
        items = seed.get(category, [])
        if not items:
            continue
        print(f"[{category}] consolidating {len(items)} items...")
        try:
            result, usage = consolidate_category(client, category, items, args.model, args.max_tokens)
            consolidated_seed[category] = result
            totals["input"] += usage["input"]
            totals["output"] += usage["output"]
            print(f"  → {len(result)} items (in/out tokens: {usage['input']}/{usage['output']})")
        except Exception as e:
            print(f"  ! failed: {e}", file=sys.stderr)
            print(f"  keeping original {len(items)} items for this category", file=sys.stderr)

    consolidated_seed["last_updated"] = datetime.now().isoformat()
    consolidated_seed["session_count"] = seed.get("session_count", 0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(consolidated_seed, f, indent=2)

    print(f"\nWrote {args.output}")
    print(f"Total tokens — input: {totals['input']:,}  output: {totals['output']:,}")
    cost = totals["input"] * 3 / 1_000_000 + totals["output"] * 15 / 1_000_000
    print(f"Estimated cost: ${cost:.2f}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
