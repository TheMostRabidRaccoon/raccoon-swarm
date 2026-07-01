"""Tests for swarm_deploy — the deployment-profile security policy.

Stdlib-only (like swarm_auth): the whole local/lan/public matrix is exercised
here without Flask or the model stack. The one integration test drives the real
codeexec gate (which returns before spawning any subprocess).
"""
import swarm_deploy as dep


# ---- profile resolution --------------------------------------------------

def test_resolve_defaults_to_local():
    assert dep.resolve_profile(None) == "local"
    assert dep.resolve_profile("") == "local"
    assert dep.resolve_profile("  ") == "local"


def test_resolve_normalizes_case():
    assert dep.resolve_profile(" PUBLIC ") == "public"


def test_unknown_profile_kept_for_flagging():
    # Not silently downgraded to a permissive default — startup_check flags it.
    assert dep.resolve_profile("publik") == "publik"
    assert dep.is_valid_profile("publik") is False


# ---- policy flags --------------------------------------------------------

def test_local_policy_is_permissive():
    p = dep.policy("local")
    assert p["lan_bypass_allowed"] is True
    assert p["require_auth"] is False
    assert p["require_persistent_secret"] is False
    assert p["codeexec_requires_sandbox"] is False


def test_lan_policy():
    p = dep.policy("lan")
    assert p["lan_bypass_allowed"] is True
    assert p["require_persistent_secret"] is True
    assert p["codeexec_requires_sandbox"] is False


def test_public_policy_is_fail_closed():
    p = dep.policy("public")
    assert p["lan_bypass_allowed"] is False
    assert p["require_auth"] is True
    assert p["require_persistent_secret"] is True
    assert p["codeexec_requires_sandbox"] is True


def test_unknown_policy_is_most_restrictive():
    # Fail closed on a typo: composition that runs before the boot check
    # (e.g. closing the CIDR bypass) must not accidentally stay open.
    p = dep.policy("publik")
    assert p["known"] is False
    assert p["lan_bypass_allowed"] is False
    assert p["codeexec_requires_sandbox"] is True


# ---- codeexec sandbox / override detection -------------------------------

def test_sandbox_detection():
    assert dep.codeexec_is_sandboxed({"RRI_CODEEXEC_SANDBOX": "docker"}) is True
    assert dep.codeexec_is_sandboxed({"RRI_CODEEXEC_SANDBOX": "gVisor"}) is True
    assert dep.codeexec_is_sandboxed({"RRI_CODEEXEC_SANDBOX": "handwave"}) is False
    assert dep.codeexec_is_sandboxed({}) is False


def test_override_detection():
    assert dep.codeexec_unsafe_override({"RRI_ALLOW_UNSAFE_PUBLIC_CODEEXEC": "true"}) is True
    assert dep.codeexec_unsafe_override({"RRI_ALLOW_UNSAFE_PUBLIC_CODEEXEC": "1"}) is True
    assert dep.codeexec_unsafe_override({"RRI_ALLOW_UNSAFE_PUBLIC_CODEEXEC": "no"}) is False
    assert dep.codeexec_unsafe_override({}) is False


def test_codeexec_allowed_matrix():
    # local/lan: always allowed.
    assert dep.codeexec_allowed("local", {})[0] is True
    assert dep.codeexec_allowed("lan", {})[0] is True
    # public: blocked unless sandbox or override.
    ok, reason = dep.codeexec_allowed("public", {})
    assert ok is False and "profile 'public'" in reason
    assert dep.codeexec_allowed("public", {"RRI_CODEEXEC_SANDBOX": "docker"})[0] is True
    assert dep.codeexec_allowed("public", {"RRI_ALLOW_UNSAFE_PUBLIC_CODEEXEC": "yes"})[0] is True


# ---- startup_check matrix ------------------------------------------------

def _check(profile, **kw):
    base = dict(auth_enabled=True, has_persistent_secret=True,
                codeexec_sandboxed=True, codeexec_override=False)
    base.update(kw)
    return dep.startup_check(profile, **base)


def test_local_always_boots():
    r = _check("local", auth_enabled=False, has_persistent_secret=False,
               codeexec_sandboxed=False)
    assert r["ok"] is True and r["fatal"] == []


def test_public_requires_auth():
    r = _check("public", auth_enabled=False)
    assert r["ok"] is False
    assert any("authentication" in f for f in r["fatal"])


def test_public_requires_persistent_secret():
    r = _check("public", has_persistent_secret=False)
    assert r["ok"] is False
    assert any("persistent" in f for f in r["fatal"])


def test_public_requires_sandbox_or_override():
    r = _check("public", codeexec_sandboxed=False, codeexec_override=False)
    assert r["ok"] is False
    assert any("unsandboxed" in f for f in r["fatal"])


def test_public_override_boots_but_warns():
    r = _check("public", codeexec_sandboxed=False, codeexec_override=True)
    assert r["ok"] is True
    assert any("UNSAFE" in w for w in r["warnings"])


def test_public_fully_configured_boots_clean():
    r = _check("public")
    assert r["ok"] is True and r["fatal"] == []


def test_lan_missing_secret_warns_not_fatal():
    r = _check("lan", has_persistent_secret=False, codeexec_sandboxed=False)
    assert r["ok"] is True
    assert any("persistent" in w for w in r["warnings"])


def test_unknown_profile_is_fatal():
    r = _check("publik")
    assert r["ok"] is False
    assert any("unknown" in f for f in r["fatal"])


# ---- banner --------------------------------------------------------------

def test_banner_mentions_posture():
    banner = dep.posture_banner("public", dep.policy("public"), 0)
    assert "public" in banner
    assert "fail-closed" in banner  # LAN bypass OFF is called out


# ---- integration: the real codeexec gate ---------------------------------

def test_codeexec_run_blocked_on_public(monkeypatch):
    import swarm_codeexec
    monkeypatch.setenv("RRI_DEPLOYMENT_PROFILE", "public")
    monkeypatch.delenv("RRI_CODEEXEC_SANDBOX", raising=False)
    monkeypatch.delenv("RRI_ALLOW_UNSAFE_PUBLIC_CODEEXEC", raising=False)
    result = swarm_codeexec.run_code("print('should not run')")
    assert result["ok"] is False
    assert result["blocked_by_profile"] == "public"
    assert result["exit_code"] == 126


def test_codeexec_run_allowed_on_local(monkeypatch):
    import swarm_codeexec
    monkeypatch.setenv("RRI_DEPLOYMENT_PROFILE", "local")
    # Not asserting execution success (subprocess/unshare varies by host) — only
    # that the profile gate does NOT block it.
    result = swarm_codeexec.run_code("print('hi')")
    assert result.get("blocked_by_profile") is None
