import os
import queue
import subprocess
import threading

import pytest

from coding_agent.container_workspace import start_workspace, stop_workspace, resume_workspace, run_workspace_tool
from coding_agent.terminal import Terminal


@pytest.mark.skipif(os.environ.get('AGENT_NETWORK_TEST') != '1', reason='Requires Docker and package registry access')
def test_installs_are_shared_with_terminal_and_survive_workspace_reopen(tmp_path):
    template = tmp_path / 'template'
    template.mkdir()
    (template / 'app.py').write_text('print("hello")\n', encoding='utf-8')
    first = start_workspace(template)
    second = start_workspace(template)
    reopened = None
    terminal = None
    try:
        # Install from the agent, then read it from a real interactive terminal.
        result = run_workspace_tool(first, 'run_command', {'command': 'pip install PyJWT==2.10.1'})
        assert result['exit_code'] == 0, result['result']
        terminal = Terminal(first.container)
        outputs = queue.Queue()

        def collect():
            try:
                while True:
                    data = terminal.read()
                    if not data:
                        break
                    outputs.put(data.decode('utf-8', errors='replace'))
            except Exception:
                pass

        threading.Thread(target=collect, daemon=True).start()
        terminal.write("python -c 'import jwt; print(jwt.__version__)'; pip install idna==3.10; printf 'TERMINAL_%s:%s\\n' DONE $?\n")
        output = ''
        while 'TERMINAL_DONE:' not in output:
            output += outputs.get(timeout=180)
        assert '2.10.1' in output and 'TERMINAL_DONE:0' in output, output
        assert run_workspace_tool(first, 'run_command', {'command': 'python -c "import idna; print(idna.__version__)"'})['output'].strip() == '3.10'
        changed = run_workspace_tool(first, 'run_command', {'command': 'pip install idna==3.7'})
        assert changed['exit_code'] == 0, changed['result']
        assert run_workspace_tool(first, 'run_command', {'command': 'python -c "import idna; print(idna.__version__)"'})['output'].strip() == '3.7'
        assert run_workspace_tool(second, 'run_command', {'command': 'python -c "import jwt"'})['exit_code'] != 0
        npm = run_workspace_tool(first, 'run_command', {'command': 'npm install is-number@7.0.0 --no-audit --no-fund'})
        assert npm['exit_code'] == 0, npm['result']
        assert run_workspace_tool(first, 'run_command', {'command': 'node -e "console.log(require(\'is-number\')(42))"'})['output'].strip() == 'true'
        assert '.agent-deps' not in run_workspace_tool(first, 'list_files', {'path': '.'})['result']
        terminal.close()
        terminal = None
        stop_workspace(first)
        reopened = resume_workspace(first.volume)
        assert run_workspace_tool(reopened, 'run_command', {'command': 'python -c "import jwt; print(jwt.__version__)"'})['output'].strip() == '2.10.1'
        assert run_workspace_tool(reopened, 'run_command', {'command': 'python -c "import flask, pytest, fastapi"'})['exit_code'] == 0
    finally:
        if terminal:
            terminal.close()
        if reopened:
            stop_workspace(reopened)
        elif first.active:
            stop_workspace(first)
        stop_workspace(second)
        subprocess.run(['docker', 'volume', 'rm', first.volume, second.volume], check=True, capture_output=True)
