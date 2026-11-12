from pathlib import Path

from langchain.tools import tool

from . import workspace_core
from .workspace_core import create_workspace, resolve_workspace_path, limit_output


@tool
def list_files(workspace: Path, path: str) -> str:
    """List up to 200 entries in a workspace directory; use '.' for the root."""
    return workspace_core.list_files(workspace, path)


@tool
def read_file(workspace: Path, path: str) -> str:
    """Read a UTF-8 text file using its path relative to the workspace."""
    return workspace_core.read_file(workspace, path)


@tool
def search_files(workspace: Path, query: str, path: str) -> str:
    """Search file contents for case-insensitive literal text and return paths and line numbers."""
    return workspace_core.search_files(workspace, query, path)


@tool
def edit_file(workspace: Path, path: str, old_text: str, new_text: str) -> str:
    """Replace one exact, unique piece of text in an existing workspace file."""
    return workspace_core.edit_file(workspace, path, old_text, new_text)
