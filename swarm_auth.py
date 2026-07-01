"""Security-critical auth primitives for the Raccoon Swarm.

Extracted from raccoon_swarm_server.py so the trust/secret logic can be
unit-tested WITHOUT importing Flask or the model-client stack, and so every
secret comparison uses constant-time equality (hmac.compare_digest) instead
of a plain `==`, which leaks length/content via timing.

Stdlib only — no Flask, no third-party deps. Keep it that way: this module
is the one piece of the server that CI can exercise on a bare interpreter.

Threat-model note: parse_trusted_cidrs() still defaults to the homelab LAN
ranges (RFC1918 + loopback). Behind a reverse proxy those ranges match the
proxy's own peer IP and silently bypass the login gate. That fail-open is a
deployment-profile concern tracked separately; this module only guarantees
the comparisons themselves are safe.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress

# Homelab defaults: loopback + RFC1918 + link-local/ULA. Callers that expose
# the server publicly should override RRI_TRUSTED_CIDRS (empty string disables
# the LAN bypass entirely).
DEFAULT_TRUSTED_CIDRS = (
    "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,"
    "192.168.0.0/16,fc00::/7,fe80::/10"
)


def constant_time_equals(a: str | None, b: str | None) -> bool:
    """Constant-time string comparison. None on either side is never equal."""
    if a is None or b is None:
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def hash_password(password: str | None) -> str:
    """SHA-256 hex digest, matching the stored RRI_PASSWORD_HASH format.

    Kept identical to the server's historical hashing so existing hashes keep
    working. (A slow KDF would be stronger, but changing it would invalidate
    every deployed RRI_PASSWORD_HASH — out of scope for this hardening pass.)
    """
    return hashlib.sha256((password or "").encode("utf-8")).hexdigest()


def password_matches(password: str | None, stored_hash: str | None) -> bool:
    """Constant-time check of a plaintext password against a stored sha256 hex.

    An empty/None stored hash never matches, so an unconfigured deployment
    cannot be entered with an empty password.
    """
    if not stored_hash:
        return False
    return constant_time_equals(hash_password(password), stored_hash)


def token_matches(provided: str | None, expected: str | None) -> bool:
    """Constant-time bearer/cookie token check. Empty expected never matches."""
    if not expected:
        return False
    return constant_time_equals(provided or "", expected)


def bearer_token_matches(auth_header: str | None, expected: str | None) -> bool:
    """Constant-time check of an 'Authorization: Bearer <token>' header."""
    if not expected:
        return False
    prefix = "Bearer "
    if not auth_header or not auth_header.startswith(prefix):
        return False
    return constant_time_equals(auth_header[len(prefix):], expected)


def parse_trusted_cidrs(env_value: str | None) -> list:
    """Parse a comma-separated CIDR list into ip_network objects.

    - None  -> homelab defaults (env var unset).
    - ""    -> empty list (LAN bypass disabled).
    Invalid entries are skipped rather than raising, so a typo in config can't
    crash the server at import time.
    """
    raw = DEFAULT_TRUSTED_CIDRS if env_value is None else env_value
    nets = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            nets.append(ipaddress.ip_network(chunk))
        except ValueError:
            continue
    return nets


def ip_is_trusted(ip_str: str | None, cidrs: list) -> bool:
    """True if ip_str falls inside any of the given networks. Bad input -> False."""
    if not ip_str:
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in cidrs)
