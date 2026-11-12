from langchain_core.messages import AIMessage


class FakeModel:
    def __init__(self, answer=None, error=None):
        self.answer = answer
        self.error = error
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.error:
            raise self.error
        return self.answer


def test_invalid_prompt_never_calls_model():
    from coding_agent.graph import build_graph

    model = FakeModel()
    result = build_graph(model).invoke({"prompt": " "})
    assert result["error"]
    assert model.calls == 0


def test_plain_answer_is_returned():
    from coding_agent.graph import build_graph

    result = build_graph(FakeModel(AIMessage(content="Hello"))).invoke({"prompt": "Hi"})
    assert result["answer"] == "Hello"
    assert result["tool_calls"] == []


def test_multiple_tool_requests_are_shown_without_execution():
    from coding_agent.graph import build_graph

    message = AIMessage(content="", tool_calls=[
        {"name": "read_file", "args": {"path": "a.py"}, "id": "one"},
        {"name": "run_tests", "args": {}, "id": "two"},
    ])
    result = build_graph(FakeModel(message)).invoke({"prompt": "Fix the bug"})
    assert [call["id"] for call in result["tool_calls"]] == ["one", "two"]
    assert all(call["status"] == "not executed" for call in result["tool_calls"])


def test_bad_tool_request_and_model_error_are_reported():
    from coding_agent.graph import build_graph

    message = AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "one"}])
    assert build_graph(FakeModel(message)).invoke({"prompt": "Read"})["error"]
    result = build_graph(FakeModel(error=Exception("secret-value"))).invoke({"prompt": "Hi"})
    assert "secret-value" not in result["error"]
    assert result["error"]


def test_malformed_tool_arguments_are_reported():
    from coding_agent.graph import build_graph

    message = AIMessage(content="", invalid_tool_calls=[
        {"name": "read_file", "args": "{", "id": "one", "error": "Invalid JSON"}
    ])
    result = build_graph(FakeModel(message)).invoke({"prompt": "Read a file"})
    assert "malformed" in result["error"]
    assert result["tool_calls"] == []


def test_jev_checks_valid_prompt_before_model_and_does_not_block_it():
    from coding_agent.graph import build_graph

    events = []

    class TrackingModel(FakeModel):
        def invoke(self, messages):
            events.append("model")
            return super().invoke(messages)

    def check(prompt):
        events.append("jev")
        return 0.1

    result = build_graph(TrackingModel(AIMessage(content="Hello")), check).invoke({"prompt": "Hi"})
    assert events == ["jev", "model"]
    assert result["jev_score"] == 0.1
    assert result["answer"] == "Hello"


def test_jev_failure_is_reported_and_model_still_runs():
    from coding_agent.graph import build_graph

    def fail(prompt):
        raise ValueError("private secret")

    result = build_graph(FakeModel(AIMessage(content="Hello")), fail).invoke({"prompt": "Hi"})
    assert result["jev_score"] is None
    assert "private secret" not in result["jev_status"]
    assert result["answer"] == "Hello"


def test_model_uses_search_and_read_results(tmp_path):
    from coding_agent.graph import build_graph
    from langchain_core.messages import ToolMessage

    (tmp_path / "users.py").write_text("def authenticate_user():\n    pass\n", encoding="utf-8")
    responses = [
        AIMessage(content="", tool_calls=[{"name": "search_files", "args": {"path": ".", "query": "login"}, "id": "one"}]),
        AIMessage(content="", tool_calls=[{"name": "search_files", "args": {"path": ".", "query": "authenticate"}, "id": "two"}]),
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "users.py"}, "id": "three"}]),
        AIMessage(content="Found authentication code."),
    ]

    class Model:
        def __init__(self):
            self.messages = []

        def invoke(self, messages):
            self.messages.append(list(messages))
            return responses[len(self.messages) - 1]

    model = Model()
    result = build_graph(model, workspace=tmp_path).invoke({"prompt": "Find login code"})
    assert result["answer"] == "Found authentication code."
    results = [message for message in model.messages[-1] if isinstance(message, ToolMessage)]
    assert [message.tool_call_id for message in results] == ["one", "two", "three"]
    assert "No matches" in results[0].content
    assert "users.py:1" in results[1].content
    assert "authenticate_user" in results[2].content


def test_loop_stops_at_model_limit(tmp_path):
    from coding_agent.graph import build_graph

    message = AIMessage(content="", tool_calls=[{"name": "list_files", "args": {"path": "."}, "id": "one"}])
    model = FakeModel(message)
    result = build_graph(model, workspace=tmp_path).invoke({"prompt": "List files"})
    assert model.calls == 25
    assert "limit" in result["error"].lower()


def test_tool_errors_and_unavailable_tools_are_returned(tmp_path):
    from coding_agent.graph import build_graph
    from langchain_core.messages import ToolMessage

    class Model:
        def __init__(self):
            self.messages = []

        def invoke(self, messages):
            self.messages.append(list(messages))
            if len(self.messages) == 1:
                return AIMessage(content="", tool_calls=[
                    {"name": "read_file", "args": {"path": "../secret"}, "id": "one"},
                    {"name": "run_tests", "args": {}, "id": "two"},
                ])
            return AIMessage(content="Cannot run tests.")

    model = Model()
    result = build_graph(model, workspace=tmp_path).invoke({"prompt": "Run tests"})
    results = [message for message in model.messages[-1] if isinstance(message, ToolMessage)]
    assert len(results) == 2
    assert "not implemented" in results[1].content.lower()
    assert result["answer"] == "Cannot run tests."


def test_too_many_tool_calls_are_not_executed(tmp_path):
    from coding_agent.graph import build_graph

    calls = [{"name": "list_files", "args": {"path": "."}, "id": str(i)} for i in range(26)]
    result = build_graph(FakeModel(AIMessage(content="", tool_calls=calls)), workspace=tmp_path).invoke({"prompt": "List files"})
    assert "tool call limit" in result["error"].lower()
    assert not result.get("tool_calls")


def test_twenty_five_tool_calls_are_allowed(tmp_path):
    from coding_agent.graph import build_graph

    class Model:
        calls = 0
        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[
                    {"name": "list_files", "args": {"path": "."}, "id": str(i)} for i in range(25)])
            return AIMessage(content="done")

    result = build_graph(Model(), workspace=tmp_path).invoke({"prompt": "List files"})
    assert len(result["tool_calls"]) == 25
    assert result["answer"] == "done"


def test_malformed_tool_call_is_reported_to_model(tmp_path):
    from coding_agent.graph import build_graph
    from langchain_core.messages import ToolMessage

    class Model:
        def __init__(self):
            self.messages = []

        def invoke(self, messages):
            self.messages.append(list(messages))
            if len(self.messages) == 1:
                return AIMessage(content="", invalid_tool_calls=[
                    {"name": "read_file", "args": "{", "id": "bad", "error": "Invalid JSON"}
                ])
            return AIMessage(content="The request was invalid.")

    model = Model()
    result = build_graph(model, workspace=tmp_path).invoke({"prompt": "Read a file"})
    messages = [message for message in model.messages[-1] if isinstance(message, ToolMessage)]
    assert messages[0].tool_call_id == "bad"
    assert "invalid" in messages[0].content.lower()
    assert result["answer"] == "The request was invalid."


def test_graph_names_each_tool_step_and_keeps_request_order(tmp_path):
    from coding_agent.graph import build_graph

    (tmp_path / "app.py").write_text("example", encoding="utf-8")
    class Model:
        calls = 0
        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[
                    {"name": "list_files", "args": {"path": "."}, "id": "one"},
                    {"name": "read_file", "args": {"path": "app.py"}, "id": "two"},
                ])
            return AIMessage(content="done")

    updates = list(build_graph(Model(), workspace=tmp_path).stream({"prompt": "Inspect files"}))
    names = [name for update in updates for name in update]
    assert names.index("list_files") < names.index("read_file")
    assert "execute_tools" not in names
    assert names[-1] == "finish"


def test_checkpointed_turns_keep_history_and_reset_limits():
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.messages import HumanMessage
    from coding_agent.graph import build_graph

    class Model:
        def __init__(self):
            self.received = []
        def invoke(self, messages):
            self.received.append(list(messages))
            return AIMessage(content=f"answer {len(self.received)}")

    model = Model()
    graph = build_graph(model, checkpointer=InMemorySaver())
    thread = {"configurable": {"thread_id": "attempt-a"}}
    graph.invoke({"prompt": "first prompt"}, thread)
    result = graph.invoke({"prompt": "second prompt"}, thread)
    assert [message.content for message in model.received[-1] if isinstance(message, HumanMessage)] == ["first prompt", "second prompt"]
    assert result["answer"] == "answer 2"
    assert result["model_count"] == 1
    graph.invoke({"prompt": "separate"}, {"configurable": {"thread_id": "attempt-b"}})
    assert [message.content for message in model.received[-1] if isinstance(message, HumanMessage)] == ["separate"]


def test_long_history_stops_before_another_model_call():
    from langgraph.checkpoint.memory import InMemorySaver
    from coding_agent.graph import build_graph

    model = FakeModel(AIMessage(content="x" * 200001))
    graph = build_graph(model, checkpointer=InMemorySaver())
    thread = {"configurable": {"thread_id": "long"}}
    graph.invoke({"prompt": "first"}, thread)
    result = graph.invoke({"prompt": "second"}, thread)
    assert "history" in result["error"].lower()
    assert model.calls == 1


def test_existing_conversation_updates_only_our_original_instruction():
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.messages import HumanMessage, SystemMessage
    from coding_agent.graph import build_graph, ORIGINAL_INSTRUCTIONS, INSTRUCTIONS

    class Model:
        def __init__(self):
            self.messages = []
        def invoke(self, messages):
            self.messages.append(list(messages))
            return AIMessage(content='done')

    for instruction, expected in [(ORIGINAL_INSTRUCTIONS, INSTRUCTIONS), ('Custom instruction', 'Custom instruction')]:
        model = Model()
        graph = build_graph(model, checkpointer=InMemorySaver())
        result = graph.invoke({'prompt': 'continue', 'messages': [SystemMessage(content=instruction),
                              HumanMessage(content='earlier')]}, {'configurable': {'thread_id': 'example'}})
        assert model.messages[0][0].content == expected
        assert model.messages[0][1].content == 'earlier'
        assert result['answer'] == 'done'
