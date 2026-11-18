import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from .diagnostics import log_event
from .jev import check_assessment
from .memory import get_evidence, record_evidence
from .container_workspace import run_workspace_tool
from .predictometer_rules import safe_paths


CHALLENGE_ROOT = Path(__file__).resolve().parents[2] / 'challenges/flaskr-post-authorization'
ORIGINAL_ROOT = Path(__file__).resolve().parents[3] / 'broken-repos/broken-flaskr-blog'
MAX_CONTEXT_BYTES = 65536


def load_challenge(challenge_id='flaskr-post-authorization'):
    if challenge_id not in ('flaskr-post-authorization', 'flaskr-secure-search'):
        raise ValueError('Unknown challenge.')
    root = CHALLENGE_ROOT if challenge_id == 'flaskr-post-authorization' else CHALLENGE_ROOT.parent / challenge_id
    path = root / 'predictometer.json'
    return json.loads(path.read_text(encoding='utf-8'))


def load_code_context(challenge, workspace):
    paths = challenge.get('expected_files', [])
    if not paths or len(paths) > 5 or safe_paths(paths) != paths:
        return None
    patch_name = challenge.get('reference_patch')
    if safe_paths([patch_name]) != [patch_name]:
        return None
    challenge_id = challenge.get('challenge_id', 'flaskr-post-authorization')
    if challenge_id not in ('flaskr-post-authorization', 'flaskr-secure-search'):
        return None
    challenge_root = CHALLENGE_ROOT if challenge_id == 'flaskr-post-authorization' else CHALLENGE_ROOT.parent / challenge_id
    original_root = ORIGINAL_ROOT if challenge_id == 'flaskr-post-authorization' else ORIGINAL_ROOT.parent / 'flaskr-secure-search'
    patch_path = (challenge_root / patch_name).resolve()
    if not patch_path.is_relative_to(challenge_root.resolve()):
        return None
    try:
        patch = patch_path.read_text(encoding='utf-8')
        original, current = {}, {}
        for path in paths:
            source = (original_root / path).resolve()
            if not source.is_relative_to(original_root.resolve()):
                return None
            original[path] = source.read_text(encoding='utf-8')
            response = run_workspace_tool(workspace, 'read_editor_file', {'path': path})
            if response.get('status') != 'completed' or not isinstance(response.get('result'), dict):
                return None
            current[path] = response['result']['content']
        context = {'original': original, 'reference_patch': patch, 'current': current}
        if len(json.dumps(context, ensure_ascii=False).encode('utf-8')) > MAX_CONTEXT_BYTES:
            return None
        return context
    except (OSError, KeyError, TypeError, UnicodeError):
        return None


def workspace_revision(rows):
    revision = 0
    for row in rows:
        event = row['event']
        if (event.get('type') in ('file_saved', 'terminal_opened') or
                (event.get('type') == 'tool_started' and event.get('name') == 'edit_file') or
                (event.get('type') == 'tool_finished' and event.get('name') == 'edit_file' and event.get('status') == 'completed') or
                (event.get('type') == 'tool_started' and event.get('name') == 'run_command')):
            revision = row.get('id', 0)
    return revision


def latest_direction(rows):
    # Results are append-only: a slower earlier request cannot replace a newer prompt.
    prompts = [row['event'] for row in rows if row['event'].get('type') == 'prompt_accepted']
    if not prompts:
        return {'status': 'unavailable', 'score': None}
    latest = prompts[-1]['turn_id']
    for row in reversed(rows):
        event = row['event']
        if event.get('type') == 'direction_result' and event.get('turn_id') == latest:
            return {'status': event['status'], 'score': event['score']}
    return {'status': 'pending', 'score': None}


def latest_code(rows):
    prompts = [row['event'] for row in rows if row['event'].get('type') == 'prompt_accepted']
    if not prompts:
        return {'status': 'unavailable', 'score': None}
    stale = False
    for row in reversed(rows):
        event = row['event']
        if event.get('type') == 'direction_result' and event.get('turn_id') == prompts[-1]['turn_id']:
            if event.get('code_status') == 'ready' and event.get('workspace_revision') != workspace_revision(rows):
                stale = True
                continue
            return {'status': event.get('code_status', 'unavailable'), 'score': event.get('code_score')}
    return {'status': 'stale' if stale else 'pending', 'score': None}


def run_latest_direction_check(database_url, attempt_id, api_key, workspace, challenge_id='flaskr-post-authorization'):
    # Reassess a saved edit using the latest saved prompt, without blocking the editor.
    try:
        with psycopg.connect(database_url, autocommit=True, row_factory=dict_row) as connection:
            row = connection.execute("""SELECT e.turn_id, e.event->>'message' AS prompt
                FROM agent_chat_events e JOIN agent_chats c ON c.id = e.chat_id
                WHERE c.attempt_id = %s AND e.event->>'type' = 'prompt'
                ORDER BY e.id DESC LIMIT 1""", (attempt_id,)).fetchone()
        if row:
            run_direction_check(database_url, attempt_id, row['turn_id'], row['prompt'], api_key, workspace, challenge_id)
    except Exception as error:
        log_event('predictometer refresh error', {'type': type(error).__name__})


def run_direction_check(database_url, attempt_id, turn_id, prompt, api_key, workspace=None, challenge_id='flaskr-post-authorization'):
    """Evaluate one accepted prompt without holding the agent's database connection."""
    try:
        with psycopg.connect(database_url, autocommit=True, row_factory=dict_row) as connection:
            memory = SimpleNamespace(conn=connection)
            events = get_evidence(memory, attempt_id)['events']
            prompts = [row['event']['turn_id'] for row in events if row['event'].get('type') == 'prompt_accepted']
            if turn_id not in prompts:
                return
            number = prompts.index(turn_id) + 1
            result = {'type': 'direction_result', 'source': 'platform', 'turn_id': turn_id,
                      'prompt_number': number, 'status': 'unavailable', 'score': None,
                      'code_status': 'unavailable', 'code_score': None, 'workspace_revision': None}
            try:
                challenge = load_challenge() if challenge_id == 'flaskr-post-authorization' else load_challenge(challenge_id)
                before = workspace_revision(events)
                code_context = None
                if workspace is not None:
                    try:
                        code_context = load_code_context(challenge, workspace)
                    except Exception as error:
                        log_event('predictometer code snapshot error', {'type': type(error).__name__})
                after = workspace_revision(get_evidence(memory, attempt_id)['events']) if workspace is not None else before
                if before != after:
                    code_context = None
                answers = check_assessment(challenge['problem'], challenge['author_approach'], prompt,
                                           number, challenge['prompt_limit'], api_key, code_context)
                result['score'] = answers['direction']
                result['status'] = 'ready' if answers['direction'] is not None else 'unavailable'
                result['code_score'] = answers['code']
                result['code_status'] = 'ready' if answers['code'] is not None and code_context is not None else 'unavailable'
                result['workspace_revision'] = after if code_context is not None else None
            except Exception as error:
                # Do not include prompts, private guidance, keys, or provider response bodies.
                log_event('predictometer direction error', {'type': type(error).__name__})
            record_evidence(memory, attempt_id, f'direction:{turn_id}:{uuid4()}', result)
    except Exception as error:
        log_event('predictometer direction storage error', {'type': type(error).__name__})
