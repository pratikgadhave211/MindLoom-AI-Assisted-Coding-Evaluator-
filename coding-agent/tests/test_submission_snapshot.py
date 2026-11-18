import subprocess
import os
from types import SimpleNamespace
import pytest


def test_snapshot_uses_separate_read_only_source_and_isolated_copy(monkeypatch):
    from coding_agent import submission_snapshot
    calls = []
    monkeypatch.setattr(submission_snapshot, 'docker', lambda *args: calls.append(args) or SimpleNamespace(stdout=''))
    source = 'coding-agent-' + 'a' * 32 + '-workspace'
    attempt = SimpleNamespace(container='workspace-container', volume=source)
    snapshot = submission_snapshot.create_snapshot(attempt)
    assert snapshot.startswith('coding-agent-submission-')
    run = next(call for call in calls if call[0] == 'run')
    assert '--network' in run and run[run.index('--network') + 1] == 'none'
    assert f'type=volume,source={source},target=/source,readonly' in run
    assert f'type=volume,source={snapshot},target=/snapshot' in run
    assert ('pause', 'workspace-container') in calls
    assert ('unpause', 'workspace-container') in calls


def test_snapshot_failure_removes_only_new_volume(monkeypatch):
    from coding_agent import submission_snapshot
    calls = []
    def docker(*args):
        calls.append(args)
        if args[0] == 'run':
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(stdout='')
    monkeypatch.setattr(submission_snapshot, 'docker', docker)
    source = 'coding-agent-' + 'a' * 32 + '-workspace'
    with pytest.raises(RuntimeError, match='snapshot'):
        submission_snapshot.create_snapshot(SimpleNamespace(container='workspace-container', volume=source))
    removed = [call[2] for call in calls if call[:2] == ('volume', 'rm')]
    assert len(removed) == 1 and removed[0] != source
    assert ('unpause', 'workspace-container') in calls


def test_snapshot_rejects_arbitrary_source_volume():
    from coding_agent.submission_snapshot import create_snapshot
    with pytest.raises(ValueError):
        create_snapshot(SimpleNamespace(container='workspace-container', volume='another-volume'))


def test_snapshot_name_is_bound_to_submission_for_interruption_cleanup():
    from coding_agent.submission_snapshot import snapshot_name
    assert snapshot_name('d759a7eb-c520-4f09-9864-94679f9d9650') == 'coding-agent-submission-d759a7ebc5204f09986494679f9d9650'
    with pytest.raises(ValueError):
        snapshot_name('not-a-uuid')


def test_snapshot_rejects_a_workspace_mounted_by_another_running_container(monkeypatch):
    from coding_agent import submission_snapshot
    def docker(*args):
        if args[0] == 'ps':
            return SimpleNamespace(stdout='workspace-container\nother-container\n')
        pytest.fail('Must not create a snapshot while another container can edit the workspace')
    monkeypatch.setattr(submission_snapshot, 'docker', docker)
    with pytest.raises(ValueError, match='Another container'):
        submission_snapshot.create_snapshot(SimpleNamespace(container='workspace-container',
            volume='coding-agent-' + 'a' * 32 + '-workspace'))


@pytest.mark.skipif(os.environ.get('AGENT_DOCKER_TEST') != '1', reason='Docker integration is opt-in')
def test_docker_snapshot_is_unchanged_after_workspace_edit(tmp_path):
    from coding_agent.container_workspace import IMAGE, docker, run_workspace_tool, start_workspace, stop_workspace
    from coding_agent.submission_snapshot import create_snapshot

    template = tmp_path / 'template'
    template.mkdir()
    (template / 'app.py').write_text('before', encoding='utf-8')
    attempt = start_workspace(template)
    snapshot = None
    try:
        snapshot = create_snapshot(attempt)
        edit = run_workspace_tool(attempt, 'edit_file', {'path': 'app.py', 'old_text': 'before', 'new_text': 'after'})
        assert edit['status'] == 'completed'
        result = docker('run', '--rm', '--network', 'none', '--mount',
                        f'type=volume,source={snapshot},target=/snapshot,readonly', '--entrypoint', 'python',
                        IMAGE, '-c', "print(open('/snapshot/app.py').read())")
        assert result.stdout.strip() == 'before'
    finally:
        stop_workspace(attempt)
        if snapshot:
            docker('volume', 'rm', snapshot)
        docker('volume', 'rm', attempt.volume)
