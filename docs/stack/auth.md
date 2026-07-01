# Auth

Password-gated login for hosted deployments. Auto-disabled locally.

## Source of truth

- `raccoon_swarm_server.py` routes: `/login` (`:1177`), `/logout` (`:1193`)
- `.env.example` (`RRI_AUTH_TOKEN`, `RRI_PASSWORD_HASH`)

## Model

- **No users, no sessions table.** One shared password, one shared token.
- Server stores the SHA256 hex of the password (`RRI_PASSWORD_HASH`).
- On successful login, the server sets a session cookie whose value equals
  `RRI_AUTH_TOKEN` (a UUID4 the operator generates once).
- Subsequent requests validate cookie == `RRI_AUTH_TOKEN`.

## Env vars

| Var                  | Format                                 |
|----------------------|----------------------------------------|
| `RRI_AUTH_TOKEN`     | UUID4 string                           |
| `RRI_PASSWORD_HASH`  | SHA256 hex of the chosen password      |

Generate password hash:

```bash
printf '%s' 'your-password' | sha256sum
# copy the hex (first field) into RRI_PASSWORD_HASH
```

## Local dev

Auth is auto-disabled when neither var is set — local runs land straight on
the UI. Do not set these in `.env` unless you want to test the login flow.

## Routes

| Route       | Method    | Purpose                            |
|-------------|-----------|------------------------------------|
| `/login`    | GET, POST | Login form + submit                |
| `/logout`   | GET       | Clear cookie, redirect to `/login` |

## Deployment profiles (`RRI_DEPLOYMENT_PROFILE`)

Selects a security posture; enforced at boot in `swarm_deploy.py` (stdlib-only,
unit-tested). **Fail closed, fail loud** — the active posture is logged as a
banner at startup and unsafe outward-facing configs refuse to boot.

| Setting                 | `local` (default) | `lan`             | `public`                    |
|-------------------------|-------------------|-------------------|-----------------------------|
| LAN auth bypass (CIDRs) | on                | on (configurable) | **off** (fail-closed)       |
| Auth required           | no                | no                | **yes** (both env vars)     |
| Persistent secret       | optional          | warned if missing | **required**                |
| `code_exec`             | unrestricted      | unrestricted      | **sandbox required** to run |

- **Why `public` closes the LAN bypass:** the default trusted CIDRs include
  RFC1918 ranges. Behind a reverse proxy the peer IP is the proxy (often a
  private/loopback address), so the bypass would fail *open* for public
  clients. `public` sets `TRUSTED_CIDRS = []` regardless of `RRI_TRUSTED_CIDRS`.
- **`code_exec` on `public`:** the sandbox is homelab-grade, not security-grade
  (`swarm_codeexec.py`). On `public` it refuses to run — and the server refuses
  to boot — unless `RRI_CODEEXEC_SANDBOX=docker|gvisor|firejail|nsjail|podman`
  declares a real boundary, or `RRI_ALLOW_UNSAFE_PUBLIC_CODEEXEC=true` accepts
  the risk explicitly (logged as a loud UNSAFE warning).
- An unknown profile value is treated as most-restrictive and is fatal — a typo
  never silently downgrades to a permissive posture.

## Threat model (intentional gaps)

- No rate limiting on `/login`.
- No CSRF token on the form (single shared password, no multi-user state).
- Cookie is the token itself — token rotation = regenerate UUID + redeploy,
  which invalidates all live sessions. Accept that.
- Deployment profiles gate the LAN bypass and `code_exec`, but do not yet add
  rate-limiting, CSRF, or upload/debug-route hardening — those cells are noted
  in the review backlog, not enforced.

If you outgrow this (multi-user, API keys, SSO), re-design — don't patch.
