"""Portfolio Workspace — the swarm's fenced repo yard.

The swarm has no repo tools today: it can write to its filestore and run
sandboxed code, but it cannot open a branch or a pull request. This module is
the *narrow* production toolchain that changes that — WITHOUT ever letting the
swarm touch its own source, push to main, merge, or read a secret.

The fence, in one sentence: the deterministic worker in this module holds a
fine-grained GitHub token; the models only ever see the narrow operations
below and their returned results.

Two boundaries enforce "the swarm cannot change its own code":

  1. GitHub-side (the real one). The token you install MUST be a *fine-grained*
     PAT (or GitHub App installation) scoped to ONLY the sandbox repo(s) — never
     to raccoon-swarm. A fine-grained token scoped to swarm-lab literally cannot
     see raccoon-swarm, so "can't touch its own code" is true at the API layer,
     not by policy. Turn on branch protection (require PR + review) on the
     sandbox repo's default branch so even the token can't self-merge.

  2. This module (defense in depth). Even with a broader token, every op here
     refuses any repo not on SWARM_WORKSPACE_REPOS, refuses writes to the base/
     protected branch, refuses non-job branch names, refuses forbidden paths
     (workflows, secrets, deploy files, dependency manifests), and there is NO
     merge op and NO push-to-main op — they simply do not exist.

Configuration (env):
  SWARM_WORKSPACE_GITHUB_TOKEN  fine-grained PAT, scoped to the sandbox repo(s)
                                only. Held by the worker; never sent to a model.
  SWARM_WORKSPACE_REPOS         comma-separated owner/repo allowlist
                                (default: TheMostRabidRaccoon/swarm-lab)
  SWARM_WORKSPACE_BASE_BRANCH   base to branch from / protect (default: main)

Ops (all return {ok, ...} dicts; never raise to the caller):
  workspace_status       config + reachability, no secrets leaked
  workspace_list_files   list a directory at a ref
  workspace_read         read a file (returns content + blob sha as its hash)
  workspace_open_branch  create a job branch off the base (a lease)
  workspace_put_file     create/update ONE file on a job branch (optimistic
                         concurrency via sha); refuses base branch + forbidden
                         paths
  workspace_open_pr      open a DRAFT pull request; never merges

Naming: job branches must match `swarm/<slug>` so a lease is always
distinguishable from a human branch and can never be the base branch.

Multi-file atomic commits (git-data blobs→tree→commit) are a deliberate
follow-up; v1 is per-file puts, which the Contents API gives us cleanly and
safely. requests + stdlib only.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any

# NOTE: `requests` is imported lazily inside _gh() (the only place it's used) so
# this module — and its pure validation guards — import on a bare interpreter.
# CI runs the unit suite with stdlib + pytest + numpy only (see tests.yml), and
# the network ops are never exercised there.

logger = logging.getLogger("SwarmVault")

WORKSPACE_VERSION = "1"

GITHUB_API = "https://api.github.com"
_HTTP_TIMEOUT = 20

_DEFAULT_REPOS = ("TheMostRabidRaccoon/swarm-lab",)

# Job branches are leases; they must be namespaced so they can never collide
# with — or be — the base branch. `swarm/<slug>`.
_JOB_BRANCH_RE = re.compile(r"^swarm/[a-z0-9][a-z0-9._\-/]{0,80}$")

# Names/prefixes the swarm may never write, per the Autonomy Ladder's permanent
# forbiddens (workflows, secrets, deploy files, dependency manifests). Matched
# defensively even though the sandbox repo is disposable — the boundary is part
# of what the demo teaches, and models should learn it here.
_FORBIDDEN_PREFIXES = (
    ".github/workflows/",
    ".github/actions/",
)
_FORBIDDEN_BASENAMES = frozenset({
    # dependency manifests / lockfiles
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "poetry.lock", "pipfile", "pipfile.lock",
    "go.mod", "go.sum", "cargo.toml", "cargo.lock", "gemfile", "gemfile.lock",
    # deploy / infra
    "procfile", "netlify.toml", "vercel.json", "railway.json", "railway.toml",
    "render.yaml", "fly.toml", "dockerfile", "docker-compose.yml",
    "docker-compose.yaml",
})
_FORBIDDEN_SUFFIXES = (".env",)
_FORBIDDEN_NAME_SUBSTR = ("secret", "credential")


# ============================================================
# Config (pure — safe to unit-test without a token or network)
# ============================================================

def _token() -> "str | None":
    tok = os.getenv("SWARM_WORKSPACE_GITHUB_TOKEN")
    return tok.strip() if tok and tok.strip() else None


def allowed_repos() -> tuple[str, ...]:
    raw = os.getenv("SWARM_WORKSPACE_REPOS")
    if not raw or not raw.strip():
        return _DEFAULT_REPOS
    repos = tuple(s.strip() for s in raw.split(",") if s.strip())
    return repos or _DEFAULT_REPOS


def base_branch() -> str:
    return (os.getenv("SWARM_WORKSPACE_BASE_BRANCH") or "main").strip()


def is_configured() -> bool:
    return _token() is not None


def check_repo_allowed(slug: str) -> "tuple[bool, str | None]":
    if slug not in allowed_repos():
        return False, (
            f"repo {slug!r} is not on the workspace allowlist "
            f"({', '.join(allowed_repos())}). The swarm may only touch its "
            f"sandbox repo — never its own source."
        )
    return True, None


def check_branch_name(branch: str) -> "tuple[bool, str | None]":
    if branch == base_branch() or branch in ("main", "master"):
        return False, (
            f"{branch!r} is the base/protected branch — the swarm never writes "
            f"there. Open a job branch (swarm/<slug>) and a draft PR instead."
        )
    if not _JOB_BRANCH_RE.match(branch):
        return False, (
            f"branch {branch!r} must be a job lease named 'swarm/<slug>' "
            f"(lowercase, starts with a letter/digit)."
        )
    return True, None


def check_write_path(path: str) -> "tuple[bool, str | None]":
    """Reject the permanently-forbidden write targets. Defense in depth on top
    of the token's repo scope."""
    p = (path or "").strip().lstrip("/")
    if not p:
        return False, "empty path"
    if ".." in p.split("/"):
        return False, "path may not contain '..'"
    low = p.lower()
    base = low.rsplit("/", 1)[-1]
    for pref in _FORBIDDEN_PREFIXES:
        if low.startswith(pref):
            return False, f"path {path!r} is forbidden (workflow/CI files are Conductor-only)"
    if base in _FORBIDDEN_BASENAMES:
        return False, f"path {path!r} is a forbidden file (deploy file or dependency manifest — Conductor-only)"
    # requirements.txt / requirements-dev.txt / requirements_prod.txt, etc.
    if base.startswith("requirements") and base.endswith(".txt"):
        return False, f"path {path!r} is a dependency manifest — Conductor-only"
    # .env anywhere in the path, including as a DIRECTORY segment
    # (sandbox/.env/config slips past a basename-suffix check).
    if any(part == ".env" or part.startswith(".env.") for part in low.split("/")):
        return False, f"path {path!r} looks like a secret/env file — forbidden"
    if any(base.endswith(sfx) for sfx in _FORBIDDEN_SUFFIXES):
        return False, f"path {path!r} looks like a secret/env file — forbidden"
    if any(s in base for s in _FORBIDDEN_NAME_SUBSTR):
        return False, f"path {path!r} looks like a secret/credential file — forbidden"
    return True, None


# ============================================================
# HTTP (the worker's private channel — token never returned)
# ============================================================

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "raccoon-swarm-workspace/1",
    }


def _gh(method: str, path: str, **kwargs) -> "tuple[dict | list | None, str | None]":
    """Call the GitHub REST API. Returns (json_or_none, error_or_none).

    Never raises; never leaks the token into an error string.
    """
    if not is_configured():
        return None, (
            "workspace not configured — set SWARM_WORKSPACE_GITHUB_TOKEN to a "
            "fine-grained token scoped to the sandbox repo only."
        )
    import requests  # lazy — keeps the module importable on a bare interpreter
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    try:
        resp = requests.request(method, url, headers=_headers(), timeout=_HTTP_TIMEOUT, **kwargs)
    except requests.RequestException as e:
        return None, f"request failed: {type(e).__name__}"
    if resp.status_code >= 400:
        # Surface GitHub's message (safe — no token), trimmed.
        msg = ""
        try:
            msg = (resp.json() or {}).get("message", "")
        except ValueError:
            msg = resp.text[:200]
        return None, f"github {resp.status_code}: {msg}"
    if resp.status_code == 204 or not resp.content:
        return {}, None
    try:
        return resp.json(), None
    except ValueError:
        return None, "github returned non-JSON body"


def _split_slug(owner: str, repo: str) -> str:
    return f"{owner}/{repo}"


# ============================================================
# Ops
# ============================================================

def status() -> dict:
    """Config + reachability. Reports whether a token is present (never the
    token itself) and confirms each allowlisted repo resolves."""
    out: dict[str, Any] = {
        "ok": True,
        "workspace_version": WORKSPACE_VERSION,
        "configured": is_configured(),
        "allowed_repos": list(allowed_repos()),
        "base_branch": base_branch(),
        "merge_op": "none (draft PRs only — Conductor merges)",
    }
    if not is_configured():
        out["note"] = (
            "No token installed. Set SWARM_WORKSPACE_GITHUB_TOKEN (fine-grained, "
            "scoped to the sandbox repo only) to enable branch/PR ops."
        )
        return out
    repos = []
    for slug in allowed_repos():
        owner, _, repo = slug.partition("/")
        data, err = _gh("GET", f"/repos/{owner}/{repo}")
        if err:
            repos.append({"repo": slug, "reachable": False, "error": err})
        else:
            repos.append({
                "repo": slug, "reachable": True,
                "default_branch": data.get("default_branch"),
                "private": data.get("private"),
            })
    out["repos"] = repos
    return out


def list_files(owner: str, repo: str, path: str = "", ref: str = "") -> dict:
    ok, err = check_repo_allowed(_split_slug(owner, repo))
    if not ok:
        return {"ok": False, "error": err}
    ref = ref or base_branch()
    params = {"ref": ref}
    data, err = _gh("GET", f"/repos/{owner}/{repo}/contents/{path.strip('/')}", params=params)
    if err:
        return {"ok": False, "error": err}
    if isinstance(data, dict):  # a file, not a dir
        return {"ok": True, "path": path, "ref": ref, "type": "file",
                "files": [{"path": data.get("path"), "type": data.get("type"),
                           "size": data.get("size"), "sha": data.get("sha")}]}
    files = [{"path": it.get("path"), "type": it.get("type"),
              "size": it.get("size"), "sha": it.get("sha")} for it in (data or [])]
    return {"ok": True, "path": path or "(root)", "ref": ref, "files": files}


def read_file(owner: str, repo: str, path: str, ref: str = "") -> dict:
    ok, err = check_repo_allowed(_split_slug(owner, repo))
    if not ok:
        return {"ok": False, "error": err}
    ref = ref or base_branch()
    data, err = _gh("GET", f"/repos/{owner}/{repo}/contents/{path.strip('/')}", params={"ref": ref})
    if err:
        return {"ok": False, "error": err}
    if not isinstance(data, dict) or data.get("type") != "file":
        return {"ok": False, "error": f"{path!r} is not a file"}
    try:
        content = base64.b64decode(data.get("content", "")).decode("utf-8", "replace")
    except (ValueError, TypeError):
        content = ""
    return {"ok": True, "path": path, "ref": ref, "sha": data.get("sha"),
            "size": data.get("size"), "content": content}


def open_branch(owner: str, repo: str, branch: str, from_branch: str = "") -> dict:
    """Create a job branch (a lease) off the base branch."""
    ok, err = check_repo_allowed(_split_slug(owner, repo))
    if not ok:
        return {"ok": False, "error": err}
    ok, err = check_branch_name(branch)
    if not ok:
        return {"ok": False, "error": err}
    src = from_branch or base_branch()
    ref, err = _gh("GET", f"/repos/{owner}/{repo}/git/ref/heads/{src}")
    if err:
        return {"ok": False, "error": f"base branch {src!r}: {err}"}
    sha = (ref or {}).get("object", {}).get("sha")
    if not sha:
        return {"ok": False, "error": f"could not resolve base branch {src!r}"}
    data, err = _gh("POST", f"/repos/{owner}/{repo}/git/refs",
                    json={"ref": f"refs/heads/{branch}", "sha": sha})
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "repo": _split_slug(owner, repo), "branch": branch,
            "from": src, "base_sha": sha}


def put_file(owner: str, repo: str, branch: str, path: str, content: str,
             message: str, sha: str = "", model: str = "unknown",
             session_id: str = "unknown") -> dict:
    """Create or update ONE file on a job branch. Optimistic concurrency: pass
    the current blob `sha` when updating an existing file. Refuses the base
    branch and forbidden paths."""
    ok, err = check_repo_allowed(_split_slug(owner, repo))
    if not ok:
        return {"ok": False, "error": err}
    ok, err = check_branch_name(branch)
    if not ok:
        return {"ok": False, "error": err}
    ok, err = check_write_path(path)
    if not ok:
        return {"ok": False, "error": err}
    # Rung-0 provenance stamp on every commit.
    stamped = (message or f"swarm: update {path}").rstrip() + (
        f"\n\nswarm-provenance: model={model} session={session_id} "
        f"boot={_boot_sha()}")
    body = {
        "message": stamped,
        "content": base64.b64encode((content or "").encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    data, err = _gh("PUT", f"/repos/{owner}/{repo}/contents/{path.strip('/')}", json=body)
    if err:
        return {"ok": False, "error": err}
    commit = (data or {}).get("commit", {})
    content_info = (data or {}).get("content", {})
    return {"ok": True, "repo": _split_slug(owner, repo), "branch": branch,
            "path": path, "commit_sha": commit.get("sha"),
            "blob_sha": content_info.get("sha")}


def open_pr(owner: str, repo: str, head: str, title: str, body: str = "",
            base: str = "", model: str = "unknown", session_id: str = "unknown") -> dict:
    """Open a DRAFT pull request. There is no merge op; the Conductor merges."""
    ok, err = check_repo_allowed(_split_slug(owner, repo))
    if not ok:
        return {"ok": False, "error": err}
    ok, err = check_branch_name(head)
    if not ok:
        return {"ok": False, "error": f"head {err}"}
    base = base or base_branch()
    stamp = (f"\n\n---\n_swarm-provenance: model={model} · session={session_id} "
             f"· boot={_boot_sha()} · draft (Conductor merges)_")
    data, err = _gh("POST", f"/repos/{owner}/{repo}/pulls",
                    json={"title": title or f"swarm: {head}", "head": head,
                          "base": base, "body": (body or "") + stamp, "draft": True})
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "repo": _split_slug(owner, repo),
            "number": data.get("number"), "url": data.get("html_url"),
            "draft": data.get("draft", True), "state": data.get("state")}


def _boot_sha() -> str:
    try:
        import swarm_version
        return swarm_version.BOOT_COMMIT or "unknown"
    except Exception:
        return "unknown"
