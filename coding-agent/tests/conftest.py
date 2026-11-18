import pytest


@pytest.fixture(autouse=True)
def disable_live_tracing(monkeypatch):
    # Tests must never send local prompts or code to a real tracing account.
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    # Real Jev calls are covered only by explicitly run synthetic smoke tests.
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
