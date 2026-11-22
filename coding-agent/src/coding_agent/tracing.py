from langsmith import Client, traceable, tracing_context


@traceable(name="privacy_scan", run_type="chain")
def _privacy_scan_event(count, status):
    """Trace only scan metadata, never prompt text or detected values."""
    return {"masked_spans": count, "status": status}


def record_privacy_scan(config, count, status):
    """Send a standalone scan event without failing the agent on tracing errors."""
    if not getattr(config, "langsmith_tracing", False):
        return
    try:
        client = Client(api_key=config.langsmith_api_key)
        with tracing_context(enabled=True, project_name=config.langsmith_project, client=client):
            _privacy_scan_event(count, status)
        client.flush()
    except Exception:
        print("LangSmith could not record the privacy scan.")


def run_graph(graph, prompt, config, thread_id=None):
    def invoke():
        if thread_id is None:
            return graph.invoke({"prompt": prompt})
        return graph.invoke({"prompt": prompt}, {"configurable": {"thread_id": thread_id}})

    # The graph runs normally when tracing is switched off.
    if not config.langsmith_tracing:
        return invoke()

    # Keep the key in the controller; send traces to the selected project.
    client = Client(api_key=config.langsmith_api_key)
    try:
        with tracing_context(enabled=True, project_name=config.langsmith_project, client=client):
            return invoke()
    finally:
        try:
            client.flush()
        except Exception:
            print("LangSmith could not finish sending all traces.")


def stream_graph(graph, prompt, config, thread_id):
    options = {"configurable": {"thread_id": thread_id}}
    if not config.langsmith_tracing:
        yield from graph.stream({"prompt": prompt}, options, stream_mode="debug")
        return
    client = Client(api_key=config.langsmith_api_key)
    try:
        with tracing_context(enabled=True, project_name=config.langsmith_project, client=client):
            yield from graph.stream({"prompt": prompt}, options, stream_mode="debug")
    finally:
        try:
            client.flush()
        except Exception:
            print("LangSmith could not finish sending all traces.")
