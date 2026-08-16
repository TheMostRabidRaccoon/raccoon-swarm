"""Current seat-model defaults are explicit and rollbackable."""
from pathlib import Path

import swarm_model_config as cfg


def test_frontier_defaults():
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


def test_nested_agent_routes_are_explicitly_separate():
    grok_nested = cfg.OPTIONAL_NESTED_AGENT_ROUTES["grok_multi_agent"]
    assert grok_nested["model"] == "grok-4.20-multi-agent"
    assert "separate topology" in grok_nested["note"]
    assert cfg.OPTIONAL_NESTED_AGENT_ROUTES["gpt_ultra"]["effort"] == "ultra"


def test_active_entry_loads_runtime_dotenv_before_import_time_model_registry():
    """RRI_* values from project .env must exist before config constants evaluate."""
    server = (Path(__file__).resolve().parents[1] / "raccoon_swarm_server.py").read_text()
    runtime_import = server.index("import swarm_runtime as runtime")
    config_import = server.index("import swarm_model_config as model_config")
    assert runtime_import < config_import
