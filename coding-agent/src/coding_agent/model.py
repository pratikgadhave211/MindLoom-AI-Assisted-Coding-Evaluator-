from langchain_openrouter import ChatOpenRouter
from langchain_groq import ChatGroq
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from openrouter import OpenRouter


def make_model(config, tools):
    # Each provider receives the same workspace tool descriptions.
    if config.provider == "nvidia":
        model = ChatNVIDIA(model=config.model, api_key=config.api_key, temperature=0.4, top_p=0.95,
                           model_kwargs={"chat_template_kwargs": {"enable_thinking": True}}, timeout=90)
        return model.bind_tools(tools)
    if config.provider == "groq":
        model = ChatGroq(model=config.model, api_key=config.api_key, timeout=30, max_retries=0)
        return model.bind_tools(tools)
    # Explicitly disable SDK retries so a rate limit is reported promptly.
    client = OpenRouter(api_key=config.api_key, timeout_ms=30000, retry_config=None)
    model = ChatOpenRouter(
        model=config.model,
        api_key=config.api_key,
        client=client,
        timeout=30000,
        max_retries=0,
        openrouter_provider={"require_parameters": True},
    )
    return model.bind_tools(tools)


def model_error(error):
    # Provider errors may contain secrets, so display only safe explanations.
    status = getattr(error, "status_code", None)
    if status == 429:
        return "Model provider rate limit reached. Please try again later."
    if status in (401, 403):
        return "Model provider rejected access. Check your API key and account."
    if status == 404:
        return "Model unavailable or does not support tool calling. Choose another free model."
    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower():
        return "The model request timed out. Please try again."
    return "The model request failed. Check your connection and model settings."
