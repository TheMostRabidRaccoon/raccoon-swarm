# Evidence catalog

**The difference between "I remember this" and "I can prove this."** The
filestore (`swarm_filestore`) is the swarm's own memory; the evidence catalog
(`swarm_evidence.py`) is a separate, provenance-carrying index of *source*
material a claim can cite. A citation is `{source_id, content_hash,
chunk_index}` — if it doesn't resolve, it's a phantom, the same discipline the
filestore applies to phantom *writes*, applied to phantom *evidence*.

Status: **M1a shipped** (catalog core, read-only, synthetic-tested). Drive
ingest, citation-gap scoring, and promotion are later milestones (below).

## Source of truth

- `swarm_evidence.py` — the catalog (stdlib `sqlite3` only; no Drive API — sources are handed in, so it unit-tests with synthetic data)
- DB at `RRI_EVIDENCE_DB`, else `<RRI_STORAGE_DIR>/evidence/evidence.db`

## Three decisions baked in on day one

1. **Origin class is in the schema, not a flag.** Every source is
   `conductor-authored` / `swarm-authored` / `third-party` / `unknown`. The
   swarm's own syntheses flow into Drive, so a naive index would let it cite
   itself as independent evidence — the **citation-laundering loop**. Origin is
   what the corroboration rule keys off (`is_independent_corroborator`:
   swarm-authored never independently corroborates a swarm claim). The *rule*
   lands with citation-verification (M2); the *data* is here now.
2. **Content-hash dedup.** The real corpus is export sprawl (a Google Doc + two
   `.txt` exports of the same work), not elegant revisions. `content_hash`
   normalizes whitespace, so identical content links to one **canonical** source
   and is indexed once — search never returns the same passage three times.
3. **Read-only.** No promotion into swarm memory here. That flows through the
   human-gated `swarm_proposals` pattern later — "what enters permanent memory"
   earns the same one-gated-step treatment as "what enters the tool registry."

## M1 allowlist (locked)

The initial corpus is the **RRI Research** Drive folder, whole-document allow.
It's a research corpus (Papers 2–6, pipeline, references), owned by the
Conductor, with nothing `sharedWithMe` (no externally-authored/untrusted docs on
day one). Because `_Notes & Sessions` (swarm session output) is included, its
sources are catalogued as `swarm-authored` — so origin-classing is load-bearing
from M1a, not deferred. Personal/mixed folders (finances, health, Carry-Forward)
are **excluded**; section-level redaction is its own milestone with its own
adversarial tests, because a redaction bug ships personal data to four vendors.

## API (M1a)

```python
conn = swarm_evidence.connect()                 # opens + ensures schema
swarm_evidence.catalog_source(conn, title=..., text=..., origin=ev.CONDUCTOR,
                              external_id="drive:<id>")   # dedup + chunk + index
hits = swarm_evidence.search(conn, "governance", k=5, origins=(ev.CONDUCTOR,))
exc  = swarm_evidence.fetch(conn, source_id, chunk_index)         # cited excerpt
res  = swarm_evidence.resolve_citation(conn, source_id, hash, chunk_index)
```

- **`catalog_source`** is idempotent by `external_id` (unchanged / updated) and
  deduped by content (duplicate → linked to canonical, not re-indexed).
- **`search`** returns ranked cited excerpts (FTS5 when available, else a ranked
  substring fallback), canonical sources only, optionally origin-filtered.
- **`fetch`** returns one bounded excerpt with provenance (`heading_path`,
  offsets, origin, url) — a model reads *this*, not the whole doc.
- **`resolve_citation`** returns `resolved` / `not-found` / `stale` (source
  changed since the cite) — the foundation for M2's `citation_gap`.

## Roadmap

- **M1b** — `scripts/build_source_catalog.py`: the Drive ingest over the
  allowlisted folder (Docs/text/markdown extraction), plus `evidence_search` /
  `evidence_fetch` in the tool registry with excerpts wrapped in the
  `untrusted_content` envelope. Seed the 10 known-answer eval questions and wire
  a recall@k harness *before* trusting retrieval.
- **M2** — citation verification in the Closer: re-fetch every cite in a
  synthesis, compute `citation_gap` (parallel to `persistence_gap`); enforce the
  independent-origin corroboration rule; staleness detection on re-sync.
- **M3** — human-gated promotion (via `swarm_proposals`) of source-backed
  findings into swarm memory; contradiction surfacing (conflicts presented,
  never collapsed).
- **M4** — revision history / argument graph; immutable snapshots → bitemporal
  ("what did the swarm believe on date X, and what evidence did it have").
