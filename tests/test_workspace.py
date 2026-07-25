"""Tests for swarm_workspace — the fenced repo sandbox.

These cover the guarantees that keep the swarm inside its yard, none of which
touch the network or need a token: the repo allowlist refuses everything but the
sandbox, the base branch can never be written, job-branch names are enforced,
and the permanently-forbidden write paths (workflows, secrets, deploy files,
dependency manifests) are rejected. Network ops fail closed when unconfigured.
"""
import swarm_workspace as ws


# ---- repo allowlist ------------------------------------------------------

def test_default_allowlist_is_sandbox_only(monkeypatch):
    monkeypatch.delenv("SWARM_WORKSPACE_REPOS", raising=False)
    assert ws.allowed_repos() == ("TheMostRabidRaccoon/swarm-lab",)


def test_own_source_repo_is_not_allowed(monkeypatch):
    monkeypatch.delenv("SWARM_WORKSPACE_REPOS", raising=False)
    ok, err = ws.check_repo_allowed("TheMostRabidRaccoon/raccoon-swarm")
    assert not ok and "allowlist" in err


def test_allowlist_is_configurable(monkeypatch):
    monkeypatch.setenv("SWARM_WORKSPACE_REPOS", "TheMostRabidRaccoon/swarm-lab, TheMostRabidRaccoon/rri-workspace-lab")
    assert ws.check_repo_allowed("TheMostRabidRaccoon/rri-workspace-lab")[0]
    assert not ws.check_repo_allowed("TheMostRabidRaccoon/raccoon-swarm")[0]


# ---- branch policy -------------------------------------------------------

def test_base_branch_never_writable(monkeypatch):
    monkeypatch.delenv("SWARM_WORKSPACE_BASE_BRANCH", raising=False)
    for b in ("main", "master"):
        ok, err = ws.check_branch_name(b)
        assert not ok and "base" in err.lower()


def test_custom_base_branch_protected(monkeypatch):
    monkeypatch.setenv("SWARM_WORKSPACE_BASE_BRANCH", "trunk")
    ok, err = ws.check_branch_name("trunk")
    assert not ok


def test_job_branch_must_be_namespaced():
    assert not ws.check_branch_name("my-feature")[0]
    assert not ws.check_branch_name("swarm")[0]
    assert ws.check_branch_name("swarm/latch-build")[0]
    assert ws.check_branch_name("swarm/demo/front-desk")[0]


def test_job_branch_rejects_uppercase_and_spaces():
    assert not ws.check_branch_name("swarm/Latch Build")[0]
    assert not ws.check_branch_name("swarm/../escape")[0]


# ---- forbidden write paths ----------------------------------------------

def test_workflow_files_forbidden():
    assert not ws.check_write_path(".github/workflows/ci.yml")[0]


def test_dependency_manifests_forbidden():
    for p in ("package.json", "requirements.txt", "demos/x/pyproject.toml", "yarn.lock"):
        ok, err = ws.check_write_path(p)
        assert not ok, p


def test_deploy_files_forbidden():
    for p in ("Procfile", "netlify.toml", "Dockerfile", "fly.toml"):
        assert not ws.check_write_path(p)[0], p


def test_secret_and_env_files_forbidden():
    for p in (
        ".env",
        ".env.local",
        "demos/x/.env",
        "demos/x/.env.production",
        "demos/x/.env/config.json",   # .env as a directory segment
        "config/secret_keys.txt",
        "creds/credentials.json",
    ):
        assert not ws.check_write_path(p)[0], p


def test_normal_demo_files_allowed():
    for p in ("demos/latch/index.html", "demos/latch/fixtures/leads.json", "BUILD_LOG.md", "README.md"):
        ok, err = ws.check_write_path(p)
        assert ok, f"{p}: {err}"


def test_path_traversal_rejected():
    assert not ws.check_write_path("../raccoon-swarm/swarm_tools.py")[0]


# ---- fail-closed when unconfigured --------------------------------------

def test_ops_fail_closed_without_token(monkeypatch):
    monkeypatch.delenv("SWARM_WORKSPACE_GITHUB_TOKEN", raising=False)
    assert ws.is_configured() is False
    # A write op should refuse before any network call, on the allowlisted repo.
    res = ws.open_branch("TheMostRabidRaccoon", "swarm-lab", "swarm/x")
    assert res["ok"] is False
    assert "configured" in res["error"] or "token" in res["error"]


def test_status_reports_unconfigured_without_leaking(monkeypatch):
    monkeypatch.delenv("SWARM_WORKSPACE_GITHUB_TOKEN", raising=False)
    st = ws.status()
    assert st["configured"] is False
    assert st["merge_op"].startswith("none")
    # never surfaces a token value
    assert "SWARM_WORKSPACE_GITHUB_TOKEN" not in str(st.get("repos", ""))
