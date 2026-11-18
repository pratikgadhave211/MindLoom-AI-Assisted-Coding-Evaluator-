import json
import argparse
from uuid import UUID, uuid4
from pathlib import Path

import psycopg

from .config import load_config
from .graph import build_graph
from .jev import check_with_jev
from .model import make_model, model_error
from .sanity import check_prompt
from .tools import TOOLS
from .container_workspace import start_workspace, stop_workspace, resume_workspace
from .memory import open_memory, get_workspace, save_workspace
from .tracing import run_graph
from .agent import prepare_checkpoint


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one agent prompt with saved conversation memory.")
    parser.add_argument("--thread-id", help="Resume an existing conversation ID")
    args = parser.parse_args(argv)
    try:
        thread_id = str(UUID(args.thread_id)) if args.thread_id else str(uuid4())
    except ValueError:
        print("Invalid conversation ID.")
        return 1
    # Read one prompt and display the model's answer or tool requests.
    try:
        prompt = check_prompt(input("Your prompt: "))
        config = load_config()
        if not config.checkpoint_database_url:
            raise ValueError("Set CHECKPOINT_DATABASE_URL in .env before starting the agent.")
    except (ValueError, EOFError, KeyboardInterrupt) as error:
        print(str(error) or "Cancelled.")
        return 1

    cleanup_failed = False
    try:
        model = make_model(config, TOOLS)
        jev_checker = None
        if config.jev_api_key:
            jev_checker = lambda text: check_with_jev(text, config.jev_api_key)
        agent_dir = Path(__file__).resolve().parents[2]
        template = agent_dir.parent / "broken-repos" / "broken-flaskr-blog"
        with open_memory(config.checkpoint_database_url, thread_id) as memory:
            volume = get_workspace(memory, thread_id)
            if args.thread_id and volume is None:
                print("Conversation ID was not found. Start a new conversation without --thread-id.")
                return 1
            workspace = None
            try:
                workspace = resume_workspace(volume) if volume else start_workspace(template)
                print(f"Conversation ID: {thread_id}")
                print(f"Workspace: {getattr(workspace, 'volume', workspace)}")
                if volume is None:
                    save_workspace(memory, thread_id, str(getattr(workspace, "volume", workspace)))
                graph = build_graph(model, jev_checker, workspace, checkpointer=memory)
                graph_config = {"configurable": {"thread_id": thread_id}}
                prepare_checkpoint(graph, graph_config, workspace)
                result = run_graph(graph, prompt, config, thread_id=thread_id)
            finally:
                if workspace is not None:
                    try:
                        stop_workspace(workspace)
                    except RuntimeError as error:
                        print(str(error))
                        cleanup_failed = True
    except KeyboardInterrupt:
        print("Cancelled.")
        return 1
    except psycopg.Error:
        print("Could not access the checkpoint database. Check that Docker Compose PostgreSQL is running.")
        return 1
    except (ValueError, RuntimeError, OSError) as error:
        print("Could not start the conversation or workspace. Check Docker, PostgreSQL, and the conversation ID.")
        return 1
    except Exception as error:
        print(model_error(error))
        return 1
    
    if result:
        print(f"{result}\n\n")
    if result.get("jev_score") is not None:
        print(f"Jev coding-request score: {result['jev_score']:.2f} / 1 (advisory)")
    elif result.get("jev_status"):
        print(f"Jev check: {result['jev_status']}; continuing without a score.")
    for call in result.get("tool_calls", []):
        print(f"Tool: {call['name']} ({call['status']})")
        print(f"Arguments: {json.dumps(call['args'], ensure_ascii=False)}")
        if call.get("result"):
            print(call["result"])
    if result.get("error"):
        print(result["error"])
        return 1
    if result.get("answer"):
        print(result["answer"])
    tests = [call for call in result.get("tool_calls", []) if call.get("name") == "run_tests"]
    if tests:
        latest = tests[-1]
        code = latest.get("exit_code")
        status = "PASSED" if code == 0 else "FAILED" if code is not None else "NOT COMPLETED"
        print(f"Recorded test result: {status} (exit code {code})")
    else:
        print("Recorded test result: run_tests was not used.")
    if not result.get("answer") and not result.get("tool_calls"):
        print("The model returned no answer or tool requests.")
    return 1 if cleanup_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
