# Portfolio Worker — deterministic orchestration outline

## Why a separate worker

The existing in-process swarm daemon is useful for autonomous reasoning, but portfolio production requires durable leases, repository worktrees, command allowlists, preview artifacts, and branch/PR state. A web-server thread should not be the source of truth for a long-running build.

## Filesystem queue

```text
portfolio/jobs/
  queued/
  processing/
  review/
  blocked/
  done/
  failed/
```

Use atomic moves on one filesystem. Every terminal job receives a result manifest.

## Worker loop

```python
while True:
    job = claim_next_eligible_job_atomically()
    if not job:
        sleep()
        continue

    validate_schema(job)
    verify_dependencies(job)
    acquire_branch_lease(job)

    try:
        workspace = open_allowlisted_worktree(job)
        prompt = render_prompt(job)
        swarm_result = invoke_headless(
            override_query=prompt,
            rounds=job["rounds"],
            models=job["models"],
        )
        parsed = parse_portfolio_job_result(swarm_result)
        verify_result_against_filesystem_and_ci(parsed, workspace)

        if parsed["status"] == "review_required":
            transition(job, "processing", "review")
        elif parsed["status"] == "blocked":
            transition(job, "processing", "blocked")
        elif acceptance_passed(parsed):
            enqueue_next_phase(parsed["next_job"])
            transition(job, "processing", "done")
        elif retry_allowed(job):
            record_attempt(job, parsed)
            requeue(job)
        else:
            transition(job, "processing", "failed")
    finally:
        release_branch_lease(job)
```

## Result verification

Never trust the model result without checking:

- artifact paths exist;
- changed files are inside allowed paths;
- branch is not protected;
- listed test commands actually ran;
- exit codes match runner logs;
- preview URL belongs to the approved deployment provider;
- screenshot files exist;
- no secret scanner finding;
- no unresolved critical/high red-team item;
- PR exists when claimed;
- no merge occurred.

## Suggested API body

```json
{
  "override_query": "<rendered bounded job prompt>",
  "rounds": 3,
  "models": ["gpt", "claude", "gemini", "grok"]
}
```

## Human review notification

Send one concise review message containing:

- project and phase;
- PR links;
- preview links;
- test summary;
- residual risks;
- exact decision requested.

Do not send one email per model. The inbox is not a distributed tracing backend.
