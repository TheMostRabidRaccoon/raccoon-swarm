"""Tests for swarm_auth — the security-critical comparison + trust logic.

These exist because the same logic used to be fused into the 5k-line Flask
module and couldn't be tested without importing the whole model-client stack.
swarm_auth is stdlib-only precisely so this runs on a bare interpreter.
"""
import swarm_auth as auth


# ---- constant_time_equals ------------------------------------------------

def test_constant_time_equals_basic():
    assert auth.constant_time_equals("abc", "abc") is True
    assert auth.constant_time_equals("abc", "abd") is False
    assert auth.constant_time_equals("abc", "abcd") is False


def test_constant_time_equals_none_safe():
    assert auth.constant_time_equals(None, "x") is False
    assert auth.constant_time_equals("x", None) is False
    assert auth.constant_time_equals(None, None) is False


# ---- password_matches ----------------------------------------------------

def test_password_matches_roundtrip():
    stored = auth.hash_password("hunter2")
    assert auth.password_matches("hunter2", stored) is True
    assert auth.password_matches("wrong", stored) is False


def test_password_never_matches_empty_hash():
    # An unconfigured deployment (no hash) must not be enterable.
    assert auth.password_matches("", "") is False
    assert auth.password_matches("anything", None) is False


def test_hash_password_matches_legacy_sha256():
    # Must stay bit-compatible with the historical hashlib.sha256 hex format
    # so existing RRI_PASSWORD_HASH values keep working.
    import hashlib
    assert auth.hash_password("pw") == hashlib.sha256(b"pw").hexdigest()


# ---- token_matches / bearer_token_matches --------------------------------

def test_token_matches():
    assert auth.token_matches("secret", "secret") is True
    assert auth.token_matches("nope", "secret") is False


def test_token_never_matches_empty_expected():
    assert auth.token_matches("", "") is False
    assert auth.token_matches("x", "") is False


def test_bearer_token_matches():
    assert auth.bearer_token_matches("Bearer secret", "secret") is True
    assert auth.bearer_token_matches("secret", "secret") is False       # missing prefix
    assert auth.bearer_token_matches("Bearer wrong", "secret") is False
    assert auth.bearer_token_matches("", "secret") is False
    assert auth.bearer_token_matches("Bearer secret", "") is False      # unconfigured


# ---- CIDR trust ----------------------------------------------------------

def test_parse_trusted_cidrs_defaults_and_disable():
    # None -> homelab defaults; "" -> fully disabled.
    assert len(auth.parse_trusted_cidrs(None)) > 0
    assert auth.parse_trusted_cidrs("") == []


def test_parse_trusted_cidrs_skips_garbage():
    nets = auth.parse_trusted_cidrs("10.0.0.0/8, not-a-cidr, 192.168.0.0/16")
    assert len(nets) == 2


def test_ip_is_trusted_lan_vs_public():
    cidrs = auth.parse_trusted_cidrs(None)
    assert auth.ip_is_trusted("127.0.0.1", cidrs) is True
    assert auth.ip_is_trusted("192.168.1.50", cidrs) is True
    assert auth.ip_is_trusted("10.1.2.3", cidrs) is True
    assert auth.ip_is_trusted("8.8.8.8", cidrs) is False


def test_ip_is_trusted_bad_input():
    cidrs = auth.parse_trusted_cidrs(None)
    assert auth.ip_is_trusted("", cidrs) is False
    assert auth.ip_is_trusted("not-an-ip", cidrs) is False


def test_empty_cidrs_trusts_nobody():
    # This is the "public deployment" posture: no LAN bypass at all.
    assert auth.ip_is_trusted("127.0.0.1", []) is False
