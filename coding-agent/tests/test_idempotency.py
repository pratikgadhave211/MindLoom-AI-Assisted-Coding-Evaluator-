import os
import subprocess
import threading
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def test_chat_prompt_accepts_request_id():
    from coding_agent.api import Prompt

    request_id = str(uuid4())
    assert Prompt(prompt='hello', request_id=request_id).request_id == request_id


@pytest.mark.skipif(os.environ.get('AGENT_POSTGRES_TEST') != '1' or os.environ.get('AGENT_DOCKER_TEST') != '1',
                    reason='Docker and PostgreSQL integration are opt-in')
def test_retries_reuse_turn_and_survive_reopening(monkeypatch):
    from coding_agent import attempts
    from coding_agent.api import create_app
    from coding_agent.config import load_config
    from coding_agent.memory import open_memory

    entered = threading.Event()
    release = threading.Event()
    calls = []

    def run(prompt, workspace, memory, chat, config, publish):
        calls.append(prompt)
        entered.set()
        assert release.wait(15)
        if prompt == 'fail logging':
            publish({'type': 'tool_started', 'name': 'read_file'})
        return {'answer': 'done'}

    monkeypatch.setattr(attempts, 'run_turn', run)
    manager = attempts.AttemptManager()
    client = TestClient(create_app(manager=manager, token='test'))
    headers = {'Authorization': 'Bearer test'}
    attempt = client.post('/attempts', headers=headers).json()['attempt_id']
    volume = manager.attempts[attempt]['workspace'].volume
    chat = attempt
    request_id = str(uuid4())
    try:
        base = f'/attempts/{attempt}'
        client.get(base + '/chats', headers=headers)
        url = base + f'/chats/{chat}/turns'
        payload = {'prompt': 'fix login', 'request_id': request_id}
        first = client.post(url, headers=headers, json=payload)
        assert first.status_code == 202
        assert entered.wait(5)
        again = client.post(url, headers=headers, json=payload)
        assert again.status_code == 202
        assert again.json()['turn_id'] == first.json()['turn_id']
        assert again.json()['status'] == 'running'
        assert client.post(url, headers=headers, json={**payload, 'prompt': 'different'}).status_code == 409
        other_chat = client.post(base + '/chats', headers=headers)
        assert other_chat.status_code == 409
        release.set()
        turn = first.json()['turn_id']
        client.get(base + f'/chats/{chat}/turns/{turn}/events', headers=headers)
        finished = client.post(url, headers=headers, json=payload).json()
        assert finished == {'turn_id': turn, 'status': 'completed'}
        assert calls == ['fix login']
        assert client.post(url, headers=headers, json={'prompt': 'hello', 'request_id': 'not-a-uuid'}).status_code == 400
        other = client.post(base + '/chats', headers=headers).json()['id']
        assert client.post(base + f'/chats/{other}/turns', headers=headers, json=payload).status_code == 409
        interrupted_id = str(uuid4())
        interrupted_turn = str(uuid4())
        manager._chat_memory(manager.attempts[attempt]).conn.execute(
            "INSERT INTO agent_requests (request_id, attempt_id, chat_id, prompt, turn_id, status) VALUES (%s, %s, %s, %s, %s, 'running')",
            (interrupted_id, attempt, chat, 'interrupted', interrupted_turn))
        client.delete(base, headers=headers)
        assert client.post(base + '/resume', headers=headers).status_code == 200
        assert client.post(url, headers=headers, json=payload).json() == finished
        assert client.post(url, headers=headers, json={'prompt': 'interrupted', 'request_id': interrupted_id}).json() == {
            'turn_id': interrupted_turn, 'status': 'interrupted'}
        assert calls == ['fix login']
        original_append = attempts.append_chat_event

        def fail_tool_event(memory, chat_id, turn_id, event):
            if event['type'] == 'tool_started':
                raise RuntimeError('history unavailable')
            return original_append(memory, chat_id, turn_id, event)

        monkeypatch.setattr(attempts, 'append_chat_event', fail_tool_event)
        logging_payload = {'prompt': 'fail logging', 'request_id': str(uuid4())}
        logging_turn = client.post(url, headers=headers, json=logging_payload).json()['turn_id']
        client.get(base + f'/chats/{chat}/turns/{logging_turn}/events', headers=headers)
        assert client.post(url, headers=headers, json=logging_payload).json()['status'] == 'interrupted'
        assert calls == ['fix login', 'fail logging']
    finally:
        release.set()
        if attempt in manager.attempts:
            thread = manager.attempts[attempt].get('thread')
            if thread:
                thread.join(timeout=20)
            manager.close(attempt)
        with open_memory(load_config().checkpoint_database_url, attempt) as memory:
            memory.delete_thread(chat)
            memory.conn.execute('DELETE FROM agent_workspaces WHERE thread_id = %s', (attempt,))
        subprocess.run(['docker', 'volume', 'rm', volume], check=True, capture_output=True)
