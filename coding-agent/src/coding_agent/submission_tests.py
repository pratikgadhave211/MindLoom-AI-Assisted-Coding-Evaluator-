import json
import re
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

from .container_workspace import IMAGE, docker


BEHAVIORS = {
    'Other users cannot update or delete a post',
    'Authors can update their own posts',
    'Authors can delete their own posts',
    'Logged-out users cannot manage posts',
    'Search and pagination return matching posts',
    'Results use stable newest-first ordering',
    'Navigation preserves the search query',
    'Search includes bodies and treats special characters literally',
    'Search matches Unicode case-insensitively',
    'Invalid and out-of-range pages return 404',
    'Empty search results are a valid first page',
}
CHECKS = Path(__file__).resolve().parents[2] / 'challenges/flaskr-secure-search/hidden_http.py'


def solution_result(correctness):
    if correctness.get('status') != 'completed':
        return 'could_not_evaluate'
    passed, total = correctness['passed'], correctness['total']
    if passed == 0:
        return 'not_passed'
    if passed < total or correctness.get('visible_tests', {}).get('status') == 'failed':
        return 'partially_passed'
    if correctness.get('visible_tests', {}).get('status') != 'passed':
        return 'could_not_evaluate'
    return 'passed'


def run_visible_checks(snapshot, submission_id=None):
    """Run candidate-controlled visible tests as additional, untrusted evidence."""
    if not re.fullmatch(r'coding-agent-submission-[0-9a-f]{32}', snapshot):
        return {'status': 'could_not_evaluate'}
    name = 'coding-agent-visible-' + (UUID(submission_id).hex if submission_id else uuid4().hex)
    try:
        result = subprocess.run(['docker', 'run', '--name', name, '--network', 'none', '--read-only',
                                 '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                                 '--memory', '512m', '--cpus', '1', '--pids-limit', '128',
                                 '--tmpfs', '/tmp:rw,nosuid,nodev,uid=1000,gid=1000,size=128m',
                                 '--mount', f'type=volume,source={snapshot},target=/source,readonly',
                                 '--workdir', '/tmp', '--entrypoint', 'sh', IMAGE, '-c',
                                 'mkdir /tmp/project && cp -a /source/. /tmp/project/ && cd /tmp/project && python -m pytest -q'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        status = 'passed' if result.returncode == 0 else 'failed' if result.returncode == 1 else 'could_not_evaluate'
        return {'status': status}
    except (OSError, subprocess.SubprocessError):
        return {'status': 'could_not_evaluate'}
    finally:
        try:
            docker('rm', '-f', name)
        except (OSError, subprocess.SubprocessError):
            pass


def run_checks(snapshot, submission_id=None):
    """Run candidate and trusted HTTP checks in separate short-lived containers."""
    if not re.fullmatch(r'coding-agent-submission-[0-9a-f]{32}', snapshot):
        return {'status': 'could_not_evaluate', 'reason': 'Invalid submission snapshot.'}
    suffix = UUID(submission_id).hex if submission_id else uuid4().hex
    network = 'coding-agent-eval-' + suffix
    container = 'coding-agent-candidate-' + suffix
    checker = 'coding-agent-checker-' + suffix
    created_network = False
    try:
        docker('network', 'create', '--internal', network)
        created_network = True
        docker('run', '-d', '--name', container, '--network', network, '--network-alias', 'candidate',
               '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--memory', '512m', '--cpus', '1', '--pids-limit', '128',
               '--tmpfs', '/tmp:rw,nosuid,nodev,uid=1000,gid=1000,size=128m',
               '--mount', f'type=volume,source={snapshot},target=/source,readonly',
               '--workdir', '/tmp', '--entrypoint', 'sh', IMAGE, '-c',
               'mkdir /tmp/project && cp -a /source/. /tmp/project/ && cd /tmp/project && '
               'python -m flask --app flaskr init-db && python -m flask --app flaskr run --host 0.0.0.0 --port 5000')
        result = subprocess.run(['docker', 'run', '--rm', '-i', '--name', checker, '--network', network, '--read-only',
                                 '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                                 '--memory', '256m', '--pids-limit', '64', '--entrypoint', 'python', IMAGE, '-'],
                                input=CHECKS.read_text(encoding='utf-8'), capture_output=True, text=True, encoding='utf-8',
                                timeout=45, check=True)
        data = json.loads(result.stdout)
        if data.get('status') != 'completed':
            return {'status': 'could_not_evaluate', 'reason': 'The challenge checks could not complete.'}
        behaviors = data.get('behaviors')
        if (not isinstance(behaviors, list) or len(behaviors) != len(BEHAVIORS) or
                {item.get('name') for item in behaviors if isinstance(item, dict)} != BEHAVIORS or
                any(not isinstance(item, dict) or item.get('status') not in ('passed', 'failed') for item in behaviors)):
            raise ValueError('Invalid test result')
        passed = sum(item['status'] == 'passed' for item in behaviors)
        return {'status': 'completed', 'behaviors': behaviors, 'passed': passed, 'total': len(behaviors)}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError):
        return {'status': 'could_not_evaluate', 'reason': 'The challenge checks could not complete.'}
    finally:
        try:
            docker('rm', '-f', checker)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            docker('rm', '-f', container)
        except (OSError, subprocess.SubprocessError):
            pass
        if created_network:
            try:
                docker('network', 'rm', network)
            except (OSError, subprocess.SubprocessError):
                pass


def cleanup_submission(submission_id):
    """Remove only containers and the private network owned by an interrupted submission."""
    suffix = UUID(submission_id).hex
    for prefix in ('coding-agent-snapshot-', 'coding-agent-checker-', 'coding-agent-candidate-', 'coding-agent-visible-', 'coding-agent-diff-'):
        try:
            docker('rm', '-f', prefix + suffix)
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        docker('network', 'rm', 'coding-agent-eval-' + suffix)
    except (OSError, subprocess.SubprocessError):
        pass
