from langchain.tools import tool
from langsmith import traceable

from . import workspace as workspace_tools
from .container_workspace import Attempt, run_workspace_tool


# The model sees these descriptions; the dispatcher supplies the workspace.
NOT_IMPLEMENTED = "Not implemented; no action was taken."


@tool
def list_files(path: str) -> str:
    """List up to 200 entries in a workspace directory; use '.' for the root."""
    return NOT_IMPLEMENTED


@tool
def search_files(query: str, path: str) -> str:
    """Search file contents for case-insensitive literal text and return paths and line numbers."""
    return NOT_IMPLEMENTED


@tool
def read_file(path: str) -> str:
    """Read a UTF-8 text file using its path relative to the workspace."""
    return NOT_IMPLEMENTED


@tool
def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace one unique exact text match in an existing workspace file."""
    return NOT_IMPLEMENTED


@tool
def run_command(command: str) -> str:
    """Run a command in the workspace terminal."""
    return NOT_IMPLEMENTED


@tool
def run_tests() -> str:
    """Run the project's tests."""
    return NOT_IMPLEMENTED


TOOLS = [list_files, search_files, read_file, edit_file, run_command, run_tests]


def validate_tool_call(call):
    # Accept only known tools and the exact string inputs they describe.
    tools = {item.name: item for item in TOOLS}
    name = call.get("name")
    args = call.get("args")
    if name not in tools or not isinstance(args, dict) or not call.get("id"):
        raise ValueError("The model returned an unknown or invalid tool request.")
    schema = tools[name].get_input_schema().model_json_schema()
    fields = schema.get("properties", {})
    if set(args) != set(fields) or any(not isinstance(value, str) for value in args.values()):
        raise ValueError(f"The model returned invalid inputs for {name}.")
    return {"id": call["id"], "name": name, "args": args, "status": "not executed"}


@traceable(run_type="tool", name="workspace_tool")
def execute_tool_call(workspace, call):
    result = validate_tool_call(call)
    if isinstance(workspace, Attempt):
        response = run_workspace_tool(workspace, result["name"], result["args"])
        result.update(response)
        return result
    available = {
        "list_files": workspace_tools.list_files,
        "search_files": workspace_tools.search_files,
        "read_file": workspace_tools.read_file,
    }
    if result["name"] not in available:
        result["status"] = "not implemented"
        result["result"] = NOT_IMPLEMENTED
        return result
    try:
        inputs = {"workspace": workspace, **result["args"]}
        result["result"] = available[result["name"]].invoke(inputs)
        result["status"] = "completed"
    except (ValueError, OSError) as error:
        result["status"] = "error"
        result["result"] = str(error)
    return result
