import os
import codecs
import difflib
import hashlib
import shutil
import tempfile
import uuid
from pathlib import Path, PureWindowsPath


SKIP_NAMES = {".git", ".venv", ".agent-deps", "node_modules", "__pycache__", ".pytest_cache", "instance"}
MAX_OUTPUT = 64 * 1024
MAX_FILE = 1024 * 1024


class FileConflictError(ValueError):
    pass


def create_workspace(template: Path, runtime_dir: Path) -> Path:
    template = Path(template)
    if not template.is_dir():
        raise ValueError("Challenge template does not exist.")
    # Refuse links before copying, so a template cannot copy outside files.
    for root, folders, files in os.walk(template, followlinks=False):
        folders[:] = [name for name in folders if name not in SKIP_NAMES]
        for name in folders + files:
            if (Path(root) / name).is_symlink():
                raise ValueError("Challenge template contains a symbolic link.")
    runtime_dir = Path(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    workspace = runtime_dir / str(uuid.uuid4())
    shutil.copytree(template, workspace, ignore=shutil.ignore_patterns(*SKIP_NAMES, ".env", ".env.*"))
    return workspace


def resolve_workspace_path(workspace: Path, path: str) -> Path:
    root = Path(workspace).resolve()
    candidate = Path(path)
    windows_path = PureWindowsPath(path)
    if candidate.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError("Use a relative path inside the workspace.")
    if ".." in candidate.parts or ".." in windows_path.parts:
        raise ValueError("Parent paths are not allowed.")
    result = (root / candidate).resolve()
    if not result.is_relative_to(root):
        raise ValueError("Path is outside the workspace.")
    return result


def limit_output(text: str) -> str:
    data = text.encode("utf-8")
    if len(data) <= MAX_OUTPUT:
        return text
    notice = "\n[Output truncated]"
    return data[:MAX_OUTPUT - len(notice)].decode("utf-8", errors="ignore") + notice


def list_files(workspace: Path, path: str) -> str:
    """List up to 200 entries in a workspace directory; use '.' for the root."""
    folder = resolve_workspace_path(workspace, path)
    if not folder.is_dir():
        raise ValueError("Directory does not exist.")
    names = sorted(item.name + ("/" if item.is_dir() else "") for item in folder.iterdir() if item.name != ".agent-deps")
    result = "\n".join(names[:200]) or "Directory is empty."
    if len(names) > 200:
        result += "\n[Listing truncated]"
    return limit_output(result)


def read_file(workspace: Path, path: str) -> str:
    """Read a UTF-8 text file using its path relative to the workspace."""
    file = resolve_workspace_path(workspace, path)
    if not file.is_file():
        raise ValueError("File does not exist.")
    with file.open("rb") as source:
        data = source.read(MAX_OUTPUT + 1)
    if b"\x00" in data:
        raise ValueError("Cannot read a binary file.")
    try:
        if len(data) > MAX_OUTPUT:
            decoder = codecs.getincrementaldecoder("utf-8")()
            text = decoder.decode(data[:MAX_OUTPUT], final=False)
            return limit_output(text + "\n[Output truncated]")
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("File is not valid UTF-8 text.") from None
    return limit_output(text)


def search_files(workspace: Path, query: str, path: str) -> str:
    """Search file contents for case-insensitive literal text and return paths and line numbers."""
    if not query.strip():
        raise ValueError("Search text cannot be empty.")
    folder = resolve_workspace_path(workspace, path)
    if not folder.is_dir():
        raise ValueError("Search path must be a directory.")
    matches = []
    size = 0
    skipped_large = 0
    for current, folders, files in os.walk(folder, followlinks=False):
        folders[:] = sorted(name for name in folders if name not in SKIP_NAMES and not (Path(current) / name).is_symlink())
        for name in sorted(files):
            file = Path(current) / name
            if file.is_symlink():
                continue
            try:
                if file.stat().st_size > MAX_FILE:
                    skipped_large += 1
                    continue
                data = file.read_bytes()
                if b"\x00" in data:
                    continue
                text = data.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if query.lower() in line.lower():
                    match = f"{file.relative_to(Path(workspace).resolve())}:{number}: {line}"
                    matches.append(match)
                    size += len(match.encode("utf-8")) + 1
                    if size > MAX_OUTPUT:
                        return limit_output("\n".join(matches))
    result = "\n".join(matches) if matches else "No matches found."
    if skipped_large:
        result += f"\nSkipped {skipped_large} file(s) larger than 1 MiB."
    return limit_output(result)


def edit_file(workspace: Path, path: str, old_text: str, new_text: str) -> str:
    """Replace one exact, unique piece of text in an existing workspace file."""
    file = resolve_workspace_path(workspace, path)
    if not file.is_file():
        raise ValueError("File does not exist.")
    if not old_text:
        raise ValueError("Old text cannot be empty.")
    data = file.read_bytes()
    if len(data) > MAX_FILE or b"\x00" in data:
        raise ValueError("File is binary or too large to edit.")
    try:
        before = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("File is not valid UTF-8 text.") from None
    if before.count(old_text) != 1:
        raise ValueError("Old text must match exactly once.")
    if "\r\n" in before:
        new_text = new_text.replace("\r\n", "\n").replace("\n", "\r\n")
    after = before.replace(old_text, new_text, 1)
    if after == before:
        raise ValueError("The replacement makes no change.")
    write_atomic(file, after.encode("utf-8"))
    diff = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=path, tofile=path)
    return limit_output("".join(diff))


def write_atomic(file: Path, data: bytes):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=file.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
        os.chmod(temporary, file.stat().st_mode)
        os.replace(temporary, file)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_editor_file(workspace: Path, path: str) -> dict:
    file = resolve_workspace_path(workspace, path)
    if not file.is_file():
        raise ValueError("File does not exist.")
    if file.stat().st_size > MAX_FILE:
        raise ValueError("File is too large to edit.")
    data = file.read_bytes()
    if len(data) > MAX_FILE or b"\x00" in data:
        raise ValueError("File is binary or too large to edit.")
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("File is not valid UTF-8 text.") from None
    return {"content": content, "version": hashlib.sha256(data).hexdigest()}


def write_editor_file(workspace: Path, path: str, content: str, expected_version: str) -> dict:
    file = resolve_workspace_path(workspace, path)
    current = read_editor_file(workspace, path)
    if current["version"] != expected_version:
        raise FileConflictError("File has changed since it was read.")
    data = content.encode("utf-8")
    if len(data) > MAX_FILE or b"\x00" in data:
        raise ValueError("File is binary or too large to edit.")
    write_atomic(file, data)
    return {"version": hashlib.sha256(data).hexdigest()}


