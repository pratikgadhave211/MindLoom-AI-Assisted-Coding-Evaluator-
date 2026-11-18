from types import SimpleNamespace
from pathlib import Path
import json
import re

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .memory import get_evidence
from .submission_evidence import collect_changes, make_activity_evidence, make_timeline, summarize_activity
from .submission_judge import configured_judge
from .submission_tests import run_checks, run_visible_checks, solution_result


def contains_reference(value, reference):
    """Do not return verbatim reference code supplied only to the judge."""
    lines = [line[1:].strip() for line in reference.splitlines()
             if line.startswith('+') and not line.startswith('+++') and len(line[1:].strip()) >= 12]
    fragments = {match.group(0).replace(' ', '') for line in lines
                 for match in re.finditer(r'\b[A-Za-z_]\w*\s*=\s*(?:True|False|None)\b', line)}
    def contains(item):
        if isinstance(item, str):
            return any(line in item for line in lines) or any(fragment in item.replace(' ', '') for fragment in fragments)
        if isinstance(item, list):
            return any(contains(child) for child in item)
        if isinstance(item, dict):
            return any(contains(child) for child in item.values())
        return False
    return contains(value)


def has_user_prompt(rows):
    return any(row['event'].get('type') == 'prompt' and isinstance(row['event'].get('message'), str)
               and row['event']['message'].strip() for row in rows)


def sanitize_review(process, reference):
    summary = process.get('summary')
    if not isinstance(summary, dict):
        return process
    summary = dict(summary)
    removed = False
    for group in ('observations', 'improvements', 'unresolved', 'evidence_gaps'):
        items = summary.get(group, [])
        safe = [item for item in items if not contains_reference(item, reference)]
        removed = removed or len(safe) != len(items)
        summary[group] = safe
    if not removed:
        return process
    return dict(process, status='partial', summary=summary,
                reason='Some feedback was withheld because it included reference solution details.')


def evaluate_submission(config, attempt_id, submission_id, snapshot, evidence_revision, chat_revision, evidence_incomplete=False):
    """Evaluate one frozen snapshot; never run the submitted code on the host."""
    database_url = config.checkpoint_database_url
    try:
        with psycopg.connect(database_url, autocommit=True, row_factory=dict_row) as connection:
            connection.execute("UPDATE submissions SET status = 'testing' WHERE id = %s AND attempt_id = %s",
                               (submission_id, attempt_id))
            correctness = run_checks(snapshot, submission_id)
            correctness['visible_tests'] = run_visible_checks(snapshot, submission_id)
            rows = [row for row in get_evidence(SimpleNamespace(conn=connection), attempt_id)['events']
                    if row['id'] <= evidence_revision]
            activity = [row['event'] for row in rows]
            statistics = summarize_activity(activity)
            incomplete = evidence_incomplete or any(event.get('changes_tracked') is False or event.get('result_truncated') is True for event in activity)
            chat_rows = connection.execute('''SELECT e.id, e.event FROM agent_chat_events e
                JOIN agent_chats c ON c.id = e.chat_id
                WHERE c.attempt_id = %s AND e.id <= %s ORDER BY e.id''', (attempt_id, chat_revision)).fetchall()
            timeline = make_timeline(chat_rows) + make_activity_evidence(rows)
            if statistics['prompts'] and not any(row['event'].get('type') == 'prompt' for row in chat_rows):
                incomplete = True
            root = Path(__file__).resolve().parents[2] / 'challenges/flaskr-secure-search'
            template = Path(__file__).resolve().parents[3] / 'broken-repos/flaskr-secure-search'
            try:
                changes = collect_changes(snapshot, template, submission_id)
                timeline.append({'id': 'submission-diff', 'text': changes['diff']})
            except Exception:
                changes = {'files': [], 'incomplete': True}
            timeline.append({'id': 'correctness', 'text': json.dumps(correctness)})
            connection.execute("UPDATE submissions SET status = 'reviewing' WHERE id = %s AND attempt_id = %s",
                               (submission_id, attempt_id))
            problem = (root / 'question.md').read_text(encoding='utf-8')
            rubric = {'criteria': json.loads((root / 'rubric.json').read_text(encoding='utf-8')),
                      'reference_patch': (root / 'reference.patch').read_text(encoding='utf-8')}
            process = (configured_judge(config, problem, rubric, timeline) if has_user_prompt(chat_rows)
                       else {'status': 'unavailable', 'reason': 'No user prompts were recorded for process review.'})
            # Do not expose the private reference or its added lines in feedback.
            process = sanitize_review(process, rubric['reference_patch'])
            summary = process.get('summary', {})
            referenced = {str(ref) for item in summary.get('observations', []) + summary.get('improvements', [])
                          for ref in item.get('evidence_ids', [])}
            evidence = [{'id': item['id'], 'text': ('Submitted code changes; see changed files.'
                        if item['id'] == 'submission-diff' else item['text'])}
                        for item in timeline if item['id'] in referenced]
            report = {'result': solution_result(correctness), 'correctness': correctness, 'statistics': statistics,
                      'process_review': process, 'changed_files': changes['files'],
                      'evidence': evidence, 'evidence_incomplete': incomplete or changes.get('incomplete', True),
                      'activity_order_incomplete': any(event.get('type') in ('file_saved', 'terminal_opened') for event in activity)}
            status = 'completed' if correctness['status'] == 'completed' else 'failed'
            connection.execute('UPDATE submissions SET status = %s, report = %s WHERE id = %s AND attempt_id = %s',
                               (status, Jsonb(report), submission_id, attempt_id))
    except Exception:
        # Preserve a failed state if the database is still reachable.
        try:
            with psycopg.connect(database_url, autocommit=True) as connection:
                connection.execute("UPDATE submissions SET status = 'failed' WHERE id = %s AND attempt_id = %s",
                                   (submission_id, attempt_id))
        except Exception:
            pass
