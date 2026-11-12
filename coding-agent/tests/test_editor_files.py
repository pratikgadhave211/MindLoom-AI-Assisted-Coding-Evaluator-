import pytest


def test_editor_save_checks_version_and_preserves_content_on_conflict(tmp_path):
    from coding_agent.workspace_core import read_editor_file, write_editor_file

    file = tmp_path / "app.py"
    file.write_text("old", encoding="utf-8")
    current = read_editor_file(tmp_path, "app.py")
    assert current["content"] == "old"
    updated = write_editor_file(tmp_path, "app.py", "new", current["version"])
    assert updated["version"] != current["version"]
    with pytest.raises(ValueError, match="changed"):
        write_editor_file(tmp_path, "app.py", "lost", current["version"])
    assert file.read_text(encoding="utf-8") == "new"
    with pytest.raises(ValueError):
        read_editor_file(tmp_path, "../outside")
