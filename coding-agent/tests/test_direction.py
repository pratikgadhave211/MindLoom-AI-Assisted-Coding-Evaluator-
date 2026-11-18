import os
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.mark.parametrize('score', [None, True, -0.1, 1.1, '0.5'])
def test_direction_rejects_invalid_provider_output(monkeypatch, score):
    from coding_agent.jev import check_assessment

    monkeypatch.setattr('coding_agent.jev.httpx.post', lambda *args, **kwargs: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {'answers': {'direction': {'noul': score}}}))
    result = check_assessment('problem', 'approach', 'prompt', 1, 10, 'fake-key', None)
    assert result == {'direction': None, 'code': None}


def test_one_jev_request_assesses_prompt_and_code(monkeypatch):
    from coding_agent.jev import check_assessment

    calls = []
    def post(url, headers, json, timeout):
        calls.append(json)
        assert set(json['questions']) == {'direction', 'code'}
        assert json['state']['prompt_number'] == 5
        assert json['state']['code_context']['current']['app.py'] == 'current'
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'answers': {
            'direction': {'noul': 0.8}, 'code': {'noul': 0.3}}})
    monkeypatch.setattr('coding_agent.jev.httpx.post', post)
    result = check_assessment('problem', 'approach', 'inspect', 5, 10, 'fake-key',
                              {'current': {'app.py': 'current'}})
    assert len(calls) == 1
    assert result == {'direction': 80, 'code': 30}


def test_missing_code_and_invalid_one_answer_do_not_erase_direction(monkeypatch):
    from coding_agent.jev import check_assessment

    def post(url, headers, json, timeout):
        assert set(json['questions']) == {'direction'}
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {'answers': {'direction': {'noul': 0.7}}})
    monkeypatch.setattr('coding_agent.jev.httpx.post', post)
    assert check_assessment('p', 'a', 'prompt', 1, 10, 'key', None) == {'direction': 70, 'code': None}


def test_invalid_code_answer_does_not_erase_valid_direction(monkeypatch):
    from coding_agent.jev import check_assessment

    monkeypatch.setattr('coding_agent.jev.httpx.post', lambda *args, **kwargs: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {'answers': {'direction': {'noul': 0.7}, 'code': None}}))
    result = check_assessment('p', 'a', 'prompt', 1, 10, 'key', {'current': {}})
    assert result == {'direction': 70, 'code': None}


def test_later_file_edit_marks_old_code_assessment_stale():
    from coding_agent.direction import latest_code

    rows = [{'id': 1, 'event': {'type': 'prompt_accepted', 'turn_id': 'turn'}},
            {'id': 2, 'event': {'type': 'file_saved', 'path': 'app.py'}},
            {'id': 3, 'event': {'type': 'direction_result', 'turn_id': 'turn', 'code_status': 'ready',
                                'code_score': 80, 'workspace_revision': 2}}]
    assert latest_code(rows) == {'status': 'ready', 'score': 80}
    rows.append({'id': 4, 'event': {'type': 'file_saved', 'path': 'app.py'}})
    assert latest_code(rows) == {'status': 'stale', 'score': None}


def test_slower_old_code_assessment_does_not_replace_current_one():
    from coding_agent.direction import latest_code

    rows = [{'id': 1, 'event': {'type': 'prompt_accepted', 'turn_id': 'turn'}},
            {'id': 2, 'event': {'type': 'file_saved'}},
            {'id': 3, 'event': {'type': 'direction_result', 'turn_id': 'turn', 'code_status': 'ready',
                                'code_score': 80, 'workspace_revision': 2}},
            {'id': 4, 'event': {'type': 'direction_result', 'turn_id': 'turn', 'code_status': 'ready',
                                'code_score': 20, 'workspace_revision': 0}}]
    assert latest_code(rows) == {'status': 'ready', 'score': 80}


def test_code_context_contains_original_reference_and_current(monkeypatch, tmp_path):
    from coding_agent import direction

    original = tmp_path / 'app.py'
    original.write_text('broken', encoding='utf-8')
    reference = tmp_path / 'fix.patch'
    reference.write_text('reference fix', encoding='utf-8')
    monkeypatch.setattr(direction, 'ORIGINAL_ROOT', tmp_path)
    monkeypatch.setattr(direction, 'CHALLENGE_ROOT', tmp_path)
    monkeypatch.setattr(direction, 'run_workspace_tool', lambda *args: {
        'status': 'completed', 'result': {'content': 'user edit', 'version': 'v1'}})
    context = direction.load_code_context({'expected_files': ['app.py'], 'reference_patch': 'fix.patch'}, object())
    assert context == {'original': {'app.py': 'broken'}, 'reference_patch': 'reference fix',
                       'current': {'app.py': 'user edit'}}


def test_code_snapshot_failure_does_not_erase_prompt_assessment(monkeypatch):
    from coding_agent import direction

    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    rows = [{'id': 1, 'event': {'type': 'prompt_accepted', 'turn_id': 'turn'}}]
    captured = []
    monkeypatch.setattr(direction.psycopg, 'connect', lambda *args, **kwargs: Connection())
    monkeypatch.setattr(direction, 'load_challenge', lambda: {'problem': 'p', 'author_approach': 'a', 'prompt_limit': 10})
    monkeypatch.setattr(direction, 'get_evidence', lambda *args: {'events': rows})
    monkeypatch.setattr(direction, 'load_code_context', lambda *args: (_ for _ in ()).throw(RuntimeError('unavailable')))
    monkeypatch.setattr(direction, 'check_assessment', lambda *args: {'direction': 70, 'code': None} if args[-1] is None else None)
    monkeypatch.setattr(direction, 'record_evidence', lambda db, attempt, key, event: captured.append(event))
    direction.run_direction_check('db', 'attempt', 'turn', 'prompt', 'key', object())
    assert captured[0]['status'] == 'ready' and captured[0]['score'] == 70
    assert captured[0]['code_status'] == 'unavailable'


def test_late_direction_result_never_replaces_newer_prompt():
    from coding_agent.direction import latest_direction

    rows = [{'event': {'type': 'prompt_accepted', 'turn_id': 'first'}},
            {'event': {'type': 'prompt_accepted', 'turn_id': 'second'}},
            {'event': {'type': 'direction_result', 'turn_id': 'second', 'status': 'ready', 'score': 80}},
            {'event': {'type': 'direction_result', 'turn_id': 'first', 'status': 'ready', 'score': 20}}]
    assert latest_direction(rows)['score'] == 80
    assert latest_direction(rows[:2]) == {'status': 'pending', 'score': None}


def test_timeout_is_recorded_without_secret_or_challenge_text(monkeypatch):
    from coding_agent import direction

    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    captured = []
    monkeypatch.setattr(direction.psycopg, 'connect', lambda *args, **kwargs: Connection())
    monkeypatch.setattr(direction, 'load_challenge', lambda: {'problem': 'private problem', 'author_approach': 'private fix', 'prompt_limit': 10})
    monkeypatch.setattr(direction, 'get_evidence', lambda *args: {'events': [
        {'event': {'type': 'prompt_accepted', 'turn_id': 'turn'}}]})
    monkeypatch.setattr(direction, 'check_assessment', lambda *args: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(direction, 'record_evidence', lambda db, attempt, key, event: captured.append(event))
    direction.run_direction_check('database', 'attempt', 'turn', 'private prompt', 'secret-key')
    assert captured[0]['status'] == 'unavailable'
    assert captured[0]['score'] is None
    assert all(secret not in repr(captured) for secret in ('private', 'secret-key'))


def test_direction_runs_in_background_without_blocking_agent(monkeypatch):
    from contextlib import nullcontext
    from threading import Event
    from coding_agent import attempts

    started, release = Event(), Event()
    manager = attempts.AttemptManager()
    config = SimpleNamespace(jev_api_key='fake-key', checkpoint_database_url='db')
    manager.attempts['attempt'] = {'workspace': SimpleNamespace(active=True), 'memory': object(),
                                   'config': config, 'busy': False, 'turns': {}, 'chats_enabled': False}
    monkeypatch.setattr(manager, '_chat_memory', lambda attempt: SimpleNamespace(conn=SimpleNamespace(transaction=nullcontext)))
    monkeypatch.setattr(attempts, 'record_evidence', lambda *args: None)
    monkeypatch.setattr(attempts, 'run_turn', lambda *args: {'answer': 'done'})

    def slow_direction(*args):
        started.set()
        release.wait(5)

    monkeypatch.setattr(attempts, 'run_direction_check', slow_direction)
    try:
        manager.start_turn('attempt', 'inspect')
        assert started.wait(2)
        manager.attempts['attempt']['thread'].join(2)
        assert not manager.attempts['attempt']['thread'].is_alive()
    finally:
        release.set()


@pytest.mark.skipif(os.environ.get('AGENT_POSTGRES_TEST') != '1', reason='PostgreSQL integration is opt-in')
def test_direction_persists_across_postgres_connections(monkeypatch):
    from coding_agent import direction
    from coding_agent.config import load_config
    from coding_agent.memory import get_evidence, open_memory, record_evidence, save_workspace

    attempt = str(uuid4())
    url = load_config().checkpoint_database_url
    with open_memory(url, attempt) as memory:
        save_workspace(memory, attempt, 'test-volume')
        record_evidence(memory, attempt, 'prompt:first', {'type': 'prompt_accepted', 'turn_id': 'first'})
        record_evidence(memory, attempt, 'prompt:second', {'type': 'prompt_accepted', 'turn_id': 'second'})
        monkeypatch.setattr(direction, 'load_challenge', lambda: {'problem': 'problem', 'author_approach': 'fix', 'prompt_limit': 10})
        seen = []
        def check(problem, approach, prompt, number, limit, key, code_context):
            seen.append(number)
            return {'direction': 80 if number == 2 else 20, 'code': None}
        monkeypatch.setattr(direction, 'check_assessment', check)
        try:
            direction.run_direction_check(url, attempt, 'second', 'second prompt', 'fake-key')
            direction.run_direction_check(url, attempt, 'first', 'first prompt', 'fake-key')
            evidence = get_evidence(memory, attempt)
            assert seen == [2, 1]
            assert direction.latest_direction(evidence['events']) == {'status': 'ready', 'score': 80}
            results = repr([row['event'] for row in evidence['events'] if row['event']['type'] == 'direction_result'])
            assert 'first prompt' not in results and 'second prompt' not in results
        finally:
            memory.conn.execute('DELETE FROM agent_workspaces WHERE thread_id = %s', (attempt,))


@pytest.mark.skipif(os.environ.get('AGENT_POSTGRES_TEST') != '1' or os.environ.get('AGENT_DOCKER_TEST') != '1',
                    reason='PostgreSQL and Docker integration are opt-in')
def test_combined_assessment_reads_completed_workspace(monkeypatch):
    import subprocess
    import time
    from coding_agent import attempts, direction
    from coding_agent.config import load_config
    from coding_agent.container_workspace import run_workspace_tool
    from coding_agent.memory import open_memory

    monkeypatch.setenv('TYPESAFE_API_KEY', 'fake-key')
    requests = []
    def assess(problem, approach, prompt, number, limit, key, context):
        requests.append(context)
        return {'direction': 80, 'code': 90}
    monkeypatch.setattr(direction, 'check_assessment', assess)
    def run(prompt, workspace, memory, chat, config, publish):
        path = 'flaskr/blog.py'
        previous = run_workspace_tool(workspace, 'read_editor_file', {'path': path})['result']
        changed = previous['content'].replace('post = get_post(id)', 'post = get_post(id, check_author=True)')
        assert changed != previous['content']
        publish({'type': 'tool_started', 'name': 'edit_file', 'path': path, 'call_id': 'edit'})
        result = run_workspace_tool(workspace, 'write_editor_file',
                                    {'path': path, 'content': changed, 'expected_version': previous['version']})
        assert result['status'] == 'completed'
        publish({'type': 'tool_finished', 'name': 'edit_file', 'path': path, 'call_id': 'edit', 'status': 'completed'})
        return {'answer': 'done'}
    monkeypatch.setattr(attempts, 'run_turn', run)
    manager = attempts.AttemptManager()
    attempt = manager.create()
    volume = manager.attempts[attempt]['workspace'].volume
    try:
        chat = manager.create_chat(attempt)['id']
        manager.start_turn(attempt, 'Inspect post ownership', chat_id=chat)
        manager.attempts[attempt]['thread'].join(20)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            evidence = manager.evidence(attempt)
            if any(row['event'].get('type') == 'direction_result' for row in evidence['events']):
                break
            time.sleep(0.1)
        assert len(requests) == 1
        assert 'check_author=True' in requests[0]['current']['flaskr/blog.py']
        assert direction.latest_direction(evidence['events']) == {'status': 'ready', 'score': 80}
        assert direction.latest_code(evidence['events']) == {'status': 'ready', 'score': 90}
        assert 'reference_patch' not in repr(evidence)
        assert manager.predictometer(attempt)['status'] == 'ready'
        current = manager.file(attempt, 'read_editor_file', {'path': 'flaskr/blog.py'})['result']
        saved = manager.file(attempt, 'write_editor_file', {'path': 'flaskr/blog.py',
                             'content': current['content'] + '\n# later edit\n', 'expected_version': current['version']})
        assert saved['status'] == 'completed'
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if len(requests) >= 2 and direction.latest_code(manager.evidence(attempt)['events'])['status'] == 'ready':
                break
            time.sleep(0.1)
        assert len(requests) >= 2
        assert '# later edit' in requests[-1]['current']['flaskr/blog.py']
        assert direction.latest_code(manager.evidence(attempt)['events']) == {'status': 'ready', 'score': 90}
    finally:
        if attempt in manager.attempts:
            manager.close(attempt)
        with open_memory(load_config().checkpoint_database_url, attempt) as memory:
            memory.delete_thread(attempt)
            memory.conn.execute('DELETE FROM agent_workspaces WHERE thread_id = %s', (attempt,))
        subprocess.run(['docker', 'volume', 'rm', volume], check=True, capture_output=True)
