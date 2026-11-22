import json
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from .model import model_error
from .sanity import check_prompt
from .tools import TOOLS, execute_tool_call, validate_tool_call
from .diagnostics import log_event, log_error
from .privacy import RESERVED
from .input_guardrail import RISK_THRESHOLD
from .secret_store import write_env_secret

MODEL_CALL_LIMIT = 25
GUARDRAIL_MESSAGE = "I can't help with that request. Please rephrase it or provide more context so I can help."
ORIGINAL_INSTRUCTIONS = "You are a coding assistant. Inspect and edit the workspace using the available tools. Run tests when appropriate. Report actual tool results and do not claim tests passed if they failed or were not run."
INSTRUCTIONS = ORIGINAL_INSTRUCTIONS + (
    " Give brief user-facing progress updates at meaningful findings, changes of direction, blockers, "
    "or when starting verification. Do not narrate every tool call. "
    "When continuing, include the update with the next tool request. "
    "Base claims on actual results and do not reveal private reasoning. "
    "Use set_env_secret to place a secret placeholder in the root .env when the user asks. "
    "Never write placeholders using edit_file or run_command. Report only actual tool results."
)


# The graph passes this small shared state between its steps.
class AgentState(TypedDict, total=False):
    prompt: str
    answer: str
    tool_calls: list
    error: str
    response: Any
    input_guardrail: dict
    messages: list
    model_count: int
    tool_count: int
    pending_calls: list


def build_graph(model, workspace=None, checkpointer=None, input_checker=None):
    # Step 1: check the user's prompt before contacting the model.
    def check(state):
        try:
            prompt = check_prompt(state["prompt"])
            if state.get("pending_calls"):
                raise ValueError("The previous turn has unfinished tool calls; start a new conversation.")
            messages = list(state.get("messages", []))
            if not messages:
                messages.append(SystemMessage(content=INSTRUCTIONS))
            elif isinstance(messages[0], SystemMessage) and (messages[0].content == ORIGINAL_INSTRUCTIONS or
                    "Privacy placeholders represent unavailable values" in messages[0].content):
                # Refresh our old instruction while preserving the rest of the conversation.
                messages[0] = messages[0].model_copy(update={"content": INSTRUCTIONS})
            messages.append(HumanMessage(content=prompt))
            history = [message.model_dump(mode="json") for message in messages]
            if len(json.dumps(history, ensure_ascii=False, default=str).encode("utf-8")) > 200000:
                raise ValueError("Conversation history is too large; start a new conversation.")
            return {"prompt": prompt, "messages": messages, "error": "", "answer": "", "tool_calls": [],
                    "model_count": 0, "tool_count": 0, "pending_calls": []}
        except (KeyError, AttributeError, ValueError) as error:
            return {"error": str(error) or "Please enter a prompt."}

    def check_input_guardrail(state):
        """Run the NeMo input rail on the protected prompt."""
        if input_checker is None:
            return {"input_guardrail": {"rule_status": "not configured", "jev_status": "not configured", "risk_score": None,
                                        "threshold": RISK_THRESHOLD, "flagged": None}}
        try:
            result = input_checker(state["prompt"])
            log_event("input guardrail", result)
            return {"input_guardrail": result}
        except Exception:
            result = {"rule_status": "unavailable", "jev_status": "unavailable", "risk_score": None,
                      "threshold": RISK_THRESHOLD, "flagged": None}
            log_event("input guardrail", result)
            return {"input_guardrail": result}

    def reject_input(state):
        """Reply without calling the model when the input guardrail flags a prompt."""
        return {"answer": GUARDRAIL_MESSAGE,
                "messages": list(state["messages"]) + [AIMessage(content=GUARDRAIL_MESSAGE)]}

    # Step 3: ask the model to answer or choose from the available tools.
    def ask_model(state):
        try:
            messages = state["messages"]
            response = model.invoke(messages)
            log_event('model response', {'content': response.text, 'tool_calls': response.tool_calls,
                                         'invalid_tool_calls': response.invalid_tool_calls,
                                         'usage': response.usage_metadata})
            pending = [(True, call) for call in response.invalid_tool_calls]
            pending += [(False, call) for call in response.tool_calls]
            return {"response": response, "messages": messages + [response], "model_count": state.get("model_count", 0) + 1, "pending_calls": pending}
        except Exception as error:
            log_error('model error', error)
            return {"error": model_error(error)}

    # Step 4: show validated requests without running any tools.
    def show_result(state):
        if state.get("error"):
            return {"answer": "", "tool_calls": state.get("tool_calls", [])}
        response = state["response"]
        if response.invalid_tool_calls:
            return {"error": "The model returned malformed tool arguments.", "answer": "", "tool_calls": []}
        try:
            calls = [validate_tool_call(call) for call in response.tool_calls]
        except (ValueError, TypeError, AttributeError):
            return {"error": "The model returned an unknown or invalid tool request.", "answer": "", "tool_calls": []}
        return {"answer": response.text, "tool_calls": calls}

    # Run one requested tool per step so the trace can show its actual name.
    def execute_tool(state):
        invalid, call = state["pending_calls"][0]
        log_event('tool request', call)
        pending = state["pending_calls"][1:]
        messages = list(state["messages"])
        results = list(state.get("tool_calls", []))
        if invalid:
            if not call.get("id"):
                return {"error": "The model returned a malformed tool request without an ID."}
            result = {"id": call["id"], "name": call.get("name") or "unknown", "args": {}, "status": "error", "result": "Invalid tool request: malformed arguments."}
        else:
            try:
                args = call.get("args", {})
                if call.get("name") == "set_env_secret":
                    result = validate_tool_call(call)
                    store = getattr(workspace, "secret_store", None)
                    message = write_env_secret(workspace, store, args["name"], args["placeholder"]) if store else "The secret was not written: placeholder unavailable."
                    result.update(status="completed" if message.startswith("The secret was written") else "error", result=message)
                elif call.get("id") and call.get("name") in ("edit_file", "run_command") and any(
                    RESERVED.search(value) for value in args.values() if isinstance(value, str)
                ):
                    result = {"id": call["id"], "name": call["name"], "args": args, "status": "error",
                              "result": "Privacy placeholder resolution is not available. The secret was not written."}
                else:
                    result = execute_tool_call(workspace, call, langsmith_extra={"name": call.get("name", "unknown_tool")})
            except (ValueError, TypeError, AttributeError):
                if not call.get("id"):
                    return {"error": "The model returned a tool request without an ID."}
                result = {"id": call["id"], "name": call.get("name", "unknown"), "args": call.get("args", {}), "status": "error", "result": "Invalid tool request."}
        log_event('tool result', result)
        results.append(result)
        messages.append(ToolMessage(content=result["result"], tool_call_id=result["id"]))
        update = {"messages": messages, "tool_calls": results, "pending_calls": pending,
                  "tool_count": state.get("tool_count", 0) + 1}
        if not pending and state.get("model_count", 0) >= MODEL_CALL_LIMIT:
            update["error"] = "Model call limit reached; the task is incomplete."
        return update

    def next_tool(state):
        invalid, call = state["pending_calls"][0]
        name = call.get("name")
        if invalid or name not in tool_names:
            return "invalid_tool"
        return name

    def after_model(state):
        if state.get("error") or workspace is None:
            return "show_result"
        if state.get("pending_calls"):
            return next_tool(state)
        return "finish"

    def after_tool(state):
        if state.get("error"):
            return END
        if state.get("pending_calls"):
            return next_tool(state)
        return "ask_model"

    def finish(state):
        return {"answer": state["response"].text, "tool_calls": state.get("tool_calls", [])}

    graph = StateGraph(AgentState)
    graph.add_node("check_prompt", check)
    graph.add_node("input_guardrail", check_input_guardrail)
    graph.add_node("reject_input", reject_input)
    graph.add_node("ask_model", ask_model)
    graph.add_node("show_result", show_result)
    tool_names = {item.name for item in TOOLS}
    for name in tool_names:
        graph.add_node(name, execute_tool)
    graph.add_node("invalid_tool", execute_tool)
    graph.add_node("finish", finish)
    graph.add_edge(START, "check_prompt")
    graph.add_conditional_edges("check_prompt", lambda state: "show_result" if state.get("error") else "input_guardrail")
    graph.add_conditional_edges("input_guardrail", lambda state: "reject_input"
                                if state.get("input_guardrail", {}).get("flagged") is True else "ask_model")
    graph.add_edge("reject_input", END)
    graph.add_conditional_edges("ask_model", after_model)
    for name in tool_names | {"invalid_tool"}:
        graph.add_conditional_edges(name, after_tool)
    graph.add_edge("show_result", END)
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)
