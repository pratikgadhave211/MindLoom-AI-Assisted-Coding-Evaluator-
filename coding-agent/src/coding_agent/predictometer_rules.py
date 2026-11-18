from difflib import ndiff
from pathlib import PurePosixPath


MAX_FILE_SIZE = 256 * 1024


def safe_paths(paths):
    # Challenge paths must stay inside the workspace; never interpret them as regex.
    safe = []
    for path in paths:
        if not isinstance(path, str) or not path or '\\' in path or ':' in path:
            continue
        parts = PurePosixPath(path)
        if parts.is_absolute() or '..' in parts.parts:
            continue
        safe.append(path)
    return safe


def evaluate_rules(challenge, events, original_files, current_files, incomplete=False):
    """Return observable rule signals; never read the filesystem or run tests."""
    relevant = safe_paths(challenge.get('relevant_files', []))
    expected = safe_paths(challenge.get('expected_files', []))
    patterns = [item for item in challenge.get('example_patterns', [])
                if isinstance(item, str) and item and len(item) <= 256]

    # A missing event can mean it was not recorded, especially for terminal edits.
    inspected = any(event.get('type') == 'tool_finished' and event.get('name') == 'read_file'
                    and event.get('status') == 'completed' and event.get('path') in relevant
                    for event in events)
    inspected_status = 'observed' if inspected else ('unknown' if incomplete or not relevant else 'not_observed')

    comparable = []
    for path in expected:
        before, after = original_files.get(path), current_files.get(path)
        if (isinstance(before, str) and isinstance(after, str)
                and len(before.encode('utf-8')) <= MAX_FILE_SIZE
                and len(after.encode('utf-8')) <= MAX_FILE_SIZE):
            comparable.append((before, after))
    changed = any(before != after for before, after in comparable)
    all_readable = bool(expected) and len(comparable) == len(expected)
    changed_status = 'observed' if changed else ('not_observed' if all_readable else 'unknown')

    added = '\n'.join(line[2:] for before, after in comparable
                      for line in ndiff(before.splitlines(), after.splitlines()) if line.startswith('+ '))
    matched = any(pattern in added for pattern in patterns)
    pattern_status = 'observed' if matched else ('not_observed' if all_readable and patterns else 'unknown')
    limit_hit = any(event.get('type') == 'tool_limit_reached' for event in events)
    limit_status = 'observed' if limit_hit else ('unknown' if incomplete else 'not_observed')

    checks = {'file_inspected': inspected_status, 'file_changed': changed_status,
              'pattern_added': pattern_status, 'tool_limit': limit_status}
    weights = {'file_inspected': 25, 'file_changed': 35, 'pattern_added': 40}
    available = sum(weight for name, weight in weights.items() if checks[name] != 'unknown')
    observed = sum(weight for name, weight in weights.items() if checks[name] == 'observed')
    # No activity is not evidence that the user will fail.
    score = round(100 * observed / available) if available and observed else None
    if score is not None and limit_hit:
        score = max(0, score - 10)
    return {'score': score, 'checks': checks}
