import os
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage


@pytest.mark.skipif(os.environ.get("AGENT_POSTGRES_TEST") != "1", reason="PostgreSQL integration is opt-in")
def test_postgres_restores_history_after_reconnecting():
    from coding_agent.config import load_config
    from coding_agent.graph import build_graph
    from coding_agent.memory import open_memory, save_workspace, get_workspace

    class Model:
        def __init__(self):
            self.messages = []
        def invoke(self, messages):
            self.messages.append(list(messages))
            return AIMessage(content="ok")

    database_url = load_config().checkpoint_database_url
    thread_id = str(uuid4())
    other_id = str(uuid4())
    model = Model()
    try:
        with open_memory(database_url, thread_id) as memory:
            save_workspace(memory, thread_id, "coding-agent-" + "a" * 32 + "-workspace")
            assert get_workspace(memory, thread_id).endswith("-workspace")
            graph = build_graph(model, checkpointer=memory)
            graph.invoke({"prompt": "first message"}, {"configurable": {"thread_id": thread_id}})
        with open_memory(database_url, thread_id) as memory:
            graph = build_graph(model, checkpointer=memory)
            graph.invoke({"prompt": "second message"}, {"configurable": {"thread_id": thread_id}})
            humans = [message.content for message in model.messages[-1] if isinstance(message, HumanMessage)]
            assert humans == ["first message", "second message"]
            assert get_workspace(memory, other_id) is None
    finally:
        with open_memory(database_url, thread_id) as memory:
            memory.delete_thread(thread_id)
            memory.conn.execute("DELETE FROM agent_workspaces WHERE thread_id = %s", (thread_id,))


@pytest.mark.skipif(os.environ.get("AGENT_POSTGRES_TEST") != "1", reason="PostgreSQL integration is opt-in")
def test_same_conversation_cannot_run_twice_at_once():
    from coding_agent.config import load_config
    from coding_agent.memory import open_memory

    database_url = load_config().checkpoint_database_url
    thread_id = str(uuid4())
    with open_memory(database_url, thread_id):
        with pytest.raises(ValueError, match="already running"):
            with open_memory(database_url, thread_id):
                pass


@pytest.mark.skipif(os.environ.get("AGENT_POSTGRES_TEST") != "1" or os.environ.get("AGENT_DOCKER_TEST") != "1", reason="PostgreSQL and Docker integration are opt-in")
def test_conversation_and_workspace_resume_together(tmp_path):
    import subprocess
    from coding_agent.config import load_config
    from coding_agent.container_workspace import start_workspace, stop_workspace, resume_workspace, run_workspace_tool
    from coding_agent.graph import build_graph
    from coding_agent.memory import open_memory, save_workspace, get_workspace

    class Model:
        def __init__(self):
            self.messages = []
        def invoke(self, messages):
            self.messages.append(list(messages))
            if len(self.messages) == 1:
                return AIMessage(content="", tool_calls=[{"id": "edit", "name": "edit_file", "args": {"path": "app.py", "old_text": "old", "new_text": "new"}}])
            return AIMessage(content="done")

    template = tmp_path / "template"
    template.mkdir()
    (template / "app.py").write_text("old", encoding="utf-8")
    database_url = load_config().checkpoint_database_url
    thread_id = str(uuid4())
    model = Model()
    first = start_workspace(template)
    second = None
    try:
        with open_memory(database_url, thread_id) as memory:
            save_workspace(memory, thread_id, first.volume)
            graph = build_graph(model, workspace=first, checkpointer=memory)
            result = graph.invoke({"prompt": "change the file"}, {"configurable": {"thread_id": thread_id}})
            assert result["tool_calls"][0]["status"] == "completed"
        stop_workspace(first)
        with open_memory(database_url, thread_id) as memory:
            second = resume_workspace(get_workspace(memory, thread_id))
            assert run_workspace_tool(second, "read_file", {"path": "app.py"})["result"] == "new"
            graph = build_graph(model, workspace=second, checkpointer=memory)
            graph.invoke({"prompt": "what changed?"}, {"configurable": {"thread_id": thread_id}})
            humans = [message.content for message in model.messages[-1] if isinstance(message, HumanMessage)]
            assert humans == ["change the file", "what changed?"]
    finally:
        if second is not None:
            stop_workspace(second)
        elif first.active:
            stop_workspace(first)
        with open_memory(database_url, thread_id) as memory:
            memory.delete_thread(thread_id)
            memory.conn.execute("DELETE FROM agent_workspaces WHERE thread_id = %s", (thread_id,))
        subprocess.run(["docker", "volume", "rm", first.volume], check=True, capture_output=True)


@pytest.mark.skipif(os.environ.get("AGENT_POSTGRES_TEST") != "1" or os.environ.get("AGENT_DOCKER_TEST") != "1", reason="PostgreSQL and Docker integration are opt-in")
def test_terminal_resumes_by_conversation_id(monkeypatch, capsys):
    import subprocess
    from coding_agent import main
    from coding_agent.config import load_config
    from coding_agent.memory import open_memory

    class Model:
        def __init__(self):
            self.messages = []
        def invoke(self, messages):
            self.messages.append(list(messages))
            return AIMessage(content="ok")

    model = Model()
    monkeypatch.setattr(main, "make_model", lambda config, tools: model)
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    monkeypatch.setattr("builtins.input", lambda _: "first prompt")
    assert main.main([]) == 0
    first_output = capsys.readouterr().out
    thread_id = next(line.split(": ", 1)[1] for line in first_output.splitlines() if line.startswith("Conversation ID: "))
    volume = next(line.split(": ", 1)[1] for line in first_output.splitlines() if line.startswith("Workspace: "))
    try:
        monkeypatch.setattr("builtins.input", lambda _: "second prompt")
        assert main.main(["--thread-id", thread_id]) == 0
        second_output = capsys.readouterr().out
        assert volume in second_output
        humans = [message.content for message in model.messages[-1] if isinstance(message, HumanMessage)]
        assert humans == ["first prompt", "second prompt"]
    finally:
        with open_memory(load_config().checkpoint_database_url, thread_id) as memory:
            memory.delete_thread(thread_id)
            memory.conn.execute("DELETE FROM agent_workspaces WHERE thread_id = %s", (thread_id,))
        subprocess.run(["docker", "volume", "rm", volume], check=True, capture_output=True)
