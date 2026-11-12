from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


def test_history_only_exposes_user_and_final_assistant_messages():
    from coding_agent.attempts import AttemptManager

    messages = [SystemMessage(content='system secret'), HumanMessage(content='Fix it'),
                AIMessage(content='thinking', tool_calls=[{'name': 'read_file', 'args': {}, 'id': '1'}]),
                ToolMessage(content='file contents', tool_call_id='1'), AIMessage(content='Fixed.')]
    memory = SimpleNamespace(get_tuple=lambda config: SimpleNamespace(checkpoint={'channel_values': {'messages': messages}}))
    manager = AttemptManager()
    manager.attempts['one'] = {'memory': memory, 'busy': False, 'turns': {}}
    assert manager.history('one') == {'messages': [{'role': 'user', 'content': 'Fix it'},
                                                  {'role': 'assistant', 'content': 'Fixed.'}],
                                      'running_turn': None}


def test_history_endpoint_requires_auth_and_reports_running_turn():
    from coding_agent.api import create_app

    class Manager:
        def history(self, attempt_id):
            if attempt_id != 'one':
                raise KeyError(attempt_id)
            return {'messages': [], 'running_turn': 'turn-1'}

    client = TestClient(create_app(manager=Manager(), token='test'))
    assert client.get('/attempts/one/history').status_code == 401
    headers = {'Authorization': 'Bearer test'}
    assert client.get('/attempts/one/history', headers=headers).json()['running_turn'] == 'turn-1'
    assert client.get('/attempts/missing/history', headers=headers).status_code == 404


def test_chat_history_restores_commentary_and_tool_events_in_order(monkeypatch):
    from coding_agent.attempts import AttemptManager

    events = [
        {'type': 'prompt', 'message': 'Find it'},
        {'type': 'progress_update', 'message': 'I will inspect the file.', 'id': 2},
        {'type': 'tool_started', 'name': 'read_file', 'id': 3},
        {'type': 'tool_finished', 'name': 'read_file', 'status': 'completed', 'id': 4},
        {'type': 'answer', 'message': 'Found it.', 'id': 5},
    ]
    rows = [{'turn_id': 't1', 'event': event} for event in events]
    connection = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: rows))
    manager = AttemptManager()
    manager.attempts['a'] = {'busy': False, 'turns': {}}
    monkeypatch.setattr(manager, '_check_chat', lambda *args: None)
    monkeypatch.setattr(manager, '_chat_memory', lambda *args: SimpleNamespace(conn=connection))
    messages = manager.chat_history('a', 'chat')['messages']
    assert [item['role'] for item in messages] == ['user', 'progress', 'tool', 'tool', 'assistant']
    assert messages[1]['content'] == 'I will inspect the file.'
    assert messages[1]['event_key'] == 't1:2'
