from .graph import build_graph
from .jev import check_with_jev
from .model import make_model
from .tools import TOOLS
from .tracing import stream_graph
from .diagnostics import log_event


def run_turn(prompt, workspace, memory, thread_id, config, publish):
    log_event('turn started', {'thread_id': thread_id, 'prompt': prompt})
    # Reuse the same model, workspace, and checkpointed graph as the CLI.
    model = make_model(config, TOOLS)
    jev = None
    if config.jev_api_key:
        jev = lambda text: check_with_jev(text, config.jev_api_key)
    graph = build_graph(model, jev, workspace, checkpointer=memory)
    options = {"configurable": {"thread_id": thread_id}}
    if graph.get_state(options).next:
        raise ValueError("The previous turn was interrupted; automatic tool replay is disabled.")

    # Debug events arrive before and after each graph step.
    names = {tool.name for tool in TOOLS} | {'invalid_tool'}
    last_update = ''
    tools_since_update = 0
    tool_failed = False
    last_tool = ''
    for event in stream_graph(graph, prompt, config, thread_id):
        payload = event.get("payload", {})
        name = payload.get("name")
        if name == 'ask_model' and event.get('type') == 'task_result':
            response = payload.get('result', {}).get('response')
            if response and response.tool_calls:
                message = response.text.strip()
                next_tool = response.tool_calls[0].get('name', '')
                milestone = next_tool in ('edit_file', 'run_tests') and next_tool != last_tool
                ready = not last_update or tools_since_update >= 2 or tool_failed or milestone
                if ready and message and message != last_update and '<think' not in message.lower() and '</think' not in message.lower():
                    publish({'type': 'progress_update', 'message': message[:2000]})
                    last_update = message
                    tools_since_update = 0
                    tool_failed = False
        if name not in names:
            continue
        if event.get("type") == "task":
            pending = payload.get("input", {}).get("pending_calls", [])
            call = pending[0][1] if pending else {}
            publish({"type": "tool_started", "name": call.get('name') or name, "call_id": call.get("id")})
        elif event.get("type") == "task_result":
            calls = payload.get("result", {}).get("tool_calls", [])
            if calls:
                call = calls[-1]
                tools_since_update += 1
                tool_failed = tool_failed or call.get('status') != 'completed'
                last_tool = call.get('name') or name
                publish({"type": "tool_finished", "name": last_tool, "call_id": call.get("id"),
                         "status": call.get("status"), "result": str(call.get("result", ""))[:4096]})
    result = graph.get_state(options).values
    log_event('turn finished', {'thread_id': thread_id, 'answer': result.get('answer'),
                                'error': result.get('error'), 'model_calls': result.get('model_count'),
                                'tool_calls': result.get('tool_count')})
    return result
