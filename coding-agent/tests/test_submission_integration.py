import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.mark.skipif(os.environ.get('AGENT_POSTGRES_TEST') != '1' or os.environ.get('AGENT_DOCKER_TEST') != '1',
                    reason='PostgreSQL and Docker integration are opt-in')
@pytest.mark.parametrize('fixed', [False, True])
def test_submission_uses_new_challenge_and_returns_saved_report(monkeypatch, tmp_path, fixed):
    from coding_agent import submissions, attempts
    from coding_agent.api import create_app
    from coding_agent.attempts import AttemptManager
    from coding_agent.config import load_config
    from coding_agent.container_workspace import docker
    from coding_agent.memory import open_memory

    seen = []
    actual_judge = submissions.configured_judge
    def judge(config, problem, rubric, events):
        seen.append((problem, rubric, events))
        if os.environ.get('AGENT_LIVE_JUDGE_TEST') == '1' and not fixed:
            return actual_judge(config, problem, rubric, events)
        return {'status': 'ready', 'summary': {'observations': [
            {'area': 'verification', 'finding': 'Behavior checks ran.', 'evidence_ids': ['correctness']}],
            'unresolved': [], 'evidence_gaps': []}, 'usage': {'total': None}}
    monkeypatch.setattr(submissions, 'configured_judge', judge)
    def run_turn(prompt, workspace, memory, chat_id, config, publish):
        publish({'type': 'tool_started', 'name': 'read_file', 'path': 'flaskr/blog.py', 'call_id': 'read'})
        publish({'type': 'tool_finished', 'name': 'read_file', 'path': 'flaskr/blog.py', 'call_id': 'read',
                 'status': 'completed', 'result': 'Example file inspected.'})
        return {'answer': 'I inspected the authorization and search code.'}
    monkeypatch.setattr(attempts, 'run_turn', run_turn)
    manager = AttemptManager()
    client = TestClient(create_app(manager=manager, token='test'))
    headers = {'Authorization': 'Bearer test'}
    assert client.get('/challenges', headers=headers).json()['challenges'][0]['id'] == 'flaskr-secure-search'
    response = client.post('/attempts', headers=headers, json={'challenge_id': 'flaskr-secure-search'})
    assert response.status_code == 201, response.text
    attempt_id = response.json()['attempt_id']
    volume = manager.attempts[attempt_id]['workspace'].volume
    snapshot = None
    try:
        root = Path(__file__).resolve().parents[2]
        reference = tmp_path / 'reference'
        shutil.copytree(root / 'broken-repos/flaskr-secure-search', reference,
                        ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', 'instance', '*.pyc'))
        subprocess.run(['git', 'apply', str(root / 'coding-agent/challenges/flaskr-secure-search/reference.patch')],
                       cwd=reference, check=True, capture_output=True)
        def apply_reference():
            for path in ('flaskr/blog.py', 'flaskr/templates/blog/index.html'):
                current = manager.file(attempt_id, 'read_editor_file', {'path': path})['result']
                result = manager.file(attempt_id, 'write_editor_file', {
                    'path': path, 'content': (reference / path).read_text(encoding='utf-8'),
                    'expected_version': current['version']})
                assert result['status'] == 'completed'
        if fixed:
            apply_reference()
        chat = manager.create_chat(attempt_id)['id']
        manager.start_turn(attempt_id, 'Inspect the authorization and search behavior', chat_id=chat)
        manager.attempts[attempt_id]['thread'].join(10)
        assert not manager.attempts[attempt_id]['busy']
        question = client.get(f'/attempts/{attempt_id}/question', headers=headers).json()
        assert 'search' in question['question'].lower()
        request_id = 'ad08df5b-a9aa-4755-a356-7e6d689616d8'
        response = client.post(f'/attempts/{attempt_id}/submissions', headers=headers, json={'request_id': request_id})
        assert response.status_code == 202, response.text
        submission_id = response.json()['submission_id']
        row = manager._chat_memory(manager.attempts[attempt_id]).conn.execute(
            'SELECT snapshot FROM submissions WHERE id = %s', (submission_id,)).fetchone()
        snapshot = row['snapshot']
        repeated = client.post(f'/attempts/{attempt_id}/submissions', headers=headers, json={'request_id': request_id})
        assert repeated.json()['submission_id'] == submission_id
        if not fixed:
            apply_reference()  # Later workspace edits must not change this submission.
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            result = client.get(f'/attempts/{attempt_id}/submissions/{submission_id}', headers=headers).json()
            if result['status'] in ('completed', 'failed', 'interrupted'):
                break
            time.sleep(0.2)
        assert result['status'] == 'completed', result
        report = result['report']
        assert report['result'] == 'passed' if fixed else report['result'] in ('partially_passed', 'not_passed')
        assert report['process_review']['status'] in ('ready', 'partial'), report['process_review']
        assert seen and 'reference_patch' in seen[0][1]
        assert 'reference_patch' not in repr(report)
    finally:
        if attempt_id in manager.attempts:
            manager.close(attempt_id)
        with open_memory(load_config().checkpoint_database_url, attempt_id) as memory:
            memory.delete_thread(attempt_id)
            memory.conn.execute('DELETE FROM agent_workspaces WHERE thread_id = %s', (attempt_id,))
        if snapshot:
            docker('volume', 'rm', snapshot)
        docker('volume', 'rm', volume)


@pytest.mark.skipif(os.environ.get('AGENT_POSTGRES_TEST') != '1' or os.environ.get('AGENT_DOCKER_TEST') != '1',
                    reason='PostgreSQL and Docker integration are opt-in')
def test_reopening_marks_interrupted_submission_and_stops_its_container():
    from uuid import uuid4
    from coding_agent.attempts import AttemptManager
    from coding_agent.config import load_config
    from coding_agent.container_workspace import IMAGE, docker
    from coding_agent.memory import open_memory

    manager = AttemptManager()
    attempt_id = manager.create('flaskr-secure-search')
    volume = manager.close(attempt_id)
    submission_id = str(uuid4())
    suffix = submission_id.replace('-', '')
    network = 'coding-agent-eval-' + suffix
    candidate = 'coding-agent-candidate-' + suffix
    try:
        with open_memory(load_config().checkpoint_database_url, attempt_id) as memory:
            memory.conn.execute("INSERT INTO submissions (id, attempt_id, request_id, status) VALUES (%s, %s, %s, 'testing')",
                                (submission_id, attempt_id, str(uuid4())))
        docker('network', 'create', '--internal', network)
        docker('run', '-d', '--name', candidate, '--network', network, '--entrypoint', 'sleep', IMAGE, 'infinity')
        manager.resume(attempt_id)
        assert manager.submission(attempt_id, submission_id)['status'] == 'interrupted'
        output = docker('ps', '-a', '--filter', f'name=^/{candidate}$', '--format', '{{.Names}}').stdout
        assert candidate not in output
    finally:
        if attempt_id in manager.attempts:
            manager.close(attempt_id)
        with open_memory(load_config().checkpoint_database_url, attempt_id) as memory:
            memory.delete_thread(attempt_id)
            memory.conn.execute('DELETE FROM agent_workspaces WHERE thread_id = %s', (attempt_id,))
        try:
            docker('rm', '-f', candidate)
        except Exception:
            pass
        try:
            docker('network', 'rm', network)
        except Exception:
            pass
        docker('volume', 'rm', volume)


@pytest.mark.skipif(os.environ.get('AGENT_POSTGRES_TEST') != '1' or os.environ.get('AGENT_DOCKER_TEST') != '1',
                    reason='PostgreSQL and Docker integration are opt-in')
def test_reopening_recovers_a_crash_during_snapshot_preparation():
    from uuid import uuid4
    from coding_agent.attempts import AttemptManager
    from coding_agent.config import load_config
    from coding_agent.container_workspace import IMAGE, docker
    from coding_agent.memory import open_memory
    from coding_agent.submission_snapshot import snapshot_name

    manager = AttemptManager()
    attempt_id = manager.create('flaskr-secure-search')
    attempt = manager.attempts[attempt_id]
    volume, old_container = attempt['workspace'].volume, attempt['workspace'].container
    submission_id = str(uuid4())
    snapshot = snapshot_name(submission_id)
    helper = 'coding-agent-snapshot-' + submission_id.replace('-', '')
    try:
        attempt['memory'].conn.execute("INSERT INTO submissions (id, attempt_id, request_id, snapshot, status) VALUES (%s, %s, %s, %s, 'preparing')",
                                       (submission_id, attempt_id, str(uuid4()), snapshot))
        docker('volume', 'create', snapshot)
        docker('run', '-d', '--name', helper, '--network', 'none', '--mount',
               f'type=volume,source={volume},target=/source,readonly', '--mount',
               f'type=volume,source={snapshot},target=/snapshot', '--entrypoint', 'sleep', IMAGE, 'infinity')
        docker('pause', old_container)
        # Simulate a process crash: release its database connection, leaving Docker resources behind.
        attempt['memory_context'].__exit__(None, None, None)
        del manager.attempts[attempt_id]
        manager.resume(attempt_id)
        assert manager.submission(attempt_id, submission_id)['status'] == 'interrupted'
        assert snapshot not in docker('volume', 'ls', '--format', '{{.Name}}').stdout.splitlines()
        assert helper not in docker('ps', '-a', '--format', '{{.Names}}').stdout.splitlines()
    finally:
        try:
            docker('unpause', old_container)
        except Exception:
            pass
        if attempt_id in manager.attempts:
            manager.close(attempt_id)
        for command in [('rm', '-f', helper), ('unpause', old_container), ('rm', '-f', old_container),
                        ('volume', 'rm', snapshot)]:
            try:
                docker(*command)
            except Exception:
                pass
        with open_memory(load_config().checkpoint_database_url, attempt_id) as memory:
            memory.delete_thread(attempt_id)
            memory.conn.execute('DELETE FROM agent_workspaces WHERE thread_id = %s', (attempt_id,))
        docker('volume', 'rm', volume)


@pytest.mark.skipif(os.environ.get('AGENT_POSTGRES_TEST') != '1' or os.environ.get('AGENT_DOCKER_TEST') != '1',
                    reason='PostgreSQL and Docker integration are opt-in')
def test_submission_without_user_prompts_does_not_invent_process_feedback(monkeypatch):
    from uuid import uuid4
    from coding_agent import submissions
    from coding_agent.attempts import AttemptManager
    from coding_agent.config import load_config
    from coding_agent.container_workspace import docker
    from coding_agent.memory import open_memory

    monkeypatch.setattr(submissions, 'configured_judge', lambda *args: pytest.fail('No prompt was recorded'))
    manager = AttemptManager()
    attempt_id = manager.create('flaskr-secure-search')
    volume = manager.attempts[attempt_id]['workspace'].volume
    snapshot = None
    try:
        submission_id = manager.submit(attempt_id, str(uuid4()))['submission_id']
        row = manager._chat_memory(manager.attempts[attempt_id]).conn.execute(
            'SELECT snapshot FROM submissions WHERE id = %s', (submission_id,)).fetchone()
        snapshot = row['snapshot']
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            result = manager.submission(attempt_id, submission_id)
            if result['status'] in ('completed', 'failed'):
                break
            time.sleep(0.2)
        assert result['status'] == 'completed', result
        assert result['report']['process_review']['status'] == 'unavailable'
        assert 'No user prompts' in result['report']['process_review']['reason']
    finally:
        if attempt_id in manager.attempts:
            manager.close(attempt_id)
        with open_memory(load_config().checkpoint_database_url, attempt_id) as memory:
            memory.delete_thread(attempt_id)
            memory.conn.execute('DELETE FROM agent_workspaces WHERE thread_id = %s', (attempt_id,))
        if snapshot:
            docker('volume', 'rm', snapshot)
        docker('volume', 'rm', volume)
