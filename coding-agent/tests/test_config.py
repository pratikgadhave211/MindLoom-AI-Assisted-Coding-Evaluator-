import pytest


def test_key_and_free_model_are_required(monkeypatch, tmp_path):
    from coding_agent.config import load_config

    env_file = tmp_path / ".env"
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        load_config(env_file)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "paid/model")
    with pytest.raises(ValueError, match="free"):
        load_config(env_file)
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/free")
    assert load_config(env_file).model == "openrouter/free"


def test_dotenv_is_loaded_and_environment_takes_priority(monkeypatch, tmp_path):
    from coding_agent.config import load_config

    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=file-key\nOPENROUTER_MODEL=openrouter/free\nTYPESAFE_API_KEY=jev-key\n")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert load_config(env_file).api_key == "file-key"
    assert load_config(env_file).jev_api_key == "jev-key"
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-key")
    assert load_config(env_file).api_key == "environment-key"


def test_langsmith_settings_are_loaded_without_printing_key(monkeypatch, tmp_path):
    from coding_agent.config import load_config

    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=test\nLANGSMITH_API_KEY=private-key\nLANGSMITH_TRACING=true\nLANGSMITH_PROJECT=agentic ide tracing\n")
    monkeypatch.delenv("LANGSMITH_TRACING")
    config = load_config(env_file)
    assert config.langsmith_tracing is True
    assert config.langsmith_project == "agentic ide tracing"
    assert config.langsmith_api_key == "private-key"
    assert "private-key" not in repr(config)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    assert load_config(env_file).langsmith_tracing is False


def test_checkpoint_database_url_is_private(monkeypatch, tmp_path):
    from coding_agent.config import load_config

    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=test\nCHECKPOINT_DATABASE_URL=postgresql://agent:secret@localhost/agent\n")
    monkeypatch.delenv("CHECKPOINT_DATABASE_URL", raising=False)
    config = load_config(env_file)
    assert config.checkpoint_database_url.startswith("postgresql://")
    assert "secret" not in repr(config)


def test_groq_provider_uses_its_own_key_and_default_model(monkeypatch, tmp_path):
    from coding_agent.config import load_config

    env_file = tmp_path / '.env'
    env_file.write_text('MODEL_PROVIDER=groq\nGROQ_API_KEY=private-groq-key\n')
    monkeypatch.delenv('MODEL_PROVIDER', raising=False)
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    config = load_config(env_file)
    assert config.provider == 'groq'
    assert config.model == 'openai/gpt-oss-120b'
    assert config.api_key == 'private-groq-key'
    assert 'private-groq-key' not in repr(config)


def test_groq_requires_key(monkeypatch, tmp_path):
    from coding_agent.config import load_config

    monkeypatch.setenv('MODEL_PROVIDER', 'groq')
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    with pytest.raises(ValueError, match='GROQ_API_KEY'):
        load_config(tmp_path / '.env')


def test_nvidia_provider_loads_model_and_key(monkeypatch, tmp_path):
    from coding_agent.config import load_config

    env_file = tmp_path / '.env'
    env_file.write_text('MODEL_PROVIDER=nvidia\nNVIDIA_API_KEY=private-nvidia-key\n')
    monkeypatch.delenv('MODEL_PROVIDER', raising=False)
    monkeypatch.delenv('NVIDIA_API_KEY', raising=False)
    config = load_config(env_file)
    assert config.provider == 'nvidia'
    assert config.model == 'nvidia/nemotron-3-ultra-550b-a55b'
    assert config.api_key == 'private-nvidia-key'
    assert 'private-nvidia-key' not in repr(config)
