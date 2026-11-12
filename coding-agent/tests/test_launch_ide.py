import pytest

from coding_agent.launch_ide import launch


def test_launch_creates_attempt_and_starts_ide():
    calls = []

    def post(path):
        calls.append(path)
        if path == "/attempts":
            return {"attempt_id": "abc"}
        return {"url": "http://127.0.0.1:3000/?agentic_attempt=abc"}

    result = launch(post)
    assert calls == ["/attempts", "/attempts/abc/ide"]
    assert result["attempt_id"] == "abc"


def test_launch_resumes_existing_attempt():
    calls = []
    attempt_id = "12345678-1234-4234-8234-123456789abc"

    def post(path):
        calls.append(path)
        return {"attempt_id": "abc", "url": "http://127.0.0.1:3000/"}

    launch(post, attempt_id)
    assert calls == [f"/attempts/{attempt_id}/resume", f"/attempts/{attempt_id}/ide"]


def test_launch_reports_attempt_when_ide_fails():
    def post(path):
        if path == "/attempts":
            return {"attempt_id": "abc"}
        raise RuntimeError("Theia could not start")

    with pytest.raises(RuntimeError, match="abc"):
        launch(post)
