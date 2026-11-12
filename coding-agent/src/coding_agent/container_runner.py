import json
import sys
from pathlib import Path

try:
    from . import workspace_core
except ImportError:
    import workspace_core


def run_workspace_tool(workspace, name, args):
    operations = {
        "list_files": workspace_core.list_files,
        "search_files": workspace_core.search_files,
        "read_file": workspace_core.read_file,
        "edit_file": workspace_core.edit_file,
        "read_editor_file": workspace_core.read_editor_file,
        "write_editor_file": workspace_core.write_editor_file,
    }
    if name not in operations:
        return {"status": "error", "result": "Unknown workspace operation."}
    try:
        result = operations[name](workspace, **args)
        return {"status": "completed", "result": result}
    except workspace_core.FileConflictError as error:
        return {"status": "conflict", "result": str(error)}
    except (ValueError, OSError, TypeError) as error:
        return {"status": "error", "result": str(error)}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    result = run_workspace_tool(Path("/workspace/challenge"), request["name"], request["args"])
    print(json.dumps(result))
