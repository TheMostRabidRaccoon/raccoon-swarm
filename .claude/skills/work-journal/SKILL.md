---
name: work-journal
description: Append task-completion-gated journal entries to one of six pipeline journals (applications, paper6, swarm_ops, content, consulting) with dual-write to Google Docs + local file, or to a seventh personal journal that is local-only. Invoke after finishing a substantive unit of work — something shipped, decided, or discovered. Do not invoke for chatter, exploration, or paused tasks.
---

# Work Journal

Keeps a cross-session running log across RRI pipelines so Claude can pick up tomorrow where today left off, without dragging the whole log into context.

## Pipelines

Seven pipelines. Routing and privacy are defined in `pipelines.json` — always load that file before writing.

| Pipeline      | Privacy      | Drive |
|---------------|--------------|-------|
| applications  | work         | yes   |
| paper6        | work         | yes   |
| swarm_ops     | work         | yes   |
| content       | work         | yes   |
| consulting    | work         | yes   |
| personal      | **local-only** | **NO** |

The `personal` journal is **never** written to Google Drive. This is a blocking privacy invariant — see `tests/privacy-check.sh`.

## Gating — is this entry worth writing?

Before invoking this skill, check: **was anything shipped, decided, or discovered?**

- **Shipped** — code merged, doc finalized, deploy done, email sent, deliverable handed off
- **Decided** — architectural choice made, scope cut, tool picked, path committed to
- **Discovered** — non-obvious finding, failed approach ruled out, user insight, blocker root-caused

If none of the above → skip. Do not write "discussed X" or "explored Y" entries. No clutter.

If ambiguous → ask the user once: "Should I journal this?"

## Routing — which pipeline?

Pipeline names are **lowercase-only** — never `Personal`, `Paper6`, etc. On macOS's case-insensitive filesystem a capitalized variant would silently collide with the canonical filename and bypass the privacy checks. If you ever see an uppercase draft or marker in `.claude/state/`, treat it as a bug and surface it.

Decide by cue, in this order:

1. **If the user names the pipeline explicitly** ("journal this to paper6") — use it.
2. **If the pipeline is obvious from context** — use it. Cues:
   - Working directory is `raccoon-swarm` → `swarm_ops`
   - Conversation about a paper/manuscript draft → `paper6`
   - Conversation about a job application, interview, take-home, or recruiter → `applications`
   - Conversation about a blog post, video, essay, tweet, public writing → `content`
   - Conversation about a named paying client / contract / proposal → `consulting`
   - Anything non-work: health, family, relationships, venting, a personal project with no commercial intent → `personal`
3. **If cues conflict** (e.g. Paper 6 research inside the swarm repo — they overlap) — ask once: "This feels like both `paper6` and `swarm_ops`. Which do you want it indexed under?"
4. **If you can't tell whether it's work or personal** — always ask. Never guess across that boundary. A false-work entry leaks; a false-personal entry just means the Doc is missing it, which is recoverable.

## Entry format

Append to the draft file for that pipeline: `.claude/state/journal-draft-<pipeline>.md`

```
## <YYYY-MM-DD HH:MM> — <one-line summary>

**Kind:** shipped | decided | discovered
**Pipeline:** <pipeline>

<2-6 sentence entry. What changed, why it matters, next step if any.>

---
```

Keep entries short. The log's value is in signal, not volume.

## Write flow

1. Load `pipelines.json` to resolve pipeline → `local_only` flag + Doc ID + local path.
2. **Privacy gate:** if `local_only: true`, never call any Google Docs / Drive MCP tool for this entry. Local append only.
3. **Content-level privacy pre-check** (work pipelines only): before appending to a work-pipeline draft, re-read the entry you just drafted. Ask yourself: *is there anything in this entry that reads as personal — venting about a named person, medical/health detail, family content, anything the user wouldn't want in a Google Doc?* If yes, surface it once: "This `<pipeline>` entry mentions \<thing\>. Route to `personal` instead, or keep as `<pipeline>`?" Do not flush to the work pipeline by default when in doubt. Pipeline routing is enforced by the hook; content classification is on you.
4. Append entry to `.claude/state/journal-draft-<pipeline>.md` (lowercase pipeline name — see Routing).
5. The `SessionEnd` hook (`.claude/hooks/journal-flush.sh`) will flush drafts to their final destinations at session end.

Writing to the draft file is the Skill's job. Flushing is the hook's job. Claude does not call the hook directly.

## Read-back — don't bloat context

When the user asks "what did I do on paper6 this week?":

1. Read the **local** journal at `journals/<pipeline>.md` using `Grep` or `Read` with `offset`/`limit` — last N entries only.
2. Do **not** fetch the full Google Doc unless the local file is missing.
3. Do **not** dump the whole journal into the response. Summarize.

## MCP tool detection (work pipelines only)

The user runs this on Mac with Claude Desktop's existing MCP config. Before the first dual-write of a session:

1. Check whether a Google Docs write tool is available (search available tools for "docs append", "google docs", etc.).
2. If present — use it for all non-personal pipelines.
3. If absent — continue local-only, and tell the user once: "Google Docs MCP not detected. Work entries are local-only until an MCP is configured (suggest: `isaacphi/mcp-gdrive`)."

Never install an MCP server autonomously. The user drives that.

## Draining pending drive-syncs at session start

The `SessionStart` hook (`.claude/hooks/journal-sync-startup.sh`) scans for `pending-drive-sync-<pipeline>.md` markers left by the previous session's flush and emits a banner into the session context listing each pending pipeline and its Doc ID.

When you see that banner:

1. **Check MCP availability first.** If no Google Docs append tool is available, tell the user once ("Google Docs MCP not detected — markers left for next session") and **stop**. Do not delete any markers.
2. **For each pending pipeline in the banner:**
   - Read the marker file (the banner lists the full path).
   - **Strip the first line** — every marker begins with a self-describing HTML comment header (`<!-- work-journal drive-sync marker for <pipeline> — … -->`). Do not include it in the Doc append; it's metadata for humans and future Claudes, not part of the entry.
   - Append the remaining content to the Google Doc (Doc ID listed in the banner) using the MCP append tool.
   - **Only after the MCP call succeeds**, delete the marker with `rm`.
   - If the MCP call fails, leave the marker in place and report the error to the user — do not retry blindly.
3. **Never drain a `personal` marker.** The hook exits non-zero if one exists; if you somehow see a `pending-drive-sync-personal.md`, surface it to the user, do not push it to any MCP, and let the user inspect it before deletion.

Draining is additive — the Doc keeps growing. No deduplication yet; if you push a marker twice, you'll get duplicate entries in the Doc.

## Out of scope for this pass

- Headless/Lenovo service-account auth — Mac + interactive OAuth only.
- Auto-summarization of old entries — revisit if journals exceed ~500 lines.
- SwarmDaemon autonomous journaling — revisit when that ships.
