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

## Threat model (intentional gaps)

- No rate limiting on `/login`.
- No CSRF token on the form (single shared password, no multi-user state).
- Cookie is the token itself — token rotation = regenerate UUID + redeploy,
  which invalidates all live sessions. Accept that.

If you outgrow this (multi-user, API keys, SSO), re-design — don't patch.
