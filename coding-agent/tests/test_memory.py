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
def test_interrupted_tool_recovers_with_postgres_and_docker(tmp_path, monkeypatch):
    import subprocess
    import time
    from types import SimpleNamespace
    from langchain_core.messages import ToolMessage
    from coding_agent import agent
    from coding_agent.config import load_config
    from coding_agent.container_workspace import start_workspace, stop_workspace, resume_workspace, run_workspace_tool, docker
    from coding_agent.graph import build_graph
    from coding_agent.memory import open_memory

    class Model:
        def invoke(self, messages):
            self.messages = list(messages)
            return AIMessage(content='Ready to continue.')

    template = tmp_path / 'template'
    template.mkdir()
    (template / 'app.py').write_text('saved edit', encoding='utf-8')
    thread_id = str(uuid4())
    options = {'configurable': {'thread_id': thread_id}}
    database_url = load_config().checkpoint_database_url
    first = start_workspace(template)
    second = None
    model = Model()
    monkeypatch.setattr(agent, 'make_model', lambda config, tools: model)
    try:
        with open_memory(database_url, thread_id) as memory:
            graph = build_graph(model, workspace=first, checkpointer=memory)
            call = {'id': 'pending', 'name': 'run_command', 'args': {'command': 'write a file'}}
            graph.update_state(options, {
                'messages': [HumanMessage(content='Fix the project'), AIMessage(content='', tool_calls=[call])],
                'pending_calls': [(False, call)],
            }, as_node='ask_model')
        # Simulate a command still running when the turn was interrupted.
        docker('exec', '-d', first.container, 'sh', '-c', 'sleep 3; echo unexpected > /workspace/challenge/late.txt')
        with open_memory(database_url, thread_id) as memory:
            result = agent.run_turn('Try again', first, memory, thread_id,
                                    SimpleNamespace(jev_api_key='', langsmith_tracing=False), lambda event: None)
            assert result['answer'] == 'Ready to continue.'
            assert isinstance(model.messages[-2], ToolMessage)
            assert model.messages[-2].tool_call_id == 'pending'
            assert 'unknown' in model.messages[-2].content
            assert model.messages[-1].content == 'Try again'
        time.sleep(4)
        assert run_workspace_tool(first, 'read_file', {'path': 'late.txt'})['status'] == 'error'
        assert run_workspace_tool(first, 'read_file', {'path': 'app.py'})['result'] == 'saved edit'
        # Simulate reopening after a server crash left its old container running.
        second = resume_workspace(first.volume)
        assert run_workspace_tool(second, 'read_file', {'path': 'app.py'})['result'] == 'saved edit'
    finally:
        if second is not None:
            stop_workspace(second)
        elif first.active:
            stop_workspace(first)
        with open_memory(database_url, thread_id) as memory:
            memory.delete_thread(thread_id)
        subprocess.run(['docker', 'volume', 'rm', first.volume], check=True, capture_output=True)


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
