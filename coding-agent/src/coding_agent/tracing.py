from langsmith import Client, tracing_context


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
