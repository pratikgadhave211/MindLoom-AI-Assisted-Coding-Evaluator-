import json
import re
import subprocess
import tarfile
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from .workspace_core import create_workspace


IMAGE = "coding-agent-workspace:latest"
OUTPUT_LIMIT = 64 * 1024
COMMAND_TIMEOUT = 120


@dataclass
class Attempt:
    container: str
    volume: str
    active: bool = True


def docker(*args):
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=60)


def launch_container(attempt):
    docker("run", "-d", "--name", attempt.container, "--network", "bridge", "--read-only",
           "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--cap-drop", "ALL",
           "--security-opt", "no-new-privileges", "--memory", "512m", "--cpus", "1",
           "--pids-limit", "128", "--mount", f"type=volume,source={attempt.volume},target=/workspace/challenge",
           "--entrypoint", "sleep", IMAGE, "infinity")


def start_workspace(template: Path) -> Attempt:
    name = "coding-agent-" + uuid.uuid4().hex
    attempt = Attempt(container=name, volume=name + "-workspace")
    try:
        # Seed through a temporary copy, without mounting the host project.
        with tempfile.TemporaryDirectory() as temporary:
            copy = create_workspace(template, Path(temporary))
            launch_container(attempt)
            with tempfile.TemporaryFile() as archive:
                with tarfile.open(fileobj=archive, mode="w") as tar:
                    tar.add(copy, arcname=".")
                archive.seek(0)
                subprocess.run(["docker", "exec", "-i", name, "tar", "--no-same-owner", "--no-same-permissions", "-xf", "-", "-C", "/workspace/challenge"], stdin=archive, check=True, capture_output=True, timeout=60)
        return attempt
    except (OSError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        try:
            docker("rm", "-f", name)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            docker("volume", "rm", attempt.volume)
        except (OSError, subprocess.SubprocessError):
            pass
        if isinstance(error, KeyboardInterrupt):
            raise
        raise RuntimeError("Could not start the isolated workspace. Check Docker and the workspace image.") from error


def resume_workspace(volume: str) -> Attempt:
    # Never let a saved record select an arbitrary Docker volume.
    if not re.fullmatch(r"coding-agent-[0-9a-f]{32}-workspace", volume):
        raise ValueError("Invalid saved workspace name.")
    attempt = Attempt(container="coding-agent-" + uuid.uuid4().hex, volume=volume)
    try:
        docker("volume", "inspect", volume)
        # A crashed server can leave its old container and commands running.
        running = docker("ps", "--filter", f"volume={volume}", "--format", "{{.Names}}\t{{.Image}}")
        containers = [line.split('\t') for line in running.stdout.splitlines()]
        if any(len(item) != 2 or not re.fullmatch(r"coding-agent-[0-9a-f]{32}", item[0])
               or item[1] != IMAGE for item in containers):
            raise RuntimeError("Cannot resume the workspace while another container is using it.")
        for name, _ in containers:
            state = docker('inspect', '--format', '{{.State.Paused}}', name).stdout.strip()
            if state == 'true':
                docker('unpause', name)
            docker("rm", "-f", name)
        launch_container(attempt)
        return attempt
    except (OSError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        try:
            docker("rm", "-f", attempt.container)
        except (OSError, subprocess.SubprocessError):
            pass
        if isinstance(error, KeyboardInterrupt):
            raise
        raise RuntimeError("Could not resume the saved workspace. Check Docker and the volume.") from error


def stop_workspace(attempt: Attempt):
    try:
        docker("rm", "-f", attempt.container)
        attempt.active = False
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Could not remove the attempt container; check Docker.") from None


def run_in_container(attempt: Attempt, args: list, input_text=None, output_limit=OUTPUT_LIMIT) -> dict:
    if not attempt.active:
        return {"output": "Workspace stopped.", "exit_code": None, "timed_out": False, "truncated": False}
    command = ["docker", "exec", "-i", "-w", "/workspace/challenge", attempt.container, *args]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    chunks = []
    size = 0
    truncated = False

    def collect_output():
        nonlocal size, truncated
        while True:
            chunk = process.stdout.read(8192)
            if not chunk:
                break
            remaining = output_limit - size
            if remaining > 0:
                chunks.append(chunk[:remaining])
                size += min(len(chunk), remaining)
            if len(chunk) > remaining:
                truncated = True

    reader = threading.Thread(target=collect_output, daemon=True)
    reader.start()
    input_errors = []

    def send_input():
        try:
            if input_text:
                process.stdin.write(input_text.encode("utf-8"))
            process.stdin.close()
        except OSError:
            input_errors.append("Could not send input to the workspace.")

    writer = threading.Thread(target=send_input, daemon=True)
    writer.start()
    try:
        process.wait(timeout=COMMAND_TIMEOUT)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        try:
            docker("kill", attempt.container)
        finally:
            attempt.active = False
            process.kill()
            process.wait()
            reader.join(timeout=5)
            writer.join(timeout=5)
        if isinstance(error, KeyboardInterrupt):
            raise
        return {"output": "Command timed out; the workspace stopped.", "exit_code": None, "timed_out": True, "truncated": truncated}
    reader.join(timeout=5)
    writer.join(timeout=5)
    if input_errors:
        return {"output": input_errors[0], "exit_code": None, "timed_out": False, "truncated": truncated}
    data = b"".join(chunks)
    if truncated:
        notice = b"\n[Output truncated]"
        data = data[:output_limit - len(notice)] + notice
    output = data.decode("utf-8", errors="replace")
    return {"output": output, "exit_code": process.returncode, "timed_out": False, "truncated": truncated}


def run_workspace_tool(attempt: Attempt, name: str, args: dict) -> dict:
    if name in ("list_files", "search_files", "read_file", "edit_file", "read_editor_file", "write_editor_file"):
        request = json.dumps({"name": name, "args": args})
        limit = 8 * 1024 * 1024 if name == "read_editor_file" else OUTPUT_LIMIT * 8
        response = run_in_container(attempt, ["python", "/opt/coding-agent/container_runner.py"], request, output_limit=limit)
        if response["exit_code"] != 0 or response["truncated"]:
            return {"status": "error", "result": response["output"] or "Workspace operation failed."}
        try:
            return json.loads(response["output"])
        except ValueError:
            return {"status": "error", "result": "Invalid response from workspace."}
    if name == "run_tests":
        command = ["python", "-m", "pytest", "-q"]
    elif name == "run_command" and args.get("command", "").strip():
        command = ["sh", "-c", args["command"]]
    else:
        return {"status": "error", "result": "Unknown tool or empty command."}
    response = run_in_container(attempt, command)
    response["status"] = "completed" if response["exit_code"] == 0 else "error"
    response["result"] = f"Exit code: {response['exit_code']}\n{response['output']}"
    return response
