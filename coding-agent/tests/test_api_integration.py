import os
import subprocess

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage


@pytest.mark.skipif(os.environ.get("AGENT_POSTGRES_TEST") != "1" or os.environ.get("AGENT_DOCKER_TEST") != "1", reason="Docker and PostgreSQL integration are opt-in")
def test_api_two_turns_share_conversation_and_workspace(monkeypatch):
    from coding_agent import agent
    from coding_agent.api import create_app
    from coding_agent.attempts import AttemptManager
    from coding_agent.config import load_config
    from coding_agent.memory import open_memory

    class Model:
        def __init__(self):
            self.messages = []
        def invoke(self, messages):
            self.messages.append(list(messages))
            if len(self.messages) == 1:
                return AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "flaskr/blog.py"}, "id": "read"}])
            return AIMessage(content="done")

    model = Model()
    monkeypatch.setattr(agent, "make_model", lambda config, tools: model)
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    manager = AttemptManager()
    client = TestClient(create_app(manager=manager, token="test-token"))
    headers = {"Authorization": "Bearer test-token"}
    attempt_id = client.post("/attempts", headers=headers).json()["attempt_id"]
    volume = manager.attempts[attempt_id]["workspace"].volume
    try:
        path = "flaskr/blog.py"
        current = client.get(f"/attempts/{attempt_id}/file", headers=headers, params={"path": path}).json()
        changed = current["content"].replace("Show all the posts, most recent first.", "Show the newest blog posts first.")
        saved = client.put(f"/attempts/{attempt_id}/file", headers=headers, json={"path": path, "content": changed, "expected_version": current["version"]})
        assert saved.status_code == 200
        stale = client.put(f"/attempts/{attempt_id}/file", headers=headers, json={"path": path, "content": changed, "expected_version": current["version"]})
        assert stale.status_code == 409
        first = client.post(f"/attempts/{attempt_id}/turns", headers=headers, json={"prompt": "read the blog"}).json()["turn_id"]
        events = client.get(f"/attempts/{attempt_id}/turns/{first}/events", headers=headers).text
        assert "event: tool_started" in events and '"name": "read_file"' in events
        assert "event: tool_finished" in events and "event: turn_finished" in events
        assert "Show the newest blog posts first." in events
        second = client.post(f"/attempts/{attempt_id}/turns", headers=headers, json={"prompt": "what did you read?"}).json()["turn_id"]
        assert "event: answer" in client.get(f"/attempts/{attempt_id}/turns/{second}/events", headers=headers).text
        humans = [message.content for message in model.messages[-1] if isinstance(message, HumanMessage)]
        assert humans == ["read the blog", "what did you read?"]
        history = client.get(f"/attempts/{attempt_id}/history", headers=headers).json()
        assert history['running_turn'] is None
        assert history['messages'] == [
            {'role': 'user', 'content': 'read the blog'}, {'role': 'assistant', 'content': 'done'},
            {'role': 'user', 'content': 'what did you read?'}, {'role': 'assistant', 'content': 'done'},
        ]

        class EditModel:
            calls = 0
            def invoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(content='', tool_calls=[{'name': 'edit_file', 'id': 'edit', 'args': {
                        'path': path, 'old_text': 'Show the newest blog posts first.',
                        'new_text': 'Show recent blog posts first.'}}])
                return AIMessage(content='Updated.')

        editor = EditModel()
        monkeypatch.setattr(agent, 'make_model', lambda config, tools: editor)
        third = client.post(f'/attempts/{attempt_id}/turns', headers=headers, json={'prompt': 'Update the description'}).json()['turn_id']
        edit_events = client.get(f'/attempts/{attempt_id}/turns/{third}/events', headers=headers).text
        assert '"name": "edit_file"' in edit_events and 'Updated.' in edit_events
        after = client.get(f'/attempts/{attempt_id}/file', headers=headers, params={'path': path}).json()
        assert 'Show recent blog posts first.' in after['content']
        assert client.put(f'/attempts/{attempt_id}/file', headers=headers, json={
            'path': path, 'content': changed, 'expected_version': saved.json()['version']}).status_code == 409
        assert client.delete(f"/attempts/{attempt_id}", headers=headers).json()["workspace_volume"] == volume
        assert client.post(f'/attempts/{attempt_id}/resume', headers=headers).status_code == 200
        restored = client.get(f'/attempts/{attempt_id}/history', headers=headers).json()
        assert restored['messages'][-2:] == [
            {'role': 'user', 'content': 'Update the description'}, {'role': 'assistant', 'content': 'Updated.'}]
        assert 'Show recent blog posts first.' in client.get(
            f'/attempts/{attempt_id}/file', headers=headers, params={'path': path}).json()['content']
        assert client.delete(f"/attempts/{attempt_id}", headers=headers).json()["workspace_volume"] == volume
    finally:
        if attempt_id in manager.attempts:
            manager.close(attempt_id)
        with open_memory(load_config().checkpoint_database_url, attempt_id) as memory:
            memory.delete_thread(attempt_id)
            memory.conn.execute("DELETE FROM agent_workspaces WHERE thread_id = %s", (attempt_id,))
        subprocess.run(["docker", "volume", "rm", volume], check=True, capture_output=True)
