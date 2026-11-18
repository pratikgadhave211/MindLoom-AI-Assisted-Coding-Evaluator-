import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest


def test_checks_run_candidate_and_judge_in_separate_networked_containers(monkeypatch):
    from coding_agent import submission_tests
    calls = []
    monkeypatch.setattr(submission_tests, 'docker', lambda *args: calls.append(args) or SimpleNamespace(stdout=''))
    def run(args, **kwargs):
        calls.append(tuple(args))
        return SimpleNamespace(returncode=0, stdout=json.dumps({'status': 'completed', 'behaviors': [
            {'name': name, 'status': 'passed'} for name in submission_tests.BEHAVIORS]}))
    monkeypatch.setattr(submission_tests.subprocess, 'run', run)
    result = submission_tests.run_checks('coding-agent-submission-' + 'a' * 32)
    assert result['status'] == 'completed'
    candidate = next(call for call in calls if call[0] == 'run')
    assert '--read-only' in candidate and not any('hidden_http' in arg for arg in candidate)
    assert any(call[:2] == ('network', 'rm') for call in calls)
    assert any(call[:2] == ('rm', '-f') for call in calls)


def test_invalid_snapshot_does_not_call_docker(monkeypatch):
    from coding_agent import submission_tests
    monkeypatch.setattr(submission_tests, 'docker', lambda *args: (_ for _ in ()).throw(AssertionError()))
    assert submission_tests.run_checks('other-volume')['status'] == 'could_not_evaluate'


def test_visible_tests_run_without_network_and_return_status_only(monkeypatch):
    from coding_agent import submission_tests
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(submission_tests.subprocess, 'run', run)
    monkeypatch.setattr(submission_tests, 'docker', lambda *args: None)
    result = submission_tests.run_visible_checks('coding-agent-submission-' + 'a' * 32)
    assert result == {'status': 'failed'}
    assert '--network' in calls[0] and calls[0][calls[0].index('--network') + 1] == 'none'


def test_solution_result_distinguishes_failed_checks_and_runner_errors():
    from coding_agent.submission_tests import solution_result
    assert solution_result({'status': 'could_not_evaluate'}) == 'could_not_evaluate'
    assert solution_result({'status': 'completed', 'passed': 3, 'total': 3,
                            'visible_tests': {'status': 'passed'}}) == 'passed'
    assert solution_result({'status': 'completed', 'passed': 2, 'total': 3,
                            'visible_tests': {'status': 'passed'}}) == 'partially_passed'
    assert solution_result({'status': 'completed', 'passed': 3, 'total': 3,
                            'visible_tests': {'status': 'could_not_evaluate'}}) == 'could_not_evaluate'


@pytest.mark.skipif(os.environ.get('AGENT_DOCKER_TEST') != '1', reason='Docker integration is opt-in')
@pytest.mark.parametrize('fixed', [False, True])
def test_real_submission_checks_distinguish_broken_and_correct_code(tmp_path, fixed):
    from coding_agent.container_workspace import docker, start_workspace, stop_workspace
    from coding_agent.submission_snapshot import create_snapshot
    from coding_agent.submission_tests import run_checks
    root = Path(__file__).resolve().parents[2]
    work = tmp_path / 'template'
    shutil.copytree(root / 'broken-repos/flaskr-secure-search', work,
                    ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', '*.pyc'))
    if fixed:
        subprocess.run(['git', 'apply', str(root / 'coding-agent/challenges/flaskr-secure-search/reference.patch')],
                       cwd=work, check=True, capture_output=True)
    attempt = start_workspace(work)
    snapshot = None
    try:
        snapshot = create_snapshot(attempt)
        result = run_checks(snapshot)
        assert result['status'] == 'completed', result
        assert (result['passed'] == result['total']) is fixed
    finally:
        stop_workspace(attempt)
        if snapshot:
            docker('volume', 'rm', snapshot)
        docker('volume', 'rm', attempt.volume)
