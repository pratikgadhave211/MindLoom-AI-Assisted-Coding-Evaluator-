def test_placeholder_tools_have_expected_names_and_do_not_run():
    from coding_agent.tools import TOOLS

    tools = {tool.name: tool for tool in TOOLS}
    assert set(tools) == {"list_files", "search_files", "read_file", "edit_file", "run_command", "run_tests"}
    assert tools["read_file"].invoke({"path": "secret.txt"}) == "Not implemented; no action was taken."
    assert tools["run_command"].invoke({"command": "a command"}) == "Not implemented; no action was taken."


def test_tool_arguments_are_validated():
    from coding_agent.tools import validate_tool_call

    assert validate_tool_call({"name": "read_file", "args": {"path": "app.py"}, "id": "1"})["id"] == "1"
    for call in [
        {"name": "unknown", "args": {}, "id": "1"},
        {"name": "read_file", "args": {}, "id": "2"},
        {"name": "read_file", "args": {"path": 1}, "id": "3"},
        {"name": "read_file", "args": {"path": "a", "extra": "b"}, "id": "4"},
    ]:
        try:
            validate_tool_call(call)
        except ValueError:
            continue
        raise AssertionError(f"Invalid tool call was accepted: {call}")


def test_dispatch_reads_and_keeps_commands_disabled(tmp_path):
    from coding_agent.tools import execute_tool_call

    (tmp_path / "app.py").write_text("login", encoding="utf-8")
    calls = [
        {"name": "list_files", "args": {"path": "."}, "id": "1"},
        {"name": "search_files", "args": {"path": ".", "query": "login"}, "id": "2"},
        {"name": "read_file", "args": {"path": "app.py"}, "id": "3"},
    ]
    for call in calls:
        result = execute_tool_call(tmp_path, call)
        assert result["status"] == "completed"
        assert result["result"]
    error = execute_tool_call(tmp_path, {"name": "read_file", "args": {"path": "../secret"}, "id": "4"})
    assert error["status"] == "error"
    command = execute_tool_call(tmp_path, {"name": "run_command", "args": {"command": "echo hi"}, "id": "5"})
    assert command["status"] == "not implemented"


def test_workspace_tools_are_invokable_and_model_does_not_choose_workspace(tmp_path):
    from coding_agent import workspace
    from coding_agent.tools import TOOLS, execute_tool_call

    (tmp_path / "app.py").write_text("hello", encoding="utf-8")
    assert workspace.read_file.invoke({"workspace": tmp_path, "path": "app.py"}) == "hello"
    assert "case-insensitive" in workspace.search_files.description.lower()
    schemas = {item.name: item for item in TOOLS}
    assert "workspace" not in schemas["read_file"].get_input_schema().model_json_schema()["properties"]
    result = execute_tool_call(tmp_path, {"name": "read_file", "args": {"path": "app.py"}, "id": "one"})
    assert result["result"] == "hello"


def test_agent_dispatches_edit_command_and_test_to_container(monkeypatch):
    from coding_agent import tools
    from coding_agent.container_workspace import Attempt

    calls = []
    def fake_run(attempt, name, args):
        calls.append((name, args))
        return {"status": "completed", "result": "ok"}
    monkeypatch.setattr(tools, "run_workspace_tool", fake_run)
    attempt = Attempt("container", "volume")
    for name, args in [
        ("edit_file", {"path": "a.py", "old_text": "old", "new_text": "new"}),
        ("run_command", {"command": "echo hi"}),
        ("run_tests", {}),
    ]:
        result = tools.execute_tool_call(attempt, {"name": name, "args": args, "id": "1"})
        assert result["status"] == "completed"
    assert [call[0] for call in calls] == ["edit_file", "run_command", "run_tests"]
