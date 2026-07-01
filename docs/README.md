# RRI Raccoon Swarm — docs index

**Where do I look?** Start here.

| If you want to know… | Read |
|----------------------|------|
| What the pieces are and how a request flows through them | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| How it's deployed, monitored, recovered, and kept safe | [`OPERATIONS.md`](OPERATIONS.md) |
| How to change this repo (humans **or** models) without creating ghosts | [`../CONTRIBUTING.md`](../CONTRIBUTING.md) |

These three are the entry layer. For subsystem detail, the `stack/` notes go deeper:

- [`stack/auth.md`](stack/auth.md) — login gate, tokens, **deployment profiles** table
- [`stack/deploy.md`](stack/deploy.md) — hosting specifics (Railway/Procfile)
- [`stack/storage.md`](stack/storage.md) — filestore layout on the volume
- [`stack/models.md`](stack/models.md) — the five models and their roles
- [`stack/ci.md`](stack/ci.md), [`stack/runtime.md`](stack/runtime.md), [`stack/hooks.md`](stack/hooks.md)

## The one-sentence version

Five frontier models deliberate in structured rounds over a shared, persistent
filestore; a synthesis is produced, memory is written, and a **closer** emits a
mechanical scorecard. The loop the system is built to run:

```
route → deliberate → verify → persist → score → observe → adapt
```
