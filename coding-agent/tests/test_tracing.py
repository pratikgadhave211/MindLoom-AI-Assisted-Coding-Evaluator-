from contextlib import contextmanager
from types import SimpleNamespace

from coding_agent import tracing


def test_graph_is_traced_to_requested_project_and_flushed(monkeypatch):
    events = []

    class Client:
        def __init__(self, api_key):
            events.append(("client", api_key))
        def flush(self):
            events.append(("flush",))

    @contextmanager
    def context(**kwargs):
        events.append(("context", kwargs["enabled"], kwargs["project_name"]))
        yield

    class Graph:
        def invoke(self, state):
            events.append(("graph", state["prompt"]))
            return {"answer": "ok"}

    monkeypatch.setattr(tracing, "Client", Client)
    monkeypatch.setattr(tracing, "tracing_context", context)
    config = SimpleNamespace(langsmith_tracing=True, langsmith_api_key="test-key", langsmith_project="agentic ide tracing")
    assert tracing.run_graph(Graph(), "hello", config) == {"answer": "ok"}
    assert events == [("client", "test-key"), ("context", True, "agentic ide tracing"), ("graph", "hello"), ("flush",)]


def test_disabled_tracing_does_not_create_client(monkeypatch):
    def fail(**kwargs):
        raise AssertionError("Client should not be created")
    monkeypatch.setattr(tracing, "Client", fail)
    graph = SimpleNamespace(invoke=lambda state: {"answer": state["prompt"]})
    config = SimpleNamespace(langsmith_tracing=False)
    assert tracing.run_graph(graph, "hello", config) == {"answer": "hello"}


def test_thread_id_is_sent_to_the_graph():
    calls = []
    class Graph:
        def invoke(self, state, config=None):
            calls.append((state, config))
            return {"answer": "ok"}
    config = SimpleNamespace(langsmith_tracing=False)
    tracing.run_graph(Graph(), "hello", config, thread_id="attempt-1")
    assert calls[0][1]["configurable"]["thread_id"] == "attempt-1"
