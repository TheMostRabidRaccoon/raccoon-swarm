"""Current frontier-seat defaults for RRI Swarm.

Keep provider model selection out of the cognitive-role prompts. Model identity
and cultural seat identity are distinct concerns: "Integrator" should survive a
model upgrade without editing the ecology ontology.

Defaults verified against provider documentation in August 2026; every value is
environment-overridable for rollback / A-B testing.
"""
from __future__ import annotations

import os


CLAUDE_MODEL = os.getenv("RRI_CLAUDE_MODEL", "claude-fable-5")
GPT_MODEL = os.getenv("RRI_GPT_MODEL", "gpt-5.6-sol")
GROK_MODEL = os.getenv("RRI_GROK_MODEL", "grok-4.5")
GEMINI_MODEL = os.getenv("RRI_GEMINI_MODEL", "gemini-3.1-pro-preview")
PERPLEXITY_MODEL = os.getenv("RRI_PERPLEXITY_MODEL", "sonar-pro")

# Grok 4.5 supports low / medium / high and defaults to high. Keep it explicit:
# prior RRI sessions showed that low-effort Grok is a materially different seat.
GROK_REASONING_EFFORT = os.getenv("RRI_GROK_REASONING", "high")

# GPT-5.6 Sol supports none / low / medium / high / xhigh / max. This runtime
# currently uses Chat Completions; pass the selected effort through extra_body.
# High is the default RRI seat posture: substantial reasoning without turning
# every ordinary round into a max-compute event. Set xhigh/max experimentally.
GPT_REASONING_EFFORT = os.getenv("RRI_GPT_REASONING", "high")

# Human-readable metadata for /config, logs, and future runtime canaries.
SEAT_MODELS = {
    "claude": {"model": CLAUDE_MODEL, "effort": None},
    "gpt": {"model": GPT_MODEL, "effort": GPT_REASONING_EFFORT},
    "grok": {"model": GROK_MODEL, "effort": GROK_REASONING_EFFORT},
    "gemini": {"model": GEMINI_MODEL, "effort": None},
    "perplexity": {"model": PERPLEXITY_MODEL, "effort": None},
}
