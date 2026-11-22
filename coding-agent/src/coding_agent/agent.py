from langchain_core.messages import AIMessage, ToolMessage

from .graph import build_graph
from .jev import check_input_safety
from .input_guardrail import check_input
from .model import make_model
from .tools import TOOLS
from .tracing import stream_graph
from .diagnostics import log_event
from .container_workspace import Attempt, docker


def prepare_checkpoint(graph, options, workspace=None):
    """Close unfinished tool requests without repeating their side effects."""
    snapshot = graph.get_state(options)
    state = getattr(snapshot, 'values', {})
    messages = []
    waiting = {}
    seen = set()
    repaired = False

    def close_unfinished():
        nonlocal repaired
        for call_id in waiting:
            messages.append(ToolMessage(
                content='Tool call interrupted; its outcome is unknown. Inspect the workspace before retrying.',
                tool_call_id=call_id))
            repaired = True
        waiting.clear()

    for message in state.get('messages', []):
        if isinstance(message, ToolMessage):
            if message.tool_call_id not in waiting:
                raise ValueError('Cannot resume: the saved tool call history is inconsistent.')
            del waiting[message.tool_call_id]
            messages.append(message)
            continue
        close_unfinished()
        messages.append(message)
        if isinstance(message, AIMessage):
            batch_ids = set()
            for call in message.tool_calls + message.invalid_tool_calls:
                call_id = call.get('id')
                if not call_id or call_id in batch_ids:
                    raise ValueError('Cannot resume: a saved tool call has a missing or duplicate ID.')
                batch_ids.add(call_id)
                seen.add(call_id)
                waiting[call_id] = True
    close_unfinished()

    for _, call in state.get('pending_calls', []):
        if call.get('id') not in seen:
            raise ValueError('Cannot resume: a pending tool call is missing from the saved history.')

    if snapshot.next or state.get('pending_calls') or repaired:
        if isinstance(workspace, Attempt):
            try:
                # Ensure an interrupted command is no longer changing the workspace.
                docker('restart', workspace.container)
            except Exception:
                workspace.active = False
                raise RuntimeError('Could not stop the interrupted workspace process.') from None
        graph.update_state(options, {'messages': messages, 'pending_calls': [], 'error': '', 'answer': ''},
                           as_node='finish')


def run_turn(prompt, workspace, memory, thread_id, config, publish):
    log_event('turn started', {'thread_id': thread_id, 'prompt': prompt})
    # Reuse the same model, workspace, and checkpointed graph as the CLI.
    model = make_model(config, TOOLS)
    safety = (lambda text: check_input_safety(text, config.jev_api_key)) if config.jev_api_key else None
    graph = build_graph(model, workspace=workspace, checkpointer=memory,
                        input_checker=lambda text: check_input(text, safety))
    options = {"configurable": {"thread_id": thread_id}}
    prepare_checkpoint(graph, options, workspace)

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
            raw_usage = response.usage_metadata if response else None
            usage = None
            keys = ('input_tokens', 'output_tokens', 'total_tokens')
            if isinstance(raw_usage, dict) and all(type(raw_usage.get(key)) is int and raw_usage[key] >= 0 for key in keys):
                usage = {key: raw_usage[key] for key in keys}
            usage_event = {'type': 'model_call', 'usage': usage}
            if getattr(config, 'model', None):
                usage_event['model'] = config.model
            if getattr(config, 'provider', None):
                usage_event['provider'] = config.provider
            publish(usage_event)
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
            tool_event = {"type": "tool_started", "name": call.get('name') or name, "call_id": call.get("id")}
            path = call.get('args', {}).get('path')
            if isinstance(path, str):
                tool_event['path'] = path[:1024]
            publish(tool_event)
        elif event.get("type") == "task_result":
            calls = payload.get("result", {}).get("tool_calls", [])
            if calls:
                call = calls[-1]
                tools_since_update += 1
                tool_failed = tool_failed or call.get('status') != 'completed'
                last_tool = call.get('name') or name
                tool_event = {"type": "tool_finished", "name": last_tool, "call_id": call.get("id"),
                              "status": call.get("status"), "result": str(call.get("result", ""))[:4096]}
                if len(str(call.get('result', ''))) > 4096:
                    tool_event['result_truncated'] = True
                path = call.get('args', {}).get('path')
                if isinstance(path, str):
                    tool_event['path'] = path[:1024]
                publish(tool_event)
    result = graph.get_state(options).values
    log_event('turn finished', {'thread_id': thread_id, 'answer': result.get('answer'),
                                'error': result.get('error'), 'model_calls': result.get('model_count'),
                                'tool_calls': result.get('tool_count')})
    return result
