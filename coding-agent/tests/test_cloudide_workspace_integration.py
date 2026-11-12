import os
import subprocess

import httpx
import pytest
from dotenv import dotenv_values


@pytest.mark.skipif(os.environ.get('CLOUDIDE_INTEGRATION_TEST') != '1', reason='Requires local API, Vite, Docker and PostgreSQL')
def test_cloudide_proxy_saves_and_keeps_attempts_separate():
    from coding_agent.config import load_config
    from coding_agent.memory import open_memory

    token = dotenv_values('.env')['AGENT_API_TOKEN']
    client = httpx.Client(base_url='http://localhost:5174/agent-api', headers={'Authorization': f'Bearer {token}'}, timeout=90)
    attempts = []
    try:
        for _ in range(2):
            response = client.post('/attempts')
            response.raise_for_status()
            attempts.append(response.json()['attempt_id'])
        first, second = attempts
        path = 'flaskr/blog.py'
        assert 'flaskr/' in client.get(f'/attempts/{first}/files').json()['entries']
        original = client.get(f'/attempts/{first}/file', params={'path': path}).json()
        saved = client.put(f'/attempts/{first}/file', json={'path': path, 'content': original['content'] + '\n# local test\n', 'expected_version': original['version']})
        assert saved.status_code == 200
        stale = client.put(f'/attempts/{first}/file', json={'path': path, 'content': 'old draft', 'expected_version': original['version']})
        assert stale.status_code == 409
        assert client.get(f'/attempts/{first}/file', params={'path': path}).json()['content'].endswith('# local test\n')
        assert client.get(f'/attempts/{second}/file', params={'path': path}).json()['content'] == original['content']
    finally:
        for attempt in attempts:
            response = client.delete(f'/attempts/{attempt}')
            if response.status_code == 200:
                volume = response.json()['workspace_volume']
                subprocess.run(['docker', 'volume', 'rm', volume], check=True, capture_output=True)
                with open_memory(load_config().checkpoint_database_url, attempt) as memory:
                    memory.delete_thread(attempt)
                    memory.conn.execute('DELETE FROM agent_workspaces WHERE thread_id = %s', (attempt,))
        client.close()
