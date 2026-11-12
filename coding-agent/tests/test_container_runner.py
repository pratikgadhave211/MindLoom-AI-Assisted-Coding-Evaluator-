from coding_agent.container_runner import run_workspace_tool


def test_runner_reads_and_edits_only_its_workspace(tmp_path):
    file = tmp_path / "app.py"
    file.write_text("old code", encoding="utf-8")
    assert run_workspace_tool(tmp_path, "read_file", {"path": "app.py"})["result"] == "old code"
    result = run_workspace_tool(tmp_path, "edit_file", {"path": "app.py", "old_text": "old", "new_text": "new"})
    assert result["status"] == "completed"
    assert file.read_text(encoding="utf-8") == "new code"
    assert run_workspace_tool(tmp_path, "read_file", {"path": "../secret"})["status"] == "error"
    assert run_workspace_tool(tmp_path, "unknown", {})["status"] == "error"
