import os
import subprocess
from pathlib import Path

import pytest

from coding_agent.container_workspace import start_workspace, stop_workspace, run_workspace_tool


@pytest.mark.skipif(os.environ.get("AGENT_DOCKER_TEST") != "1", reason="Docker integration is opt-in")
def test_workspace_edit_command_and_tests_are_isolated(tmp_path):
    template = tmp_path / "template"
    template.mkdir()
    (template / "test_demo.py").write_text("def test_result():\n    assert 1 == 2\n", encoding="utf-8")
    (template / "quotes.txt").write_text('"' * 60000, encoding="utf-8")
    first = start_workspace(template)
    second = start_workspace(template)
    try:
        initial = run_workspace_tool(first, "run_tests", {})
        assert initial["exit_code"] != 0
        edit = run_workspace_tool(first, "edit_file", {"path": "test_demo.py", "old_text": "1 == 2", "new_text": "1 == 1"})
        assert edit["status"] == "completed", edit
        assert run_workspace_tool(first, "run_tests", {})["exit_code"] == 0
        assert "1 == 2" in run_workspace_tool(second, "read_file", {"path": "test_demo.py"})["result"]
        assert "1 == 2" in (template / "test_demo.py").read_text(encoding="utf-8")
        command = run_workspace_tool(first, "run_command", {"command": "printf hello"})
        assert command["exit_code"] == 0 and "hello" in command["result"]
        assert len(run_workspace_tool(first, "read_file", {"path": "quotes.txt"})["result"]) == 60000
        large_output = run_workspace_tool(first, "run_command", {"command": "python -c 'print(\"x\" * 100000)'"})
        assert large_output["truncated"] and len(large_output["output"].encode("utf-8")) <= 65536
        boundary = run_workspace_tool(first, "run_command", {"command": "set -e; test \"$(id -u)\" != 0; test ! -S /var/run/docker.sock; test ! -e /root/.env; test -z \"$OPENROUTER_API_KEY\""})
        assert boundary["exit_code"] == 0
    finally:
        stop_workspace(first)
        stop_workspace(second)
        subprocess.run(["docker", "volume", "rm", first.volume, second.volume], check=True, capture_output=True)


@pytest.mark.skipif(os.environ.get("AGENT_DOCKER_TEST") != "1", reason="Docker integration is opt-in")
def test_fake_model_can_edit_and_verify_in_container(tmp_path):
    from langchain_core.messages import AIMessage
    from coding_agent.graph import build_graph

    template = tmp_path / "template"
    template.mkdir()
    (template / "test_demo.py").write_text("def test_result():\n    assert 1 == 2\n", encoding="utf-8")
    attempt = start_workspace(template)
    class Model:
        def __init__(self):
            self.count = 0
        def invoke(self, messages):
            self.count += 1
            if self.count == 1:
                return AIMessage(content="", tool_calls=[
                    {"id": "read", "name": "read_file", "args": {"path": "test_demo.py"}},
                    {"id": "before", "name": "run_tests", "args": {}},
                ])
            if self.count == 2:
                return AIMessage(content="", tool_calls=[{"id": "edit", "name": "edit_file", "args": {"path": "test_demo.py", "old_text": "1 == 2", "new_text": "1 == 1"}}])
            if self.count == 3:
                return AIMessage(content="", tool_calls=[{"id": "after", "name": "run_tests", "args": {}}])
            return AIMessage(content="The updated test passed.")
    try:
        result = build_graph(Model(), workspace=attempt).invoke({"prompt": "Fix the test"})
        calls = {call["id"]: call for call in result["tool_calls"]}
        assert calls["before"]["status"] == "error"
        assert calls["edit"]["status"] == "completed"
        assert calls["after"]["status"] == "completed"
        assert result["answer"] == "The updated test passed."
    finally:
        stop_workspace(attempt)
        subprocess.run(["docker", "volume", "rm", attempt.volume], check=True, capture_output=True)


@pytest.mark.skipif(os.environ.get("AGENT_DOCKER_TEST") != "1", reason="Docker integration is opt-in")
def test_timeout_stops_the_attempt(tmp_path, monkeypatch):
    from coding_agent import container_workspace

    template = tmp_path / "template"
    template.mkdir()
    attempt = start_workspace(template)
    monkeypatch.setattr(container_workspace, "COMMAND_TIMEOUT", 1)
    try:
        result = run_workspace_tool(attempt, "run_command", {"command": "sleep 60 & wait"})
        assert result["timed_out"] is True
        assert not attempt.active
        assert run_workspace_tool(attempt, "run_command", {"command": "echo no"})["status"] == "error"
    finally:
        stop_workspace(attempt)
        subprocess.run(["docker", "volume", "rm", attempt.volume], check=True, capture_output=True)


@pytest.mark.skipif(os.environ.get("AGENT_DOCKER_TEST") != "1", reason="Docker integration is opt-in")
def test_timeout_applies_when_container_does_not_read_large_input(tmp_path, monkeypatch):
    from coding_agent import container_workspace

    template = tmp_path / "template"
    template.mkdir()
    attempt = start_workspace(template)
    monkeypatch.setattr(container_workspace, "COMMAND_TIMEOUT", 1)
    try:
        result = container_workspace.run_in_container(attempt, ["sh", "-c", "sleep 60"], "x" * 1000000)
        assert result["timed_out"] is True
        assert not attempt.active
    finally:
        stop_workspace(attempt)
        subprocess.run(["docker", "volume", "rm", attempt.volume], check=True, capture_output=True)


@pytest.mark.skipif(os.environ.get("AGENT_DOCKER_TEST") != "1", reason="Docker integration is opt-in")
def test_real_flask_challenge_loads_and_runs_tests():
    template = Path(__file__).resolve().parents[2] / "broken-repos" / "broken-flaskr-blog"
    attempt = start_workspace(template)
    try:
        assert "flaskr/" in run_workspace_tool(attempt, "list_files", {"path": "."})["result"]
        result = run_workspace_tool(attempt, "run_tests", {})
        assert result["exit_code"] is not None
        assert "No module named" not in result["output"]
        assert "passed" in result["output"] or "failed" in result["output"].lower()
    finally:
        stop_workspace(attempt)
        subprocess.run(["docker", "volume", "rm", attempt.volume], check=True, capture_output=True)


@pytest.mark.skipif(os.environ.get("AGENT_DOCKER_TEST") != "1", reason="Docker integration is opt-in")
def test_resuming_workspace_keeps_previous_edits(tmp_path):
    from coding_agent.container_workspace import resume_workspace

    template = tmp_path / "template"
    template.mkdir()
    (template / "app.py").write_text("old", encoding="utf-8")
    first = start_workspace(template)
    second = None
    try:
        edit = run_workspace_tool(first, "edit_file", {"path": "app.py", "old_text": "old", "new_text": "new"})
        assert edit["status"] == "completed"
        stop_workspace(first)
        second = resume_workspace(first.volume)
        assert run_workspace_tool(second, "read_file", {"path": "app.py"})["result"] == "new"
        assert (template / "app.py").read_text(encoding="utf-8") == "old"
    finally:
        if second is not None:
            stop_workspace(second)
        elif first.active:
            stop_workspace(first)
        subprocess.run(["docker", "volume", "rm", first.volume], check=True, capture_output=True)
