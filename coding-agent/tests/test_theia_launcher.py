from types import SimpleNamespace


def test_theia_uses_attempt_volume_and_loopback_port(monkeypatch):
    from coding_agent import attempts

    commands = []
    monkeypatch.setattr(attempts, "docker", lambda *args: commands.append(args))
    manager = attempts.AttemptManager()
    manager.attempts["attempt-1"] = {"workspace": SimpleNamespace(volume="coding-agent-test-workspace", active=True), "busy": False}
    url = manager.start_ide("attempt-1")
    command = commands[0]
    assert "127.0.0.1:3000:3000" in command
    assert any("source=coding-agent-test-workspace,target=/workspace/challenge" in part for part in command)
    assert "agentic_attempt=attempt-1" in url
    assert not any("AGENT_API_TOKEN" in part for part in command)
