import json
import re
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

from .container_workspace import IMAGE, docker


DIFF_PROGRAM = '''
import difflib, json, os
from pathlib import Path
original = json.load(__import__('sys').stdin)
root = Path('/snapshot')
current = {}
unknown = set()
incomplete = False
for folder, directories, files in os.walk(root, followlinks=False):
    directories[:] = [item for item in directories if item not in {'.git', '.venv', '.agent-deps', 'node_modules', '__pycache__', '.pytest_cache', 'instance'}]
    for name in files:
        path = Path(folder) / name
        relative = path.relative_to(root).as_posix()
        if name == '.env' or name.startswith('.env.') or path.is_symlink():
            incomplete = True
            unknown.add(relative)
            continue
        try:
            if path.stat().st_size > 256 * 1024:
                incomplete = True
                unknown.add(relative)
                continue
            current[relative] = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            incomplete = True
            unknown.add(relative)
changes = []
files = []
for name in sorted(set(original) | set(current)):
    if name in unknown:
        continue
    before, after = original.get(name, ''), current.get(name, '')
    if before != after:
        files.append(name)
        changes.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='a/' + name, tofile='b/' + name))
diff = ''.join(changes)
if len(diff.encode('utf-8')) > 200000:
    diff = diff.encode('utf-8')[:200000].decode('utf-8', errors='ignore')
    incomplete = True
print(json.dumps({'files': files[:500], 'diff': diff, 'incomplete': incomplete or len(files) > 500}))
'''


def collect_changes(snapshot, template, submission_id=None):
    """Compare a read-only snapshot with a bounded text-only challenge template."""
    if not re.fullmatch(r'coding-agent-submission-[0-9a-f]{32}', snapshot):
        raise ValueError('Invalid submission snapshot.')
    template = Path(template)
    original = {}
    skip = {'.git', '.venv', '.agent-deps', 'node_modules', '__pycache__', '.pytest_cache', 'instance'}
    for path in template.rglob('*'):
        if not path.is_file() or path.is_symlink() or any(part in skip for part in path.relative_to(template).parts):
            continue
        if path.name == '.env' or path.name.startswith('.env.') or path.stat().st_size > 256 * 1024:
            continue
        try:
            original[path.relative_to(template).as_posix()] = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            continue
    name = 'coding-agent-diff-' + (UUID(submission_id).hex if submission_id else uuid4().hex)
    try:
        result = subprocess.run(['docker', 'run', '--rm', '-i', '--name', name, '--network', 'none', '--read-only',
                                 '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '256m',
                                 '--pids-limit', '64', '--mount', f'type=volume,source={snapshot},target=/snapshot,readonly',
                                 '--entrypoint', 'python', IMAGE, '-c', DIFF_PROGRAM],
                                input=json.dumps(original, ensure_ascii=False), text=True, encoding='utf-8', capture_output=True,
                                timeout=60, check=True)
    finally:
        try:
            docker('rm', '-f', name)
        except (OSError, subprocess.SubprocessError):
            pass
    result = json.loads(result.stdout)
    if not isinstance(result, dict) or not isinstance(result.get('files'), list) or not isinstance(result.get('diff'), str):
        raise ValueError('Invalid change summary.')
    return result


def make_timeline(rows):
    """Prepare recorded chat events with stable evidence IDs."""
    allowed = {'prompt', 'progress_update', 'answer', 'tool_started', 'tool_finished', 'error', 'turn_finished'}
    timeline = []
    for row in rows:
        event = row['event']
        if event.get('type') in allowed:
            details = {key: event[key] for key in ('type', 'message', 'name', 'status', 'path', 'result', 'result_truncated') if key in event}
            timeline.append({'id': f"chat:{row['id']}", 'text': json.dumps(details, ensure_ascii=False)})
    return timeline


def make_activity_evidence(rows):
    """Include editor/terminal events without guessing their order among chat events."""
    result = []
    for row in rows:
        event = row['event']
        if event.get('type') in ('file_saved', 'terminal_opened'):
            details = {key: event[key] for key in ('type', 'source', 'path') if key in event}
            details['note'] = 'ordering relative to chat is unknown'
            result.append({'id': f"activity:{row['id']}", 'text': json.dumps(details, ensure_ascii=False)})
    return result


def summarize_activity(events):
    """Count recorded activity without guessing missing provider usage."""
    tools = {}
    failed = 0
    calls = []
    prompts = 0
    for event in events:
        kind = event.get('type')
        if kind == 'prompt_accepted':
            prompts += 1
        elif kind == 'tool_started':
            name = event.get('name') or 'unknown'
            tools[name] = tools.get(name, 0) + 1
        elif kind == 'tool_finished' and event.get('status') == 'error':
            failed += 1
        elif kind == 'model_call':
            calls.append(event.get('usage'))
    valid = [usage for usage in calls if isinstance(usage, dict) and all(
        type(usage.get(key)) is int and usage[key] >= 0 for key in ('input_tokens', 'output_tokens', 'total_tokens'))]
    coverage = 'complete' if calls and len(valid) == len(calls) else 'partial' if valid else 'unavailable'
    tokens = {name: sum(usage[key] for usage in valid) if valid else None
              for name, key in [('input', 'input_tokens'), ('output', 'output_tokens'), ('total', 'total_tokens')]}
    tokens['coverage'] = coverage
    return {'prompts': prompts, 'model_calls': len(calls), 'tools': tools,
            'failed_tool_calls': failed, 'tokens': tokens}
