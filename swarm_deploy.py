"""Deployment profiles for the Raccoon Swarm — fail closed, fail loud.

RRI_DEPLOYMENT_PROFILE selects a security posture:

  local  (default) — homelab / single machine. Current behavior preserved:
                     LAN auth bypass on, codeexec unrestricted, no secret
                     requirement. Nothing changes for existing deployments.
  lan              — trusted network. LAN bypass still allowed, but a
                     persistent secret is expected and codeexec is warned.
  public           — internet-facing. FAIL CLOSED: the LAN trust bypass is
                     off (the reverse-proxy fail-open documented in #66),
                     auth is required, a persistent secret is required, and
                     codeexec refuses to run unless a real sandbox is declared
                     (or an explicit unsafe override is set). Unsafe configs
                     refuse to BOOT.

Design: stdlib-only and free of Flask/model imports, so the entire policy is
unit-testable on a bare interpreter (same pattern as swarm_auth.py). This
module only DECIDES policy; enforcement lives in the callers (server startup
resolves the profile + refuses to boot; swarm_codeexec gates run_code).

Unsafe states are meant to be loud — the posture banner is logged at boot and
fatal misconfigurations stop the process rather than quietly running open.
"""
from __future__ import annotations

VALID_PROFILES = ("local", "lan", "public")
DEFAULT_PROFILE = "local"

# Env values that count as "a real sandbox is in front of codeexec". The
# operator asserts this; the swarm can't verify a container boundary from
# inside, so we trust-but-make-explicit.
_SANDBOX_BACKENDS = {"docker", "gvisor", "firejail", "nsjail", "podman"}

_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(v) -> bool:
    return str(v).strip().lower() in _TRUTHY if v is not None else False


def resolve_profile(env_value: str | None) -> str:
    """Normalize RRI_DEPLOYMENT_PROFILE. Empty/None -> default 'local'.

    An unrecognized non-empty value is returned as-is (lowercased) so that
    startup_check() can flag it FATAL — we deliberately do NOT silently fall
    back to a permissive profile on a typo (that would be fail-open).
    """
    if not env_value or not env_value.strip():
        return DEFAULT_PROFILE
    return env_value.strip().lower()


def is_valid_profile(profile: str) -> bool:
    return profile in VALID_PROFILES


def policy(profile: str) -> dict:
    """Resolve a profile to its security policy flags.

    An unknown profile resolves to the MOST RESTRICTIVE (public-equivalent)
    flags, so any composition that runs before the boot-time fatal check
    (e.g. closing the CIDR bypass) also fails closed.
    """
    known = profile in VALID_PROFILES
    effective = profile if known else "public"
    return {
        "profile": profile,
        "known": known,
        "lan_bypass_allowed": effective in ("local", "lan"),
        "require_auth": effective == "public",
        "require_persistent_secret": effective in ("lan", "public"),
        "codeexec_requires_sandbox": effective == "public",
    }


def codeexec_is_sandboxed(env: dict) -> bool:
    """True when RRI_CODEEXEC_SANDBOX names a known real sandbox backend."""
    return str(env.get("RRI_CODEEXEC_SANDBOX", "")).strip().lower() in _SANDBOX_BACKENDS


def codeexec_unsafe_override(env: dict) -> bool:
    """True when the operator has explicitly opted into unsafe public codeexec."""
    return _truthy(env.get("RRI_ALLOW_UNSAFE_PUBLIC_CODEEXEC"))


def codeexec_allowed(profile: str, env: dict) -> tuple[bool, str | None]:
    """Whether codeexec may run under this profile. Returns (ok, reason_if_not).

    Only 'public' (or an unknown/fail-closed profile) gates codeexec; local/lan
    run it as before.
    """
    if not policy(profile)["codeexec_requires_sandbox"]:
        return True, None
    if codeexec_is_sandboxed(env):
        return True, None
    if codeexec_unsafe_override(env):
        return True, None
    return False, (
        f"code_exec refused under deployment profile '{profile}': the sandbox is "
        "homelab-grade, not security-grade. Put a real sandbox in front and set "
        "RRI_CODEEXEC_SANDBOX=docker|gvisor|firejail|nsjail|podman, or set "
        "RRI_ALLOW_UNSAFE_PUBLIC_CODEEXEC=true to explicitly accept the risk."
    )


def startup_check(profile: str, *, auth_enabled: bool, has_persistent_secret: bool,
                  codeexec_sandboxed: bool, codeexec_override: bool) -> dict:
    """Validate a deployment config. Returns {ok, fatal: [...], warnings: [...]}.

    Pure over booleans so the whole matrix is testable without env or Flask.
    Fatal entries mean 'refuse to boot'; warnings are logged loudly but allow
    boot.
    """
    fatal: list[str] = []
    warnings: list[str] = []
    pol = policy(profile)

    if not pol["known"]:
        fatal.append(
            f"unknown RRI_DEPLOYMENT_PROFILE '{profile}' — must be one of "
            f"{', '.join(VALID_PROFILES)}"
        )

    if pol["require_auth"] and not auth_enabled:
        fatal.append(
            "profile requires authentication but it is not enabled — set both "
            "RRI_AUTH_TOKEN and RRI_PASSWORD_HASH (there is no LAN bypass on public)"
        )

    if pol["require_persistent_secret"] and not has_persistent_secret:
        msg = ("no persistent session secret — set RRI_AUTH_TOKEN so session "
               "cookies survive restarts and aren't signed with an ephemeral key")
        # On public this is fatal; on lan it's a warning.
        (fatal if pol["profile"] == "public" else warnings).append(msg)

    if pol["codeexec_requires_sandbox"]:
        if not codeexec_sandboxed and not codeexec_override:
            fatal.append(
                "code_exec is unsandboxed on a public profile — set "
                "RRI_CODEEXEC_SANDBOX=<backend> or, to accept the risk explicitly, "
                "RRI_ALLOW_UNSAFE_PUBLIC_CODEEXEC=true"
            )
        elif codeexec_override and not codeexec_sandboxed:
            warnings.append(
                "UNSAFE: code_exec is running WITHOUT a real sandbox on a public "
                "profile because RRI_ALLOW_UNSAFE_PUBLIC_CODEEXEC=true. This is a "
                "homelab-grade boundary exposed to the internet."
            )

    return {"ok": not fatal, "fatal": fatal, "warnings": warnings}


def posture_banner(profile: str, pol: dict, trusted_cidr_count: int) -> str:
    """A loud, human-readable summary of the active security posture."""
    lines = [
        "==================== DEPLOYMENT POSTURE ====================",
        f"  profile:            {profile}" + ("" if pol.get("known") else "  (UNKNOWN!)"),
        f"  LAN auth bypass:    {'ON' if pol['lan_bypass_allowed'] else 'OFF (fail-closed)'}"
        f"  [{trusted_cidr_count} trusted CIDR(s)]",
        f"  auth required:      {'yes' if pol['require_auth'] else 'no'}",
        f"  persistent secret:  {'required' if pol['require_persistent_secret'] else 'optional'}",
        f"  codeexec:           {'sandbox required' if pol['codeexec_requires_sandbox'] else 'unrestricted'}",
        "============================================================",
    ]
    return "\n".join(lines)
