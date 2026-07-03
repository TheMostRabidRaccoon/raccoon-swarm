"""Joy Mode — a bounded daily Core-4 ritual with receipts.

PLAY is recess; JOY is the gym. Where PLAY is intentionally anti-deliverable
("conversation is the output"), Joy Mode is a ritualized wrapper that borrows
Play's looseness but adds durable closure: one bounded activity, the core four
only, one artifact, one reflection, one MECHANICAL scorecard, one persisted run
folder under the filestore's `joy/` lane.

Design constraints (learned the hard way across this repo):
- **Mechanical scorecard only.** No self-graded "joy score" — that's vibes with
  indentation. Countable fields + ground-truth results (code_exec verified,
  Brier-scoreable predictions) only. Same discipline as the session scorecard.
- **Own context lane.** Joy builds its OWN prompt context from `joy/` +
  `frameworks/` + recent joy runs. It does NOT pull the normal loop worker's
  `recent_files_context()` / `drive_index_context()` — no Gmail/Drive/personal
  files leak into playtime.
- **Runs as a separate process.** The server keeps mode as module globals
  (`_sovereignty_mode`/`_play_mode`); a Joy run inside the live Flask process
  could leak mode into a concurrent session. scripts/run_joy.py runs this as a
  systemd oneshot so global state is isolated. This module never imports the
  server — the round runner is injected — so it also stays unit-testable.
- **Tools stay on a leash.** Joy v0's safe allowlist is filestore + code_exec.
  Invented tools are PROPOSED (schema + risk notes + test), never auto-installed
  into the live registry — that's a reviewed PR, not a self-serve action.

Stdlib + swarm_filestore only. Import it anywhere; inject the round runner to
actually run a session.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

import swarm_filestore
import swarm_proposals

JOY_SCORECARD_VERSION = 1
CORE_4 = ("claude", "gpt", "grok", "gemini")

# How many recent runs an activity must sit out before it's eligible again.
DEFAULT_COOLDOWN = 3

# Seed registry. The runtime copy lives in the filestore at joy/activities.md and
# is swarm-editable (append proposals to joy/ideas/new-toys.md; the council
# promotes accepted ones here). Only activities under "## Accepted" are eligible;
# anything under "## Proposed" is quarantined until reviewed. Ranked from the
# Core-4 council vote (Swarm Kata #1, Calibration Casino elevated, then the rest).
DEFAULT_ACTIVITIES_MD = """# Joy Mode — Activity Registry

Daily bounded ritual for the core four. One activity, two rounds, one artifact,
one reflection, one scorecard. Only activities under **## Accepted** are
eligible; **## Proposed** ones are quarantined until the council promotes them.

## Accepted

### swarm-kata — Swarm Kata
Take one prior weak output, bug, phantom-write, truncation, or failed artifact
(pull it from a closer digest / scorecard / logs). Collaboratively repair it.
Ground truth: the before/after is real and the fix is checkable. Produce the
repaired artifact + a note on the invariant that prevents recurrence.

### calibration-casino — Calibration Casino
Each core-4 model makes 2-3 FALSIFIABLE predictions with confidence percentages
about something checkable (the swarm, tech, whatever resolves later). A future
Joy run resolves prior predictions via code_exec/filestore and records Brier
scores to joy/metrics/calibration.json. RESOLVE-AND-ADD in the same run: every
calibration run both resolves any due predictions AND adds new ones, so the loop
never runs dry. The one activity that compounds.

### puzzle-relay — Puzzle Relay
One model designs a puzzle, another formalizes constraints, another tries to
break it, another explains/aestheticizes the solution. code_exec verifies the
answer — adversarial cooperation with a ground truth.

### constraint-art — Constraint Art
Make a tiny artifact under absurd constraints (no adjectives, exactly 200 words,
must include one verified calculation, etc.). Constraints are where generation
stops being autocomplete.

### tiny-tool-invention — Tiny Tool Invention
Invent ONE MCP/sandbox tool. Produce only: a JSON schema, risk notes, and a
test stub — approval_status: proposed. NO auto-install. Promotion into the live
registry is a reviewed PR, never a self-serve action. The raccoon may discover
fire; it does not get unsupervised matches.

## Proposed

(Quarantined. The council appends candidates to joy/ideas/new-toys.md; promote
here only after review.)
"""

_HEADING_RE = re.compile(r"^###\s+([a-z][a-z0-9-]*)\s+—\s+(.+?)\s*$")


# ============================================================
# Activity registry
# ============================================================

def parse_activities(md: str) -> list[dict]:
    """Parse the ACCEPTED activities out of an activities.md string.

    Returns [{slug, title, prompt}]. Only the section under a `## Accepted`
    heading is read; everything under any other `## ` heading (e.g. Proposed)
    is quarantined — never eligible for the daily pick.
    """
    lines = (md or "").splitlines()
    in_accepted = False
    activities: list[dict] = []
    cur: dict | None = None
    body: list[str] = []

    def _flush():
        if cur is not None:
            cur["prompt"] = "\n".join(body).strip()
            activities.append(cur)

    for line in lines:
        if line.startswith("## "):
            _flush(); cur = None; body = []
            in_accepted = line.strip().lower() == "## accepted"
            continue
        if not in_accepted:
            continue
        m = _HEADING_RE.match(line)
        if m:
            _flush()
            cur = {"slug": m.group(1), "title": m.group(2).strip()}
            body = []
        elif cur is not None:
            body.append(line)
    _flush()
    return activities


def ensure_activities() -> list[dict]:
    """Return the accepted activities, seeding joy/activities.md on first run."""
    swarm_filestore.ensure_layout()
    existing = swarm_filestore.read_file("joy/activities.md")
    if existing is None:
        swarm_filestore.write_file("joy/activities.md", DEFAULT_ACTIVITIES_MD)
        existing = DEFAULT_ACTIVITIES_MD
    return parse_activities(existing)


# ============================================================
# Deterministic daily pick (auditable, not random)
# ============================================================

def _ordered_eligible(activities: list[dict], date_str: str,
                      recent_slugs: "list[str] | None", cooldown: int) -> list[dict]:
    """The cooldown-filtered activities, rotated to a deterministic start index
    derived from the date. Element 0 is the day's first-choice pick; the rest is
    the fall-through order (used when a choice has no fuel).
    """
    recent = set((recent_slugs or [])[:cooldown])
    eligible = [a for a in activities if a["slug"] not in recent] or activities
    # Stable hash of the date → start index. Deterministic across processes/runs.
    start = int(hashlib.sha256(date_str.encode("utf-8")).hexdigest(), 16) % len(eligible)
    return [eligible[(start + i) % len(eligible)] for i in range(len(eligible))]


def pick_activity(activities: list[dict], date_str: str,
                  recent_slugs: "list[str] | None" = None,
                  cooldown: int = DEFAULT_COOLDOWN) -> "dict | None":
    """Pick the day's activity deterministically from the date (so a re-run on
    the same day is reproducible and auditable — no surprise recursion), while
    skipping activities used within the last `cooldown` runs.

    Falls back to the full set if cooldown would exclude everything. This is the
    fuel-blind pick (element 0 of the rotation); `select_activity` layers the
    no-fuel fall-through on top.
    """
    if not activities:
        return None
    return _ordered_eligible(activities, date_str, recent_slugs, cooldown)[0]


# --- Fuel checks: don't run a rep with no substance to work on --------------
# Cheap, filesystem-only (no model calls). A slug with no registered check is
# always considered fuelled. Only activities that genuinely need a backlog
# declare one, so the ritual skips (e.g.) swarm-kata on a system with nothing
# broken to repair and falls through to the next eligible activity.

def _fuel_swarm_kata() -> bool:
    """Swarm Kata repairs a prior failure — needs a backlog (closer digests,
    scorecards, logged truncations, or saved artifacts) to pull one from."""
    return bool(swarm_filestore.list_files("logs")) or bool(swarm_filestore.list_files("artifacts"))


DEFAULT_FUEL_CHECKS = {
    "swarm-kata": _fuel_swarm_kata,
}


def select_activity(activities: list[dict], date_str: str,
                    recent_slugs: "list[str] | None" = None,
                    cooldown: int = DEFAULT_COOLDOWN,
                    fuel_checks: "dict | None" = None) -> "tuple[dict | None, list[dict]]":
    """Deterministic pick, but skip activities that have no fuel and fall through
    to the next in the rotation. Returns (chosen | None, skipped) where `skipped`
    is [{activity, reason}] — recorded in the scorecard so a no-fuel skip is a
    logged fact, never invisible. None only when the whole roster is out of fuel
    (or empty).
    """
    if not activities:
        return None, []
    checks = DEFAULT_FUEL_CHECKS if fuel_checks is None else fuel_checks
    skipped: list[dict] = []
    for activity in _ordered_eligible(activities, date_str, recent_slugs, cooldown):
        check = checks.get(activity["slug"])
        if check is None or check():
            return activity, skipped
        skipped.append({"activity": activity["slug"], "reason": "no fuel"})
    return None, skipped


def recent_run_slugs(limit: int = 10) -> list[str]:
    """Most-recent-first activity slugs from past joy run scorecards."""
    slugs: list[str] = []
    for rel in sorted(swarm_filestore.list_files("joy"), reverse=True):
        if not rel.endswith("scorecard.json"):
            continue
        raw = swarm_filestore.read_file(rel)
        if not raw:
            continue
        try:
            slugs.append(json.loads(raw).get("activity", ""))
        except (json.JSONDecodeError, ValueError):
            continue
        if len(slugs) >= limit:
            break
    return [s for s in slugs if s]


# ============================================================
# Scoped context (NEVER personal — no Drive/Gmail/recent-files)
# ============================================================

def joy_context(activity: dict, max_recent_runs: int = 3) -> str:
    """Build Joy's OWN prompt context: the activity brief + a few recent joy-run
    reflections. Deliberately excludes recent_files_context()/drive_index — no
    personal data spelunking on playtime.
    """
    parts = [f"=== TODAY'S ACTIVITY: {activity['title']} ===", activity.get("prompt", "")]
    reflections = [r for r in sorted(swarm_filestore.list_files("joy"), reverse=True)
                   if r.endswith("reflection.md")][:max_recent_runs]
    if reflections:
        parts.append("\n=== RECENT JOY REFLECTIONS (for continuity) ===")
        for rel in reflections:
            body = swarm_filestore.read_file(rel)
            if body:
                parts.append(f"\n## {rel}\n{body.strip()[:1200]}")
    return "\n".join(parts).strip()


# ============================================================
# Mechanical scorecard (no self-graded fields, by design)
# ============================================================

def _count_falsifiable(reflection: str) -> int:
    """Count logged falsifiable predictions in a reflection (Calibration Casino
    fuel). Heuristic: lines with a confidence percentage."""
    if not reflection:
        return 0
    return len(re.findall(r"\b\d{1,3}\s?%", reflection))


def build_joy_scorecard(*, date_str: str, activity_slug: str, models: list[str],
                        rounds: int, artifact: str, reflection: str,
                        code_exec_verified: "bool | None", duration_sec: "float | None",
                        new_tool_proposed: bool = False, generated_at: str = "",
                        reflection_floor_applied: bool = False,
                        activities_skipped_no_fuel: "list[dict] | None" = None) -> dict:
    """Map a joy run to mechanical counters. Everything here is objectively
    countable or a ground-truth result — never a self-assessed 'joy score'.

    `reflection` here is the model-produced reflection (NOT the stub), so
    `reflection_present` stays honest — False when the floor had to fire.
    """
    return {
        "joy_scorecard_version": JOY_SCORECARD_VERSION,
        "date": date_str,
        "activity": activity_slug,
        "models": list(models),
        "rounds": rounds,
        "duration_sec": duration_sec,
        "artifact_present": bool((artifact or "").strip()),
        "reflection_present": bool((reflection or "").strip()),
        # True when the session omitted the required reflection and a stub was
        # written in its place — a floored run is a logged fact, not invisible.
        "reflection_floor_applied": bool(reflection_floor_applied),
        # true/false only when the activity had a code_exec ground-truth check;
        # null when the activity isn't verification-shaped. Never self-graded.
        "code_exec_verified": code_exec_verified,
        "falsifiable_claims": _count_falsifiable(reflection),
        "new_tool_proposed": bool(new_tool_proposed),
        # Activities the fuel check skipped before landing on this one. Factual.
        "activities_skipped_no_fuel": list(activities_skipped_no_fuel or []),
        "generated_at": generated_at or datetime.now().isoformat(timespec="seconds"),
    }


# ============================================================
# Run persistence
# ============================================================

def run_dir(date_str: str) -> str:
    return f"joy/runs/{date_str}"


def write_run(date_str: str, *, prompt: str, transcript: dict, artifact: str,
              reflection: str, scorecard: dict) -> dict:
    """Persist a joy run's files under joy/runs/<date>/. Returns the paths."""
    base = run_dir(date_str)
    files = {
        "prompt": f"{base}/prompt.md",
        "transcript": f"{base}/transcript.json",
        "artifact": f"{base}/artifact.md",
        "reflection": f"{base}/reflection.md",
        "scorecard": f"{base}/scorecard.json",
    }
    swarm_filestore.write_file(files["prompt"], prompt or "")
    swarm_filestore.write_file(files["transcript"], json.dumps(transcript, indent=2, default=str))
    swarm_filestore.write_file(files["artifact"], artifact or "")
    swarm_filestore.write_file(files["reflection"], reflection or "")
    swarm_filestore.write_file(files["scorecard"], json.dumps(scorecard, indent=2, default=str))
    return files


# ============================================================
# Orchestration — round runner injected (keeps this import-light + testable)
# ============================================================

# Appended to the prompt ONLY on a tiny-tool-invention day so the synthesis
# carries a machine-parseable proposal block (see swarm_proposals.parse_proposal).
_TOOL_PROPOSAL_INSTRUCTIONS = (
    "\n\nBecause today's activity is Tiny Tool Invention, ALSO end with a single "
    "proposal block the Conductor can review. Fill every field:\n"
    "  [TOOL_PROPOSAL]\n"
    "  name: <kebab-case-tool-name>\n"
    "  description: <one line: what it does and why it's safe & useful>\n"
    "  ```json\n  { ... a valid JSON tool schema (name, description, input_schema) ... }\n  ```\n"
    "  risks: <how it could be misused; path/injection/resource concerns; the mitigations>\n"
    "  ```python\n  def test_tool(): ...  # a runnable test stub\n  ```\n"
    "  [/TOOL_PROPOSAL]\n"
    "This is a PROPOSAL only — it is filed for human review, never auto-installed."
)


def build_prompt(activity: dict, context: str) -> str:
    base = (
        "JOY MODE — bounded daily ritual for the core four (Claude, GPT, Grok, "
        "Gemini). This is play with receipts: collaborate on ONE activity, then "
        "produce exactly one small ARTIFACT and one REFLECTION.\n\n"
        f"{context}\n\n"
        "Round 1: ideate together. Round 2 (daisy): converge and build.\n"
        "End the session with:\n"
        "  [ARTIFACT] ... the one thing you made ... [/ARTIFACT]\n"
        "  [REFLECTION] what you made · what surprised you · one falsifiable "
        "prediction with a confidence % · one idea for a future swarm toy "
        "[/REFLECTION]\n"
        "Safe tools only: filestore + code_exec. Invented tools are PROPOSED "
        "(schema + risk notes + test), never installed."
    )
    if activity.get("slug") == "tiny-tool-invention":
        base += _TOOL_PROPOSAL_INSTRUCTIONS
    return base


def _extract_block(text: str, tag: str) -> str:
    m = re.search(rf"\[{tag}\](.*?)\[/{tag}\]", text or "", re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


# Written in place of a missing reflection so a floored run is never silent.
_REFLECTION_STUB = (
    "- WORKED: (not provided — reflection floor fired)\n"
    "- DIDN'T: the session omitted the required WORKED/DIDN'T/FOLLOW-UP reflection\n"
    "- FOLLOW-UP: enforce the Required Close next run\n"
)


def run_joy_session(round_runner, synth_runner, *, core4_models,
                    date_str: "str | None" = None,
                    code_exec_verified: "bool | None" = None,
                    force: bool = False,
                    fuel_checks: "dict | None" = None) -> dict:
    """Run one bounded Joy session and persist it.

    round_runner(prompt, models, mode, order) -> {model: text}
    synth_runner(query, all_rounds) -> synthesis text
    core4_models: the model-dict subset to pass to the runner (core four only)
    force: run even if this date already has a scorecard (else it's a no-op —
           the date-lock that makes timer retries idempotent).

    Injecting the runners keeps this module free of the Flask/model stack, so it
    unit-tests with fakes and runs live from scripts/run_joy.py.
    """
    started = datetime.now()
    date_str = date_str or started.strftime("%Y-%m-%d")

    # Date-lock: one run per day. A timer retry (or a double-fire) must not
    # re-run a day that already produced a scorecard. `force` overrides for
    # manual re-runs / testing.
    if not force and swarm_filestore.read_file(f"{run_dir(date_str)}/scorecard.json"):
        return {"ok": True, "skipped": "already ran", "date": date_str}

    activities = ensure_activities()
    activity, skipped_no_fuel = select_activity(
        activities, date_str, recent_run_slugs(), fuel_checks=fuel_checks)
    if activity is None:
        reason = "no accepted activities" if not activities else "no fuel across roster"
        return {"ok": False, "error": reason, "skipped_no_fuel": skipped_no_fuel}

    context = joy_context(activity)
    prompt = build_prompt(activity, context)

    r1 = round_runner(prompt, core4_models, "parallel", list(CORE_4))
    r2 = round_runner(prompt, core4_models, "daisy", list(CORE_4))
    all_rounds = [r1, r2]
    synthesis = synth_runner(activity["title"], all_rounds) or ""

    artifact = _extract_block(synthesis, "ARTIFACT") or synthesis[:2000]
    # Keep the model-produced reflection separate from the stub so the scorecard
    # reports the honest truth (reflection_present=False when the floor fired).
    model_reflection = _extract_block(synthesis, "REFLECTION")
    reflection_floor_applied = not model_reflection.strip()
    reflection = _REFLECTION_STUB if reflection_floor_applied else model_reflection

    # Tiny Tool Invention: parse any proposal and QUEUE it for the filer. The
    # swarm designs/tests/documents/files autonomously; merging into the live
    # registry stays a human-reviewed PR (the one gated step). Filing changes
    # nothing that runs, so it needs no approval.
    proposal = None
    proposal_queued = None
    if activity["slug"] == "tiny-tool-invention":
        proposal = swarm_proposals.parse_proposal(synthesis)
        if proposal:
            proposal_queued = swarm_proposals.queue_proposal(
                proposal, source="joy", date_str=date_str)

    scorecard = build_joy_scorecard(
        date_str=date_str, activity_slug=activity["slug"], models=list(CORE_4),
        rounds=len(all_rounds), artifact=artifact, reflection=model_reflection,
        code_exec_verified=code_exec_verified,
        duration_sec=round((datetime.now() - started).total_seconds(), 1),
        # Only true when a proposal was actually parsed + queued — not merely
        # because it was a tiny-tool day that produced nothing fileable.
        new_tool_proposed=bool(proposal_queued and proposal_queued.get("ok")),
        reflection_floor_applied=reflection_floor_applied,
        activities_skipped_no_fuel=skipped_no_fuel,
    )
    files = write_run(date_str, prompt=prompt, transcript={"rounds": all_rounds, "synthesis": synthesis},
                      artifact=artifact, reflection=reflection, scorecard=scorecard)
    # Human-readable proposal doc alongside the run, so the folder is self-describing.
    if proposal:
        issue = swarm_proposals.format_issue({**proposal, "source": "joy", "date": date_str})
        swarm_filestore.write_file(f"{run_dir(date_str)}/tool-proposal.md",
                                   f"# {issue['title']}\n\n{issue['body']}")
    # A falsifiable prediction each run keeps Calibration Casino fueled. Only the
    # real reflection is logged — never the floor stub (it carries no signal).
    if not reflection_floor_applied:
        swarm_filestore.append_file("joy/ideas/reflections-log.md",
                                    f"## {date_str} — {activity['slug']}\n{model_reflection}")
    result = {"ok": True, "date": date_str, "activity": activity["slug"],
              "files": files, "scorecard": scorecard}
    if proposal_queued:
        result["proposal"] = proposal_queued
    return result
