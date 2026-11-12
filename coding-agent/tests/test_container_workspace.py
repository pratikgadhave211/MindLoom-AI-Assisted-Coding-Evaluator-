import json
import io
import threading
from types import SimpleNamespace

import pytest
from coding_agent import container_workspace


def test_workspace_launch_enables_outbound_network(monkeypatch):
    calls = []
    monkeypatch.setattr(container_workspace, 'docker', lambda *args: calls.append(args))
    attempt = container_workspace.Attempt(container='test-container', volume='test-volume')
    container_workspace.launch_container(attempt)
    args = calls[0]
    assert args[args.index('--network') + 1] == 'bridge'
    assert '--read-only' in args


def test_runner_routes_reads_and_uses_fixed_test_command(monkeypatch):
    calls = []

    def fake_run(attempt, args, input_text=None, output_limit=container_workspace.OUTPUT_LIMIT):
        calls.append((args, input_text))
        if input_text:
            return {"output": json.dumps({"status": "completed", "result": "file content"}), "exit_code": 0, "timed_out": False, "truncated": False}
        return {"output": "passed", "exit_code": 0, "timed_out": False, "truncated": False}

    monkeypatch.setattr(container_workspace, "run_in_container", fake_run)
    attempt = SimpleNamespace(container="attempt-1", active=True)
    read = container_workspace.run_workspace_tool(attempt, "read_file", {"path": "app.py"})
    tests = container_workspace.run_workspace_tool(attempt, "run_tests", {})
    assert read["result"] == "file content"
    assert tests["exit_code"] == 0
    assert calls[1][0] == ["python", "-m", "pytest", "-q"]


def test_command_never_runs_on_host(monkeypatch):
    calls = []

    def fake_run(attempt, args, input_text=None):
        calls.append(args)
        return {"output": "ok", "exit_code": 0, "timed_out": False, "truncated": False}

    monkeypatch.setattr(container_workspace, "run_in_container", fake_run)
    attempt = SimpleNamespace(container="attempt-1", active=True)
    result = container_workspace.run_workspace_tool(attempt, "run_command", {"command": "echo hello"})
    assert calls == [["sh", "-c", "echo hello"]]
    assert result["status"] == "completed"


def test_input_write_does_not_block_starting_timeout(monkeypatch):
    started_waiting = threading.Event()
    class Input:
        def write(self, data):
            if not started_waiting.wait(0.5):
                raise RuntimeError("Input blocked before timeout started")
        def close(self):
            pass
    class Process:
        stdin = Input()
        stdout = io.BytesIO(b"ok")
        returncode = 0
        def wait(self, timeout=None):
            started_waiting.set()
            return 0
    monkeypatch.setattr(container_workspace.subprocess, "Popen", lambda *a, **k: Process())
    result = container_workspace.run_in_container(SimpleNamespace(container="test", active=True), ["test"], "x" * 100000)
    assert result["exit_code"] == 0


def test_start_cleans_up_after_interrupt(monkeypatch, tmp_path):
    template = tmp_path / "template"
    template.mkdir()
    calls = []
    def fake_docker(*args):
        calls.append(args)
        if args[0] == "run":
            raise KeyboardInterrupt()
    monkeypatch.setattr(container_workspace, "docker", fake_docker)
    with pytest.raises(KeyboardInterrupt):
        container_workspace.start_workspace(template)
    assert any(call[:2] == ("rm", "-f") for call in calls)
    assert any(call[:2] == ("volume", "rm") for call in calls)


def test_resume_rejects_arbitrary_volume_names():
    with pytest.raises(ValueError, match="Invalid saved workspace"):
        container_workspace.resume_workspace("someone-else-volume")
