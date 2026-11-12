import pytest


def test_edit_requires_one_exact_match_and_preserves_bytes_on_failure(tmp_path):
    from coding_agent.workspace import edit_file

    file = tmp_path / "app.py"
    file.write_bytes(b"one\r\ntwo\r\n")
    result = edit_file.invoke({"workspace": tmp_path, "path": "app.py", "old_text": "two", "new_text": "three"})
    assert file.read_bytes() == b"one\r\nthree\r\n"
    assert "three" in result
    for old in ("", "missing", "one\r\nthree\r\none"):
        before = file.read_bytes()
        with pytest.raises(ValueError):
            edit_file.invoke({"workspace": tmp_path, "path": "app.py", "old_text": old, "new_text": "x"})
        assert file.read_bytes() == before
    file.write_text("same same", encoding="utf-8")
    with pytest.raises(ValueError):
        edit_file.invoke({"workspace": tmp_path, "path": "app.py", "old_text": "same", "new_text": "x"})
    assert file.read_text(encoding="utf-8") == "same same"


def test_edit_rejects_paths_outside_workspace(tmp_path):
    from coding_agent.workspace import edit_file

    with pytest.raises(ValueError):
        edit_file.invoke({"workspace": tmp_path, "path": "../secret", "old_text": "a", "new_text": "b"})
