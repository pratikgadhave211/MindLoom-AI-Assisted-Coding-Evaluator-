from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver


@pytest.mark.parametrize('interrupted', [True, False])
def test_retry_closes_unfinished_tool_calls_without_running_them(monkeypatch, tmp_path, interrupted):
    from coding_agent import agent
    from coding_agent.graph import build_graph

    class Model:
        def invoke(self, messages):
            self.messages = list(messages)
            return AIMessage(content='I can continue.')

    model = Model()
    monkeypatch.setattr(agent, 'make_model', lambda config, tools: model)
    memory = InMemorySaver()
    graph = build_graph(model, workspace=tmp_path, checkpointer=memory)
    options = {'configurable': {'thread_id': 'retry'}}
    calls = [
        {'name': 'read_file', 'args': {'path': 'app.py'}, 'id': 'one'},
        {'name': 'edit_file', 'args': {'path': 'app.py'}, 'id': 'two'},
    ]
    messages = [HumanMessage(content='Fix it'), AIMessage(content='', tool_calls=calls),
                ToolMessage(content='original content', tool_call_id='one')]
    graph.update_state(options, {'messages': messages, 'pending_calls': [(False, calls[1])]},
                       as_node='ask_model' if interrupted else 'finish')
    events = []
    result = agent.run_turn('Try again', tmp_path, memory, 'retry',
                            SimpleNamespace(jev_api_key='', langsmith_tracing=False), events.append)
    assert result['answer'] == 'I can continue.'
    assert model.messages[-3].content == 'original content'
    assert model.messages[-2].tool_call_id == 'two'
    assert 'unknown' in model.messages[-2].content.lower()
    assert model.messages[-1].content == 'Try again'
    assert [event['type'] for event in events] == ['model_call']
    assert not (tmp_path / 'app.py').exists()


def test_retry_refuses_tool_request_without_id(monkeypatch, tmp_path):
    from coding_agent import agent
    from coding_agent.graph import build_graph
    model = object()
    monkeypatch.setattr(agent, 'make_model', lambda config, tools: model)
    memory = InMemorySaver()
    graph = build_graph(model, workspace=tmp_path, checkpointer=memory)
    options = {'configurable': {'thread_id': 'retry'}}
    call = {'name': 'read_file', 'args': {}, 'id': None}
    graph.update_state(options, {'messages': [AIMessage(content='', tool_calls=[call])],
                                 'pending_calls': [(False, call)]}, as_node='finish')
    with pytest.raises(ValueError, match='tool call'):
        agent.run_turn('Try again', tmp_path, memory, 'retry',
                       SimpleNamespace(jev_api_key='', langsmith_tracing=False), lambda event: None)


def test_retry_stops_old_workspace_processes_before_repair(monkeypatch):
    from coding_agent import agent
    from coding_agent.container_workspace import Attempt
    from coding_agent.graph import build_graph

    memory = InMemorySaver()
    graph = build_graph(object(), workspace='workspace', checkpointer=memory)
    options = {'configurable': {'thread_id': 'retry'}}
    call = {'name': 'run_command', 'args': {'command': 'echo hi'}, 'id': 'one'}
    graph.update_state(options, {'messages': [AIMessage(content='', tool_calls=[call])],
                                 'pending_calls': [(False, call)]}, as_node='ask_model')
    commands = []
    monkeypatch.setattr(agent, 'docker', lambda *args: commands.append(args))
    agent.prepare_checkpoint(graph, options, Attempt(container='workspace', volume='volume'))
    assert commands == [('restart', 'workspace')]
    assert graph.get_state(options).next == ()


def test_failed_workspace_restart_keeps_checkpoint_unfinished(monkeypatch):
    from coding_agent import agent
    from coding_agent.container_workspace import Attempt
    from coding_agent.graph import build_graph

    memory = InMemorySaver()
    graph = build_graph(object(), workspace='workspace', checkpointer=memory)
    options = {'configurable': {'thread_id': 'retry'}}
    call = {'name': 'run_command', 'args': {'command': 'echo hi'}, 'id': 'one'}
    graph.update_state(options, {'messages': [AIMessage(content='', tool_calls=[call])],
                                 'pending_calls': [(False, call)]}, as_node='ask_model')
    def fail(*args):
        raise OSError('Docker unavailable')
    monkeypatch.setattr(agent, 'docker', fail)
    workspace = Attempt(container='workspace', volume='volume')
    with pytest.raises(RuntimeError, match='interrupted workspace'):
        agent.prepare_checkpoint(graph, options, workspace)
    assert not workspace.active
    assert graph.get_state(options).next
    assert graph.get_state(options).values['pending_calls']


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
    tool_events = [event for event in events if event['type'].startswith('tool_')]
    assert [event["type"] for event in tool_events] == ["tool_started", "tool_finished"]
    assert tool_events[0]["name"] == "read_file" and tool_events[0]["call_id"] == "one"
    assert tool_events[1]["status"] == "completed" and tool_events[1]["result"] == "hello"


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
    visible = [item for item in events if item['type'] != 'model_call']
    assert [item['type'] for item in visible] == ['progress_update', 'tool_started', 'tool_finished', 'tool_started', 'tool_finished']
    assert visible[0]['message'] == 'I will read the file.'
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
