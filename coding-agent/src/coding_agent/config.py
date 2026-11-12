import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values


@dataclass
class Config:
    model: str
    api_key: str = field(repr=False)
    jev_api_key: str = field(default="", repr=False)
    langsmith_api_key: str = field(default="", repr=False)
    langsmith_tracing: bool = False
    langsmith_project: str = "default"
    checkpoint_database_url: str = field(default="", repr=False)
    provider: str = "openrouter"


def load_config(env_file=None):
    # Read the local .env file; environment variables take priority.
    path = env_file if env_file is not None else Path(__file__).resolve().parents[2] / ".env"
    values = dotenv_values(path, interpolate=False)
    provider = (os.environ.get("MODEL_PROVIDER", values.get("MODEL_PROVIDER")) or "openrouter").strip().lower()
    if provider not in ("openrouter", "groq", "nvidia"):
        raise ValueError("MODEL_PROVIDER must be openrouter, groq, or nvidia.")
    key_name = {"groq": "GROQ_API_KEY", "nvidia": "NVIDIA_API_KEY", "openrouter": "OPENROUTER_API_KEY"}[provider]
    key = (os.environ.get(key_name, values.get(key_name)) or "").strip()
    jev_key = (os.environ.get("TYPESAFE_API_KEY", values.get("TYPESAFE_API_KEY")) or "").strip()
    model_name = {"groq": "GROQ_MODEL", "nvidia": "NVIDIA_MODEL", "openrouter": "OPENROUTER_MODEL"}[provider]
    default_model = {"groq": "openai/gpt-oss-120b", "nvidia": "nvidia/nemotron-3-ultra-550b-a55b", "openrouter": "openrouter/free"}[provider]
    model = (os.environ.get(model_name, values.get(model_name)) or default_model).strip()
    langsmith_key = (os.environ.get("LANGSMITH_API_KEY", values.get("LANGSMITH_API_KEY")) or "").strip()
    tracing = (os.environ.get("LANGSMITH_TRACING", values.get("LANGSMITH_TRACING")) or "false").strip().lower() == "true"
    project = (os.environ.get("LANGSMITH_PROJECT", values.get("LANGSMITH_PROJECT")) or "default").strip()
    database_url = (os.environ.get("CHECKPOINT_DATABASE_URL", values.get("CHECKPOINT_DATABASE_URL")) or "").strip()
    if not key:
        raise ValueError(f"Set {key_name} before running the agent.")
    if provider == "openrouter" and model != "openrouter/free" and not model.endswith(":free"):
        raise ValueError("Choose openrouter/free or a model ending in :free.")
    if tracing and not langsmith_key:
        raise ValueError("Set LANGSMITH_API_KEY when tracing is enabled.")
    return Config(model=model, api_key=key, jev_api_key=jev_key, langsmith_api_key=langsmith_key,
                  langsmith_tracing=tracing, langsmith_project=project, checkpoint_database_url=database_url,
                  provider=provider)
