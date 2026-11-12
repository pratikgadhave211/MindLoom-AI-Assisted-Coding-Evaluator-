import os
import subprocess
import pytest
from fastapi.testclient import TestClient


def test_chat_routes_keep_conversations_separate():
    from coding_agent.api import create_app

    class Manager:
        def list_chats(self, attempt):
            return [{'id': 'old', 'title': 'Earlier chat'}]

        def create_chat(self, attempt):
            return {'id': 'new', 'title': 'New chat'}

        def chat_history(self, attempt, chat):
            if chat == 'wrong':
                raise KeyError(chat)
            return {'messages': [], 'running_turn': None}

        def start_turn(self, attempt, prompt, chat_id=None):
            assert chat_id == 'new'
            return 'turn'

    client = TestClient(create_app(manager=Manager(), token='test'))
    headers = {'Authorization': 'Bearer test'}
    assert client.get('/attempts/a/chats', headers=headers).json()[0]['id'] == 'old'
    assert client.post('/attempts/a/chats', headers=headers).json()['id'] == 'new'
    assert client.get('/attempts/a/chats/wrong/history', headers=headers).status_code == 404
    assert client.post('/attempts/a/chats/new/turns', headers=headers, json={'prompt': 'hello'}).status_code == 202


@pytest.mark.skipif(os.environ.get('AGENT_POSTGRES_TEST') != '1' or os.environ.get('AGENT_DOCKER_TEST') != '1',
                    reason='Docker and PostgreSQL integration are opt-in')
def test_chats_share_workspace_but_not_model_history(monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage
    from coding_agent import agent
    from coding_agent.api import create_app
    from coding_agent.attempts import AttemptManager
    from coding_agent.config import load_config
    from coding_agent.memory import open_memory

    class Model:
        def __init__(self):
            self.inputs = []

        def invoke(self, messages):
            self.inputs.append([item.content for item in messages if isinstance(item, HumanMessage)])
            if self.inputs[-1][-1] == 'fail prompt':
                raise RuntimeError('test model failure')
            if self.inputs[-1][-1] == 'new prompt' and isinstance(messages[-1], HumanMessage):
                return AIMessage(content='I will inspect the blog.', tool_calls=[{'id': 'read', 'name': 'read_file',
                                                        'args': {'path': 'flaskr/blog.py'}}])
            return AIMessage(content='done')

    model = Model()
    monkeypatch.setattr(agent, 'make_model', lambda config, tools: model)
    monkeypatch.setenv('TYPESAFE_API_KEY', '')
    manager = AttemptManager()
    client = TestClient(create_app(manager=manager, token='test'))
    headers = {'Authorization': 'Bearer test'}
    attempt = client.post('/attempts', headers=headers).json()['attempt_id']
    volume = manager.attempts[attempt]['workspace'].volume
    chats = []
    try:
        base = f'/attempts/{attempt}'
        path = 'flaskr/blog.py'
        original = client.get(base + '/file', headers=headers, params={'path': path}).json()
        changed = original['content'] + '\n# shared workspace test\n'
        assert client.put(base + '/file', headers=headers, json={'path': path, 'content': changed,
                          'expected_version': original['version']}).status_code == 200
        old_turn = client.post(base + '/turns', headers=headers, json={'prompt': 'original prompt'}).json()['turn_id']
        assert 'turn_finished' in client.get(base + f'/turns/{old_turn}/events', headers=headers).text
        assert client.get(base + '/chats', headers=headers).json()[0]['id'] == attempt
        original_history = client.get(base + f'/chats/{attempt}/history', headers=headers).json()
        assert original_history['messages'][0]['content'] == 'original prompt'
        legacy = client.post(base + '/turns', headers=headers, json={'prompt': 'legacy follow up'}).json()['turn_id']
        client.get(base + f'/turns/{legacy}/events', headers=headers)
        assert client.get(base + f'/chats/{attempt}/history', headers=headers).json()['messages'][-2]['content'] == 'legacy follow up'
        chat = client.post(base + '/chats', headers=headers).json()['id']
        chats.append(chat)
        assert client.get(base + f'/chats/{chat}/history', headers=headers).json()['messages'] == []
        turn = client.post(base + f'/chats/{chat}/turns', headers=headers, json={'prompt': 'new prompt'}).json()['turn_id']
        stream = client.get(base + f'/chats/{chat}/turns/{turn}/events', headers=headers).text
        assert 'turn_finished' in stream
        assert stream.index('event: progress_update') < stream.index('event: tool_started') < stream.index('event: tool_finished')
        assert model.inputs[-1] == ['new prompt']
        history = client.get(base + f'/chats/{chat}/history', headers=headers).json()['messages']
        assert [item['role'] for item in history] == ['user', 'progress', 'tool', 'tool', 'assistant']
        assert history[1]['content'] == 'I will inspect the blog.'
        assert history[1]['event_key'].startswith(turn + ':')
        assert any(item['role'] == 'tool' and 'read_file' in item['content'] for item in history)
        assert client.get(base + f'/chats/{attempt}/turns/{turn}/events', headers=headers).status_code == 404
        assert '# shared workspace test' in client.get(base + '/file', headers=headers, params={'path': path}).json()['content']
        turn = client.post(base + f'/chats/{attempt}/turns', headers=headers, json={'prompt': 'follow up'}).json()['turn_id']
        client.get(base + f'/chats/{attempt}/turns/{turn}/events', headers=headers)
        assert model.inputs[-1] == ['original prompt', 'legacy follow up', 'follow up']
        turn = client.post(base + f'/chats/{chat}/turns', headers=headers, json={'prompt': 'fail prompt'}).json()['turn_id']
        assert 'event: error' in client.get(base + f'/chats/{chat}/turns/{turn}/events', headers=headers).text
        client.delete(base, headers=headers)
        assert client.post(base + '/resume', headers=headers).status_code == 200
        restored = client.get(base + f'/chats/{chat}/history', headers=headers).json()['messages']
        assert any(item['role'] == 'tool' for item in restored)
        assert any(item['role'] == 'progress' and item['content'] == 'I will inspect the blog.' for item in restored)
        assert restored[-1]['role'] == 'error'
        assert len(client.get(base + '/chats', headers=headers).json()) == 2
    finally:
        if attempt in manager.attempts:
            manager.close(attempt)
        with open_memory(load_config().checkpoint_database_url, attempt) as memory:
            for chat_id in [attempt] + chats:
                memory.delete_thread(chat_id)
            memory.conn.execute('DELETE FROM agent_workspaces WHERE thread_id = %s', (attempt,))
        subprocess.run(['docker', 'volume', 'rm', volume], check=True, capture_output=True)
