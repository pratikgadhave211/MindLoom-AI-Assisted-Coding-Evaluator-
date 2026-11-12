from fastapi.testclient import TestClient


def test_api_requires_token_and_starts_a_turn():
    from coding_agent.api import create_app

    class Manager:
        def create(self):
            return "attempt-1"
        def start_turn(self, attempt_id, prompt):
            assert attempt_id == "attempt-1" and prompt == "Inspect the project"
            return "turn-1"

    client = TestClient(create_app(manager=Manager(), token="local-test-token"))
    assert client.post("/attempts").status_code == 401
    headers = {"Authorization": "Bearer local-test-token"}
    response = client.post("/attempts", headers=headers)
    assert response.status_code == 201
    assert response.json()["attempt_id"] == "attempt-1"
    response = client.post("/attempts/attempt-1/turns", headers=headers, json={"prompt": "Inspect the project"})
    assert response.status_code == 202
    assert response.json()["turn_id"] == "turn-1"


def test_api_rejects_empty_prompt_and_unknown_attempt():
    from coding_agent.api import create_app

    class Manager:
        def start_turn(self, attempt_id, prompt):
            raise KeyError(attempt_id)
    client = TestClient(create_app(manager=Manager(), token="test"))
    headers = {"Authorization": "Bearer test"}
    assert client.post("/attempts/missing/turns", headers=headers, json={"prompt": "  "}).status_code == 400
    assert client.post("/attempts/missing/turns", headers=headers, json={"prompt": "hello"}).status_code == 404


def test_events_are_streamed_with_names_and_support_reconnect():
    from coding_agent.api import create_app

    class Manager:
        def events(self, attempt_id, turn_id, after, timeout=1):
            items = [
                {"id": 1, "type": "tool_started", "name": "read_file", "call_id": "one"},
                {"id": 2, "type": "tool_finished", "name": "read_file", "call_id": "one", "status": "completed"},
                {"id": 3, "type": "turn_finished", "status": "completed"},
            ]
            return [item for item in items if item["id"] > after], True

    client = TestClient(create_app(manager=Manager(), token="test"))
    headers = {"Authorization": "Bearer test", "Last-Event-ID": "1"}
    response = client.get("/attempts/a/turns/t/events", headers=headers)
    assert response.status_code == 200
    assert "event: tool_started" not in response.text
    assert "event: tool_finished" in response.text
    assert '"name": "read_file"' in response.text
    assert "event: turn_finished" in response.text


def test_editor_file_routes_report_version_conflicts():
    from coding_agent.api import create_app

    class Manager:
        def file(self, attempt_id, name, args):
            if name == "read_editor_file":
                return {"status": "completed", "result": {"content": "old", "version": "v1"}}
            return {"status": "conflict", "result": "File has changed."}

    client = TestClient(create_app(manager=Manager(), token="test"))
    headers = {"Authorization": "Bearer test"}
    response = client.get("/attempts/a/file", headers=headers, params={"path": "app.py"})
    assert response.json() == {"content": "old", "version": "v1"}
    response = client.put("/attempts/a/file", headers=headers, json={"path": "app.py", "content": "new", "expected_version": "v1"})
    assert response.status_code == 409
