import os
import subprocess
import threading
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from coding_agent.api import create_app
from coding_agent.container_workspace import Attempt, run_workspace_tool


@pytest.mark.skipif(os.environ.get('AGENT_TERMINAL_TEST') != '1', reason='Requires Docker and the phase4 image')
def test_real_terminal_runs_commands_and_closes():
    name = 'terminal-test-' + uuid4().hex
    volume = name + '-workspace'
    subprocess.run(['docker', 'run', '-d', '--name', name, '--network', 'none', '--read-only',
                    '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges', '--memory', '512m', '--cpus', '1',
                    '--pids-limit', '128', '--mount', f'type=volume,source={volume},target=/workspace/challenge',
                    '--entrypoint', 'sleep', 'coding-agent-workspace:phase4', 'infinity'],
                   check=True, capture_output=True)
    released = threading.Event()
    class Manager:
        def terminal_workspace(self, attempt):
            assert attempt == 'a'
            return name
        def release_terminal(self, attempt):
            assert attempt == 'a'
            subprocess.run(['docker', 'restart', name], check=True, capture_output=True)
            released.set()
        def file(self, attempt, operation, args):
            return run_workspace_tool(Attempt(container=name, volume='unused'), operation, args)

    try:
        client = TestClient(create_app(manager=Manager(), token='test'))
        with client.websocket_connect('/attempts/a/terminal', headers={'origin': 'http://localhost:5174'}) as socket:
            socket.send_json({'token': 'test'})
            assert socket.receive_json()['type'] == 'ready'
            socket.send_json({'type': 'resize', 'cols': 100, 'rows': 30})
            socket.send_json({'type': 'input', 'data': "python --version; node --version; npm --version; node -e 'console.log(2+3)'; python -c 'import fastapi, uvicorn'; printf terminal-file > /workspace/challenge/phase4-check.txt; printf 'DONE_%s\\n' MARKER\n"})
            output = ''
            while 'DONE_MARKER' not in output or 'Python 3.' not in output or 'v24.' not in output:
                output += socket.receive_json().get('data', '')
            assert 'v24.' in output
            file_response = client.get('/attempts/a/file', params={'path': 'phase4-check.txt'}, headers={'Authorization': 'Bearer test'})
            assert file_response.json()['content'] == 'terminal-file'
            socket.send_json({'type': 'input', 'data': "printf 'from fastapi import FastAPI\\napp = FastAPI()\\n@app.get(\"/\")\\ndef root(): return {\"ok\": True}\\n' > /tmp/phase4_app.py\n"})
            socket.send_json({'type': 'input', 'data': 'cd /tmp && python -m uvicorn phase4_app:app --host 127.0.0.1 --port 8931\n'})
            output = ''
            while 'Uvicorn running on' not in output:
                output += socket.receive_json().get('data', '')
            reply = subprocess.run(['docker', 'exec', name, 'python', '-c',
                                    "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8931/').read().decode())"],
                                   check=True, capture_output=True, text=True, timeout=10)
            assert '"ok":true' in reply.stdout
            socket.send_json({'type': 'input', 'data': '\x03'})
            output = ''
            while 'Finished server process' not in output:
                output += socket.receive_json().get('data', '')
            socket.send_json({'type': 'input', 'data': "setsid sleep 120 >/dev/null 2>&1 & printf 'BG_%s\\n' READY\n"})
            output = ''
            while 'BG_READY' not in output:
                output += socket.receive_json().get('data', '')
            socket.send_json({'type': 'close'})
            assert released.wait(10)
            from starlette.websockets import WebSocketDisconnect
            with pytest.raises(WebSocketDisconnect):
                while True:
                    socket.receive_json()
        processes = subprocess.run(['docker', 'exec', name, 'ps', '-eo', 'args'], check=True, capture_output=True, text=True).stdout
        assert '/bin/bash -i' not in processes
        assert 'sleep 120' not in processes
        assert client.get('/attempts/a/file', params={'path': 'phase4-check.txt'}, headers={'Authorization': 'Bearer test'}).json()['content'] == 'terminal-file'
    finally:
        subprocess.run(['docker', 'rm', '-f', name], check=True, capture_output=True)
        subprocess.run(['docker', 'volume', 'rm', volume], check=True, capture_output=True)
