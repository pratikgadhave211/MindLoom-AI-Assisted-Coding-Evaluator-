from types import SimpleNamespace

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver


def test_agent_logs_tool_and_final_result(monkeypatch, tmp_path, capsys):
    from coding_agent import agent

    (tmp_path / 'app.py').write_text('example content', encoding='utf-8')
    class Model:
        calls = 0
        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content='', tool_calls=[{'name': 'read_file', 'args': {'path': 'app.py'}, 'id': 'call-1'}])
            return AIMessage(content='Finished.')

    monkeypatch.setattr(agent, 'make_model', lambda config, tools: Model())
    agent.run_turn('Read app', tmp_path, InMemorySaver(), 'thread', SimpleNamespace(jev_api_key='', langsmith_tracing=False), lambda event: None)
    output = capsys.readouterr().out
    assert 'read_file' in output and 'app.py' in output
    assert 'example content' in output and 'Finished.' in output


def test_model_error_logs_provider_details_without_headers_or_secrets(capsys):
    from coding_agent.graph import build_graph

    class ProviderError(Exception):
        status_code = 400
        body = '{"error":{"message":"Provider returned error","code":400,"metadata":{"provider_name":"AtlasCloud","raw":"{\\"msg\\":\\"bad request\\"}"}}}'
        headers = {'Authorization': 'Bearer do-not-print'}
    class Model:
        def invoke(self, messages):
            raise ProviderError('secret-value')

    result = build_graph(Model()).invoke({'prompt': 'Hi'})
    output = capsys.readouterr().out
    assert result['error']
    assert 'ProviderError' in output and '400' in output and 'AtlasCloud' in output and 'bad request' in output
    assert 'secret-value' not in output and 'do-not-print' not in output


def test_known_keys_are_redacted_from_logged_content(monkeypatch, capsys):
    from coding_agent.diagnostics import log_event
    monkeypatch.setenv('OPENROUTER_API_KEY', 'known-test-key-12345')
    log_event('tool result', {'content': 'value known-test-key-12345'})
    output = capsys.readouterr().out
    assert 'known-test-key-12345' not in output
    assert '[redacted]' in output
