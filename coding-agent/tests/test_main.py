from langchain_core.messages import AIMessage
from contextlib import contextmanager
import pytest
from langgraph.checkpoint.memory import InMemorySaver


@pytest.fixture(autouse=True)
def fake_checkpoint_database(monkeypatch):
    from coding_agent import main

    @contextmanager
    def fake_memory(url, thread_id):
        yield InMemorySaver()

    monkeypatch.setattr("sys.argv", ["coding-agent"])
    monkeypatch.setattr(main, "open_memory", fake_memory)
    monkeypatch.setattr(main, "get_workspace", lambda memory, thread_id: None)
    monkeypatch.setattr(main, "save_workspace", lambda memory, thread_id, volume: None)


def test_terminal_shows_tool_result(monkeypatch, capsys, tmp_path):
    from coding_agent import main

    class FakeModel:
        calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls > 1:
                return AIMessage(content="Found the file.")
            return AIMessage(content="", tool_calls=[
                {"name": "read_file", "args": {"path": "blog.py"}, "id": "one"}
            ])

    (tmp_path / "blog.py").write_text("example content", encoding="utf-8")
    monkeypatch.setattr(main, "start_workspace", lambda template: tmp_path)
    monkeypatch.setattr(main, "stop_workspace", lambda workspace: None)
    monkeypatch.setattr("builtins.input", lambda _: "Find the bug")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    monkeypatch.setattr(main, "make_model", lambda config, tools: FakeModel())
    assert main.main() == 0
    output = capsys.readouterr().out
    assert "read_file (completed)" in output
    assert "example content" in output
    assert "Found the file" in output
    assert "test-key" not in output


def test_model_setup_error_does_not_print_secrets(monkeypatch, capsys):
    from coding_agent import main

    def fail(config, tools):
        raise ValueError("sensitive-key")

    monkeypatch.setattr("builtins.input", lambda _: "Find the bug")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    monkeypatch.setattr(main, "make_model", fail)
    assert main.main() == 1
    assert "sensitive-key" not in capsys.readouterr().out


def test_terminal_shows_jev_score(monkeypatch, capsys):
    from coding_agent import main

    class FakeModel:
        def invoke(self, messages):
            return AIMessage(content="Hello")

    monkeypatch.setattr("builtins.input", lambda _: "Hi")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-jev-key")
    monkeypatch.setattr(main, "check_with_jev", lambda prompt, key: 0.42)
    monkeypatch.setattr(main, "make_model", lambda config, tools: FakeModel())
    monkeypatch.setattr(main, "start_workspace", lambda template: "test-workspace")
    monkeypatch.setattr(main, "stop_workspace", lambda workspace: None)
    assert main.main() == 0
    output = capsys.readouterr().out
    assert "Jev coding-request score: 0.42" in output
    assert "Hello" in output
    assert "test-jev-key" not in output


def test_workspace_is_stopped_when_graph_fails(monkeypatch, capsys):
    from coding_agent import main

    stopped = []
    monkeypatch.setattr("builtins.input", lambda _: "Inspect the repo")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(main, "make_model", lambda config, tools: object())
    monkeypatch.setattr(main, "start_workspace", lambda template: "attempt")
    monkeypatch.setattr(main, "stop_workspace", lambda attempt: stopped.append(attempt))
    def fail(*args, **kwargs):
        raise RuntimeError("failure")
    monkeypatch.setattr(main, "build_graph", fail)
    assert main.main() == 1
    assert stopped == ["attempt"]


def test_terminal_reports_actual_failed_test_even_if_model_claims_pass(monkeypatch, capsys):
    from coding_agent import main

    class Graph:
        def get_state(self, config):
            return type("Snapshot", (), {"next": ()})()
        def invoke(self, state, config=None):
            return {"answer": "All tests passed.", "tool_calls": [{"name": "run_tests", "args": {}, "status": "error", "result": "Exit code: 1", "exit_code": 1}]}
    monkeypatch.setattr("builtins.input", lambda _: "Fix the tests")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(main, "make_model", lambda config, tools: object())
    monkeypatch.setattr(main, "start_workspace", lambda template: "attempt")
    monkeypatch.setattr(main, "stop_workspace", lambda attempt: None)
    monkeypatch.setattr(main, "build_graph", lambda *args, **kwargs: Graph())
    assert main.main() == 0
    assert "Recorded test result: FAILED (exit code 1)" in capsys.readouterr().out


def test_workspace_name_is_shown_if_database_registration_fails(monkeypatch, capsys):
    from coding_agent import main
    from types import SimpleNamespace

    workspace = SimpleNamespace(volume="coding-agent-sample-workspace")
    stopped = []
    monkeypatch.setattr("builtins.input", lambda _: "hello")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(main, "make_model", lambda config, tools: object())
    monkeypatch.setattr(main, "start_workspace", lambda template: workspace)
    monkeypatch.setattr(main, "stop_workspace", lambda attempt: stopped.append(attempt))
    def fail(*args):
        raise RuntimeError("database failure")
    monkeypatch.setattr(main, "save_workspace", fail)
    assert main.main([]) == 1
    assert workspace.volume in capsys.readouterr().out
    assert stopped == [workspace]
