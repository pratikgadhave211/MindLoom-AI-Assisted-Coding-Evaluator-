from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest
from types import SimpleNamespace

from coding_agent.api import create_app


def test_terminal_requires_valid_origin_and_token():
    class Manager:
        def terminal_workspace(self, attempt):
            raise AssertionError('Unauthenticated requests must not open a shell')

    client = TestClient(create_app(manager=Manager(), token='local-token'))
    try:
        with client.websocket_connect('/attempts/a/terminal', headers={'origin': 'http://malicious.example'}):
            assert False, 'An untrusted origin connected'
    except WebSocketDisconnect as error:
        assert error.code == 1008
    with client.websocket_connect('/attempts/a/terminal', headers={'origin': 'http://localhost:5174'}) as socket:
        socket.send_json({'token': 'wrong'})
        try:
            socket.receive_json()
            assert False, 'An incorrect token connected'
        except WebSocketDisconnect as error:
            assert error.code == 1008


def test_terminal_rejects_unknown_attempt():
    class Manager:
        def terminal_workspace(self, attempt):
            raise KeyError(attempt)

    client = TestClient(create_app(manager=Manager(), token='local-token'))
    with client.websocket_connect('/attempts/missing/terminal', headers={'origin': 'http://localhost:5174'}) as socket:
        socket.send_json({'token': 'local-token'})
        assert socket.receive_json()['type'] == 'error'


def test_open_terminal_prevents_agent_turns_and_editor_saves():
    from coding_agent.attempts import AttemptManager
    manager = AttemptManager()
    manager.attempts['a'] = {'workspace': SimpleNamespace(active=True), 'busy': False, 'terminal_open': True}
    with pytest.raises(ValueError, match='terminal'):
        manager.start_turn('a', 'change a file')
    with pytest.raises(ValueError, match='terminal'):
        manager.file('a', 'write_editor_file', {})


def test_terminal_disconnect_restarts_workspace_and_clears_reservation(monkeypatch):
    from coding_agent import attempts
    calls = []
    monkeypatch.setattr(attempts, 'docker', lambda *args: calls.append(args))
    manager = attempts.AttemptManager()
    manager.attempts['a'] = {'workspace': SimpleNamespace(container='workspace', active=True), 'terminal_open': True}
    manager.release_terminal('a')
    assert calls == [('restart', 'workspace')]
    assert manager.attempts['a']['terminal_open'] is False
