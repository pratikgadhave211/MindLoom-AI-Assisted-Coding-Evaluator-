import pytest


@pytest.fixture(autouse=True)
def disable_live_tracing(monkeypatch):
    # Tests must never send local prompts or code to a real tracing account.
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
