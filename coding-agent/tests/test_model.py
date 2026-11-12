def test_openrouter_model_accepts_all_tool_definitions():
    from coding_agent.config import Config
    from coding_agent.model import make_model
    from coding_agent.tools import TOOLS

    model = make_model(Config(model="openrouter/free", api_key="test-key"), TOOLS)
    names = {item["function"]["name"] for item in model.kwargs["tools"]}
    assert names == {tool.name for tool in TOOLS}
    assert model.bound.client.sdk_configuration.retry_config is None
    assert model.bound.client.sdk_configuration.timeout_ms == 30000


def test_provider_error_messages_are_clear_and_do_not_leak_details():
    from coding_agent.model import model_error

    error = Exception("secret-key")
    error.status_code = 429
    assert "rate limit" in model_error(error).lower()
    assert "secret-key" not in model_error(error)
    error.status_code = 404
    assert "tool calling" in model_error(error).lower()


def test_groq_model_accepts_all_tool_definitions():
    from coding_agent.config import Config
    from coding_agent.model import make_model
    from coding_agent.tools import TOOLS

    model = make_model(Config(model='openai/gpt-oss-120b', api_key='test-key', provider='groq'), TOOLS)
    assert model.bound.model_name == 'openai/gpt-oss-120b'
    assert {item['function']['name'] for item in model.kwargs['tools']} == {tool.name for tool in TOOLS}


def test_nvidia_model_accepts_tools_and_requested_settings(monkeypatch):
    from coding_agent.config import Config
    from coding_agent.model import make_model
    from coding_agent.tools import TOOLS

    captured = {}
    class Model:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def bind_tools(self, tools):
            return tools
    monkeypatch.setattr('coding_agent.model.ChatNVIDIA', Model)
    assert make_model(Config(model='nvidia/nemotron-3-ultra-550b-a55b', api_key='test-key', provider='nvidia'), TOOLS) == TOOLS
    assert captured['model'] == 'nvidia/nemotron-3-ultra-550b-a55b'
    assert captured['temperature'] == 0.4
    assert captured['top_p'] == 0.95
    assert captured['model_kwargs']['chat_template_kwargs'] == {'enable_thinking': True}
