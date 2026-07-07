"""Tests for the Grok reasoning-effort passthrough.

grok-4.3 silently defaults reasoning_effort to "low" when the param is
omitted, so the guarantee that matters is: the Grok seat actually sends the
configured effort on every chat.completions call (both the no-tools path and
the tool-use loop), and other seats' calls are untouched when extra_body is
None. The param rides in extra_body so any openai>=1.0 SDK forwards it.
"""
import raccoon_swarm_server as srv


class _FakeMessage:
    content = "fine."
    tool_calls = None


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    choices = [_FakeChoice()]


class _FakeClient:
    """Records the kwargs of every chat.completions.create call."""

    def __init__(self):
        self.calls = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                return _FakeResponse()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _call(client, extra_body, monkeypatch, tools_enabled):
    monkeypatch.setattr(srv, "_mcp_tools_enabled", lambda: tools_enabled)
    return srv._openai_chat_with_tools(
        client=client,
        model_name="grok-4.3",
        max_tokens=100,
        tokens_param="max_tokens",
        sys_prompt="sys",
        query="q",
        images=None,
        calling_model="grok",
        label="Grok",
        extra_body=extra_body,
    )


def test_extra_body_sent_without_tools(monkeypatch):
    client = _FakeClient()
    _call(client, {"reasoning_effort": "high"}, monkeypatch, tools_enabled=False)
    assert client.calls[0]["extra_body"] == {"reasoning_effort": "high"}


def test_extra_body_sent_in_tool_loop(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(srv.swarm_tools, "tools_for_openai", lambda: [])
    _call(client, {"reasoning_effort": "high"}, monkeypatch, tools_enabled=True)
    assert client.calls[0]["extra_body"] == {"reasoning_effort": "high"}


def test_none_extra_body_omits_key(monkeypatch):
    """GPT shares this code path and must not receive Grok's param."""
    client = _FakeClient()
    _call(client, None, monkeypatch, tools_enabled=False)
    assert "extra_body" not in client.calls[0]


def test_default_effort_is_high():
    """Env-unset default. If this changes, .env.example and docs/stack/models.md
    document the value and must move with it."""
    assert srv.GROK_REASONING_EFFORT == "high"
