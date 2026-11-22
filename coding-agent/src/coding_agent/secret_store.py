"""Temporarily encrypt prompt secrets and write them through a controlled tool."""

import json
import re
import subprocess

from cryptography.fernet import Fernet

from .container_workspace import Attempt


class SecretStore:
    """Keep encrypted values only for the current agent turn."""

    def __init__(self):
        self.cipher = Fernet(Fernet.generate_key())
        self.values = {}

    def store(self, value):
        """Encrypt a value and return a placeholder for the model."""
        token = f"[SECRET_{len(self.values) + 1}]"
        self.values[token] = self.cipher.encrypt(value.encode("utf-8"))
        return token

    def resolve(self, token):
        """Decrypt a known placeholder, or return None after it is cleared."""
        value = self.values.get(token)
        return self.cipher.decrypt(value).decode("utf-8") if value is not None else None

    def clear(self):
        """Remove the encrypted values when the turn ends."""
        self.values.clear()


def write_env_secret(workspace, store, name, placeholder):
    """Write one secret into the workspace root .env without logging its value."""
    if not isinstance(workspace, Attempt) or not workspace.active:
        return "The secret was not written: workspace unavailable."
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return "The secret was not written: invalid environment variable name."
    value = store.resolve(placeholder)
    if value is None or any(char in value for char in "\r\n\0"):
        return "The secret was not written: placeholder unavailable or unsupported value."
    # The value is passed through stdin, never the command line or tool trace.
    script = '''import json, os, re, sys
data = json.load(sys.stdin)
os.chdir('/workspace/challenge')
flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
fd = os.open('.env', flags, 0o600)
with os.fdopen(fd, 'r+', encoding='utf-8') as f:
    lines = f.read().splitlines()
    prefix = data['name'] + '='
    lines = [line for line in lines if not line.startswith(prefix)]
    lines.append(prefix + json.dumps(data['value'], ensure_ascii=False))
    f.seek(0)
    f.write('\\n'.join(lines) + '\\n')
    f.truncate()
'''
    try:
        subprocess.run(["docker", "exec", "-i", workspace.container, "python", "-c", script],
                       input=json.dumps({"name": name, "value": value}), text=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "The secret was not written: workspace operation failed."
    return f"The secret was written to .env as {name}."
