import re
import subprocess
from uuid import UUID, uuid4

from .container_workspace import IMAGE, docker


# Run this fixed copy program inside a network-free helper container.
COPY_SNAPSHOT = '''
import os, shutil, stat
from pathlib import Path
source = Path('/source')
destination = Path('/snapshot')
skip = {'.git', '.venv', '.agent-deps', 'node_modules', '__pycache__', '.pytest_cache', 'instance'}
total = 0
count = 0
for folder, directories, files in os.walk(source, followlinks=False):
    directories[:] = [name for name in directories if name not in skip]
    relative = Path(folder).relative_to(source)
    target = destination / relative
    target.mkdir(parents=True, exist_ok=True)
    for name in directories + files:
        path = Path(folder) / name
        if path.is_symlink():
            raise ValueError('Workspace contains a symbolic link')
    for name in files:
        path = Path(folder) / name
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Workspace contains an unsupported file')
        count += 1
        total += info.st_size
        if count > 20000 or total > 100 * 1024 * 1024:
            raise ValueError('Workspace exceeds snapshot limits')
        shutil.copy2(path, target / name)
'''


def snapshot_name(submission_id):
    return 'coding-agent-submission-' + UUID(submission_id).hex


def create_snapshot(attempt, submission_id=None):
    """Freeze one workspace in a new Docker volume while its container is paused."""
    if not re.fullmatch(r'coding-agent-[0-9a-f]{32}-workspace', attempt.volume):
        raise ValueError('Invalid workspace volume.')
    containers = docker('ps', '--filter', f'volume={attempt.volume}', '--format', '{{.Names}}').stdout.splitlines()
    if any(name != attempt.container for name in containers):
        raise ValueError('Another container is using the workspace.')
    suffix = UUID(submission_id).hex if submission_id else uuid4().hex
    snapshot = 'coding-agent-submission-' + suffix
    helper = 'coding-agent-snapshot-' + suffix
    paused = False
    created = False
    try:
        docker('volume', 'create', snapshot)
        created = True
        docker('pause', attempt.container)
        paused = True
        docker('run', '--rm', '--name', helper, '--network', 'none', '--read-only', '--user', '0:0',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '256m',
               '--pids-limit', '64', '--mount', f'type=volume,source={attempt.volume},target=/source,readonly',
               '--mount', f'type=volume,source={snapshot},target=/snapshot',
               '--entrypoint', 'python', IMAGE, '-c', COPY_SNAPSHOT)
        return snapshot
    except (OSError, subprocess.SubprocessError) as error:
        try:
            docker('rm', '-f', helper)
        except (OSError, subprocess.SubprocessError):
            pass
        if created:
            try:
                docker('volume', 'rm', snapshot)
            except (OSError, subprocess.SubprocessError):
                pass
        raise RuntimeError('Could not create the submission snapshot.') from error
    finally:
        if paused:
            try:
                docker('unpause', attempt.container)
            except (OSError, subprocess.SubprocessError):
                attempt.active = False
                if created:
                    try:
                        docker('volume', 'rm', snapshot)
                    except (OSError, subprocess.SubprocessError):
                        pass
                raise RuntimeError('Could not resume the workspace after the snapshot.') from None
