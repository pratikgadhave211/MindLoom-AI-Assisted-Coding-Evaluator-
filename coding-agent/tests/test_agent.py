from types import SimpleNamespace
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver


def test_turn_emits_tool_progress_before_final_answer(monkeypatch, tmp_path):
    from coding_agent import agent

    (tmp_path / "app.py").write_text("hello", encoding="utf-8")
    class Model:
        calls = 0
        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "app.py"}, "id": "one"}])
            return AIMessage(content="Found it.")

    monkeypatch.setattr(agent, "make_model", lambda config, tools: Model())
    config = SimpleNamespace(jev_api_key="", langsmith_tracing=False)
    events = []
    result = agent.run_turn("Find the file", tmp_path, InMemorySaver(), "thread", config, events.append)
    assert result["answer"] == "Found it."
    assert [event["type"] for event in events] == ["tool_started", "tool_finished"]
    assert events[0]["name"] == "read_file" and events[0]["call_id"] == "one"
    assert events[1]["status"] == "completed" and events[1]["result"] == "hello"


def test_commentary_is_sent_once_before_its_tool(monkeypatch, tmp_path):
    from coding_agent import agent

    (tmp_path / 'app.py').write_text('hello', encoding='utf-8')
    class Model:
        calls = 0
        def invoke(self, messages):
            self.calls += 1
            if self.calls <= 2:
                return AIMessage(content='I will read the file.', tool_calls=[
                    {'name': 'read_file', 'args': {'path': 'app.py'}, 'id': str(self.calls)}])
            return AIMessage(content='Finished.')

    model = Model()
    monkeypatch.setattr(agent, 'make_model', lambda config, tools: model)
    events = []
    result = agent.run_turn('Read the file', tmp_path, InMemorySaver(), 'thread',
                            SimpleNamespace(jev_api_key='', langsmith_tracing=False), events.append)
    assert [item['type'] for item in events] == ['progress_update', 'tool_started', 'tool_finished', 'tool_started', 'tool_finished']
    assert events[0]['message'] == 'I will read the file.'
    assert model.calls == 3 and result['answer'] == 'Finished.'


def test_private_thinking_is_not_published(monkeypatch, tmp_path):
    from coding_agent import agent
    class Model:
        calls = 0
        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content='<think>private</think>', tool_calls=[
                    {'name': 'list_files', 'args': {'path': '.'}, 'id': 'one'}])
            return AIMessage(content='Done.')
    monkeypatch.setattr(agent, 'make_model', lambda config, tools: Model())
    events = []
    agent.run_turn('List files', tmp_path, InMemorySaver(), 'thread',
                   SimpleNamespace(jev_api_key='', langsmith_tracing=False), events.append)
    assert all(event['type'] != 'progress_update' for event in events)


def test_progress_is_spaced_but_allowed_after_tool_failure(monkeypatch, tmp_path):
    from coding_agent import agent
    class Model:
        calls = 0
        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content='Starting.', tool_calls=[{'name': 'list_files', 'args': {'path': '.'}, 'id': '1'}])
            if self.calls == 2:
                return AIMessage(content='Still looking.', tool_calls=[{'name': 'read_file', 'args': {'path': 'missing'}, 'id': '2'}])
            if self.calls == 3:
                return AIMessage(content='The file is missing; checking the folder.', tool_calls=[{'name': 'list_files', 'args': {'path': '.'}, 'id': '3'}])
            return AIMessage(content='Done.')
    monkeypatch.setattr(agent, 'make_model', lambda config, tools: Model())
    events = []
    agent.run_turn('Inspect', tmp_path, InMemorySaver(), 'thread',
                   SimpleNamespace(jev_api_key='', langsmith_tracing=False), events.append)
    assert [event['message'] for event in events if event['type'] == 'progress_update'] == [
        'Starting.', 'The file is missing; checking the folder.']


def test_unknown_tool_failure_is_visible_and_allows_followup(monkeypatch, tmp_path):
    from coding_agent import agent
    class Model:
        calls = 0
        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content='Starting.', tool_calls=[{'name': 'unknown_tool', 'args': {}, 'id': '1'}])
            if self.calls == 2:
                return AIMessage(content='That tool is unavailable; checking the folder.', tool_calls=[{'name': 'list_files', 'args': {'path': '.'}, 'id': '2'}])
            return AIMessage(content='Done.')
    monkeypatch.setattr(agent, 'make_model', lambda config, tools: Model())
    events = []
    agent.run_turn('Inspect', tmp_path, InMemorySaver(), 'thread',
                   SimpleNamespace(jev_api_key='', langsmith_tracing=False), events.append)
    assert any(event['type'] == 'tool_finished' and event['name'] == 'unknown_tool' and event['status'] == 'error' for event in events)
    assert any(event['type'] == 'progress_update' and event['message'].startswith('That tool') for event in events)
