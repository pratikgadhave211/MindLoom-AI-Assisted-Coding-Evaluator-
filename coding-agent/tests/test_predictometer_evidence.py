from contextlib import nullcontext
from threading import Event
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver


def test_tool_events_include_path_without_edit_content(monkeypatch, tmp_path):
    from coding_agent import agent

    (tmp_path / 'app.py').write_text('hello', encoding='utf-8')

    class Model:
        calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content='', tool_calls=[{
                    'name': 'read_file', 'args': {'path': 'app.py'}, 'id': 'one'}])
            return AIMessage(content='done')

    monkeypatch.setattr(agent, 'make_model', lambda config, tools: Model())
    events = []
    agent.run_turn('Inspect', tmp_path, InMemorySaver(), 'chat',
                   SimpleNamespace(jev_api_key='', langsmith_tracing=False), events.append)
    tool_events = [event for event in events if event['type'].startswith('tool_')]
    assert tool_events[0]['path'] == 'app.py'
    assert tool_events[1]['path'] == 'app.py'
    assert 'args' not in tool_events[0]


def test_model_call_usage_is_emitted_without_provider_secrets(monkeypatch, tmp_path):
    from coding_agent import agent

    class Model:
        def invoke(self, messages):
            return AIMessage(content='done', usage_metadata={'input_tokens': 10, 'output_tokens': 4, 'total_tokens': 14})
    monkeypatch.setattr(agent, 'make_model', lambda config, tools: Model())
    events = []
    agent.run_turn('Inspect', tmp_path, InMemorySaver(), 'thread',
                   SimpleNamespace(jev_api_key='', langsmith_tracing=False), events.append)
    assert events == [{'type': 'model_call', 'usage': {'input_tokens': 10, 'output_tokens': 4, 'total_tokens': 14}}]


def test_failed_model_request_is_counted_with_unknown_usage(monkeypatch, tmp_path):
    from coding_agent import agent
    class Model:
        def invoke(self, messages):
            raise RuntimeError('provider failure')
    monkeypatch.setattr(agent, 'make_model', lambda config, tools: Model())
    events = []
    result = agent.run_turn('Inspect', tmp_path, InMemorySaver(), 'thread',
                            SimpleNamespace(jev_api_key='', langsmith_tracing=False), events.append)
    assert result['error']
    assert events == [{'type': 'model_call', 'usage': None}]


def test_large_tool_result_is_marked_truncated(monkeypatch, tmp_path):
    from coding_agent import agent
    (tmp_path / 'app.py').write_text('x' * 5000, encoding='utf-8')
    class Model:
        calls = 0
        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content='', tool_calls=[{'name': 'read_file', 'args': {'path': 'app.py'}, 'id': 'one'}])
            return AIMessage(content='done')
    monkeypatch.setattr(agent, 'make_model', lambda config, tools: Model())
    events = []
    agent.run_turn('Inspect', tmp_path, InMemorySaver(), 'thread',
                   SimpleNamespace(jev_api_key='', langsmith_tracing=False), events.append)
    finished = next(event for event in events if event['type'] == 'tool_finished')
    assert finished['result_truncated'] is True and len(finished['result']) == 4096


def test_prompt_and_file_evidence_are_attempt_scoped(monkeypatch):
    from coding_agent import attempts

    saved = []
    entered = Event()
    release = Event()
    manager = attempts.AttemptManager()
    attempt = {'workspace': SimpleNamespace(active=True), 'memory': object(), 'config': object(),
               'busy': False, 'turns': {}, 'chats_enabled': True}
    manager.attempts['attempt'] = attempt
    memory = SimpleNamespace(conn=SimpleNamespace(transaction=lambda: nullcontext(), execute=lambda *args: None))
    monkeypatch.setattr(manager, '_chat_memory', lambda attempt: memory)
    monkeypatch.setattr(manager, '_check_chat', lambda *args: None)
    monkeypatch.setattr(attempts, 'append_chat_event', lambda *args: None)
    monkeypatch.setattr(attempts, 'record_evidence', lambda memory, attempt, key, event: saved.append((attempt, key, event)))

    def run(prompt, workspace, memory, chat, config, publish):
        entered.set()
        assert release.wait(5)
        publish({'type': 'tool_finished', 'name': 'read_file', 'path': 'app.py', 'call_id': 'call', 'status': 'completed', 'result': 'private file text'})
        return {'answer': 'done'}

    monkeypatch.setattr(attempts, 'run_turn', run)
    turn = manager.start_turn('attempt', 'Inspect this', chat_id='chat-one')
    assert entered.wait(5)
    with pytest.raises(ValueError, match='already running'):
        manager.start_turn('attempt', 'Overlapping', chat_id='chat-two')
    release.set()
    attempt['thread'].join(5)
    monkeypatch.setattr(attempts, 'run_workspace_tool', lambda *args: {'status': 'completed', 'result': {'version': 'new'}})
    manager.file('attempt', 'write_editor_file', {'path': 'app.py', 'content': 'private edit'})

    assert [item[2]['type'] for item in saved] == ['prompt_accepted', 'tool_finished', 'file_saved']
    assert all(item[0] == 'attempt' for item in saved)
    assert saved[0][1] == f'prompt:{turn}'
    assert saved[1][2]['path'] == 'app.py'
    assert 'private' not in repr(saved)


def test_terminal_activity_is_recorded_as_a_coverage_gap(monkeypatch):
    from coding_agent import attempts

    saved = []
    manager = attempts.AttemptManager()
    manager.attempts['attempt'] = {'workspace': SimpleNamespace(active=True, container='container'), 'busy': False}
    monkeypatch.setattr(manager, '_chat_memory', lambda attempt: object())
    monkeypatch.setattr(attempts, 'record_evidence', lambda memory, attempt, key, event: saved.append(event))
    assert manager.terminal_workspace('attempt') == 'container'
    assert saved == [{'type': 'terminal_opened', 'source': 'user', 'changes_tracked': False}]


def test_evidence_reports_incomplete_collection(monkeypatch):
    from coding_agent import attempts

    manager = attempts.AttemptManager()
    manager.attempts['attempt'] = {'evidence_incomplete': True}
    monkeypatch.setattr(manager, '_chat_memory', lambda attempt: object())
    monkeypatch.setattr(attempts, 'get_evidence', lambda memory, attempt: {'prompt_count': 0, 'revision': 0, 'events': []})
    assert manager.evidence('attempt')['incomplete'] is True


def test_saving_a_file_schedules_background_reassessment(monkeypatch):
    from coding_agent import attempts

    manager = attempts.AttemptManager()
    workspace = SimpleNamespace(active=True)
    config = SimpleNamespace(jev_api_key='key', checkpoint_database_url='db')
    manager.attempts['attempt'] = {'workspace': workspace, 'config': config, 'busy': False}
    monkeypatch.setattr(manager, '_chat_memory', lambda attempt: object())
    monkeypatch.setattr(attempts, 'record_evidence', lambda *args: None)
    monkeypatch.setattr(attempts, 'run_workspace_tool', lambda *args: {'status': 'completed', 'result': {}})
    scheduled = []
    class Thread:
        def __init__(self, target, daemon):
            scheduled.append(target)
        def start(self):
            pass
    monkeypatch.setattr(attempts.threading, 'Thread', Thread)
    manager.file('attempt', 'write_editor_file', {'path': 'app.py'})
    assert len(scheduled) == 1
    assert manager.attempts['attempt']['assessment_running'] is True


def test_older_assessment_cannot_clear_newer_assessment_status(monkeypatch):
    from coding_agent import attempts

    manager = attempts.AttemptManager()
    attempt = {}
    manager.attempts['attempt'] = attempt
    tasks = []
    class Thread:
        def __init__(self, target, daemon):
            tasks.append(target)
        def start(self):
            pass
    monkeypatch.setattr(attempts.threading, 'Thread', Thread)
    manager._start_assessment('attempt', attempt, lambda: None, ())
    manager._start_assessment('attempt', attempt, lambda: None, ())
    tasks[0]()
    assert attempt['assessment_running'] is True
    tasks[1]()
    assert attempt['assessment_running'] is False
