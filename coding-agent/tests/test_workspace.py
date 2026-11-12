import pytest


def test_copies_are_independent_and_skip_generated_files(tmp_path):
    from coding_agent.workspace import create_workspace

    template = tmp_path / "template"
    template.mkdir()
    (template / "app.py").write_text("original", encoding="utf-8")
    (template / ".env").write_text("sensitive", encoding="utf-8")
    for name in (".git", ".venv", "node_modules", "__pycache__", "instance"):
        (template / name).mkdir()
        (template / name / "data").write_text("skip", encoding="utf-8")
    first = create_workspace(template, tmp_path / "runs")
    second = create_workspace(template, tmp_path / "runs")
    (first / "app.py").write_text("changed", encoding="utf-8")
    assert first != second
    assert (template / "app.py").read_text(encoding="utf-8") == "original"
    assert (second / "app.py").read_text(encoding="utf-8") == "original"
    assert not (first / ".git").exists()
    assert not (first / ".env").exists()
    assert not (first / "instance").exists()
    with pytest.raises(ValueError):
        create_workspace(tmp_path / "missing", tmp_path / "runs")


def test_read_list_search_and_limits(tmp_path):
    from coding_agent.workspace import list_files, read_file, search_files

    (tmp_path / "users.py").write_text("def Authenticate():\n    pass\n", encoding="utf-8")
    (tmp_path / "large.txt").write_text("x" * 70000, encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "hidden.txt").write_text("Authenticate", encoding="utf-8")
    assert "users.py" in list_files.invoke({"workspace": tmp_path, "path": "."})
    assert "Authenticate" in read_file.invoke({"workspace": tmp_path, "path": "users.py"})
    result = search_files.invoke({"workspace": tmp_path, "query": "authenticate", "path": "."})
    assert "users.py:1" in result
    assert "hidden.txt" not in result
    assert "no matches" in search_files.invoke({"workspace": tmp_path, "query": "missing", "path": "."}).lower()
    assert "truncated" in read_file.invoke({"workspace": tmp_path, "path": "large.txt"}).lower()
    with pytest.raises(ValueError):
        search_files.invoke({"workspace": tmp_path, "query": "", "path": "."})


def test_workspace_rejects_outside_paths_and_invalid_files(tmp_path):
    from coding_agent.workspace import read_file

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "binary").write_bytes(b"\xff\x00")
    for path in ("../outside", str(tmp_path / "outside"), "binary", "missing"):
        with pytest.raises((ValueError, OSError)):
            read_file.invoke({"workspace": root, "path": path})


def test_rejects_links_to_outside(tmp_path):
    from coding_agent.workspace import create_workspace, read_file

    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (root / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symbolic links is not permitted")
    with pytest.raises(ValueError):
        read_file.invoke({"workspace": root, "path": "link.txt"})
    with pytest.raises(ValueError):
        create_workspace(root, tmp_path / "runs")


def test_read_truncates_unicode_without_rejecting_valid_text(tmp_path):
    from coding_agent.workspace import read_file

    (tmp_path / "unicode.txt").write_text("a" * 65536 + "€" * 10, encoding="utf-8")
    result = read_file.invoke({"workspace": tmp_path, "path": "unicode.txt"})
    assert "truncated" in result.lower()
    assert len(result.encode("utf-8")) <= 65536


def test_large_listing_and_search_are_truncated(tmp_path):
    from coding_agent.workspace import list_files, search_files

    for number in range(201):
        (tmp_path / f"{number}.txt").write_text("", encoding="utf-8")
    (tmp_path / "many.txt").write_text("match " * 12000, encoding="utf-8")
    assert "truncated" in list_files.invoke({"workspace": tmp_path, "path": "."}).lower()
    assert "truncated" in search_files.invoke({"workspace": tmp_path, "query": "match", "path": "."}).lower()


def test_search_reports_skipped_large_files(tmp_path):
    from coding_agent.workspace import search_files

    (tmp_path / "large.txt").write_text("x" * (1024 * 1024 + 1), encoding="utf-8")
    result = search_files.invoke({"workspace": tmp_path, "query": "missing", "path": "."})
    assert "skipped" in result.lower()
    assert "1" in result
def test_installed_packages_do_not_clutter_workspace_explorer_or_search(tmp_path):
    from coding_agent.workspace import list_files, search_files

    hidden = tmp_path / '.agent-deps' / 'python'
    hidden.mkdir(parents=True)
    (hidden / 'dependency.py').write_text('unique_dependency_marker', encoding='utf-8')
    (tmp_path / 'app.py').write_text('project file', encoding='utf-8')
    assert '.agent-deps' not in list_files.invoke({'workspace': tmp_path, 'path': '.'})
    assert search_files.invoke({'workspace': tmp_path, 'path': '.', 'query': 'unique_dependency_marker'}) == 'No matches found.'

