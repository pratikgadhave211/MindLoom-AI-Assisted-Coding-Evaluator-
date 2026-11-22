import threading
import time
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest


def test_turns_keep_same_workspace_and_reject_overlap(monkeypatch):
    from coding_agent import attempts

    entered = threading.Event()
    release = threading.Event()
    workspaces = []

    @contextmanager
    def memory(url, thread_id):
        yield object()

    def run(prompt, workspace, memory, thread_id, config, publish):
        workspaces.append(workspace)
        publish({"type": "tool_started", "name": "read_file", "call_id": "1"})
        entered.set()
        release.wait(5)
        publish({"type": "tool_finished", "name": "read_file", "call_id": "1", "status": "completed", "result": "ok"})
        return {"answer": "done"}

    monkeypatch.setattr(attempts, "load_config", lambda: SimpleNamespace(checkpoint_database_url="db"))
    monkeypatch.setattr(attempts, "open_memory", memory)
    monkeypatch.setattr(attempts, "start_workspace", lambda template: SimpleNamespace(volume="volume", active=True))
    monkeypatch.setattr(attempts, "save_workspace", lambda *args: None)
    monkeypatch.setattr(attempts, "stop_workspace", lambda workspace: None)
    monkeypatch.setattr(attempts, "run_turn", run)
    monkeypatch.setattr(attempts, "protect_prompt", lambda prompt, **kwargs: (prompt, 0))
    monkeypatch.setattr(attempts, "run_workspace_tool", lambda workspace, name, args: {"status": "completed", "result": "ok"})
    manager = attempts.AttemptManager()
    monkeypatch.setattr(manager, '_chat_memory', lambda attempt: SimpleNamespace(conn=SimpleNamespace(transaction=nullcontext)))
    monkeypatch.setattr(attempts, 'record_evidence', lambda *args: None)
    attempt_id = manager.create()
    turn_id = manager.start_turn(attempt_id, "first")
    assert entered.wait(5)
    with pytest.raises(ValueError, match="already running"):
        manager.start_turn(attempt_id, "overlap")
    with pytest.raises(ValueError, match="Cannot save"):
        manager.file(attempt_id, "write_editor_file", {})
    assert manager.file(attempt_id, "read_editor_file", {})["result"] == "ok"
    release.set()
    for _ in range(100):
        events, done = manager.events(attempt_id, turn_id, 0, timeout=0.05)
        if done:
            break
        time.sleep(0.01)
    assert done
    assert [event["type"] for event in events] == ["turn_started", "tool_started", "tool_finished", "answer", "turn_finished"]
    assert events[2]["status"] == "completed"
    manager.close(attempt_id)


def test_shutdown_stops_open_idle_workspace(monkeypatch):
    from coding_agent import attempts

    stopped = []
    closed = []
    manager = attempts.AttemptManager()
    manager.attempts["a"] = {
        "workspace": SimpleNamespace(volume="volume", active=True), "busy": False,
        "memory_context": SimpleNamespace(__exit__=lambda *args: closed.append(True)), "turns": {},
    }
    monkeypatch.setattr(attempts, "stop_workspace", lambda workspace: stopped.append(workspace.volume))
    manager.shutdown()
    assert stopped == ["volume"]
    assert closed == [True]
    assert manager.attempts == {}
