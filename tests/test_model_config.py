"""Current seat-model defaults are explicit and rollbackable."""
import swarm_model_config as cfg


def test_frontier_defaults(monkeypatch):
    # Module-level defaults are expected to match the verified Aug-2026 registry.
    assert cfg.CLAUDE_MODEL == "claude-fable-5"
    assert cfg.GPT_MODEL == "gpt-5.6-sol"
    assert cfg.GROK_MODEL == "grok-4.5"
    assert cfg.GEMINI_MODEL == "gemini-3.1-pro-preview"
    assert cfg.PERPLEXITY_MODEL == "sonar-pro"


def test_reasoning_effort_is_not_left_at_low():
    assert cfg.GROK_REASONING_EFFORT == "high"
    assert cfg.GPT_REASONING_EFFORT == "high"


def test_registry_exposes_effective_seat_models():
    assert cfg.SEAT_MODELS["gpt"]["model"] == cfg.GPT_MODEL
    assert cfg.SEAT_MODELS["grok"]["effort"] == "high"
