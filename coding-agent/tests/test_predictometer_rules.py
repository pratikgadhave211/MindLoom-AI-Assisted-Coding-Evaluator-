from coding_agent.predictometer_rules import evaluate_rules


CHALLENGE = {'relevant_files': ['flaskr/blog.py'], 'expected_files': ['flaskr/blog.py'],
             'example_patterns': ['check_author=True']}


def test_rules_find_relevant_activity_and_added_pattern():
    events = [
        {'type': 'tool_finished', 'name': 'read_file', 'path': 'flaskr/blog.py', 'status': 'completed'},
        {'type': 'tool_finished', 'name': 'edit_file', 'path': 'flaskr/blog.py', 'status': 'completed'},
    ]
    result = evaluate_rules(CHALLENGE, events, {'flaskr/blog.py': 'post = get_post(id)\n'},
                            {'flaskr/blog.py': 'post = get_post(id, check_author=True)\n'})
    assert result['score'] == 100
    assert all(result['checks'][name] == 'observed' for name in ('file_inspected', 'file_changed', 'pattern_added'))


def test_pattern_must_be_added_not_already_present():
    events = [{'type': 'file_saved', 'path': 'flaskr/blog.py'}]
    code = 'get_post(id, check_author=True)\n'
    result = evaluate_rules(CHALLENGE, events, {'flaskr/blog.py': code}, {'flaskr/blog.py': code + '# comment\n'})
    assert result['checks']['pattern_added'] == 'not_observed'


def test_missing_files_or_incomplete_events_are_unknown():
    result = evaluate_rules(CHALLENGE, [], {}, {}, incomplete=True)
    assert result['score'] is None
    assert set(result['checks'].values()) >= {'unknown'}


def test_tool_limit_is_a_small_deduction_only_once_and_tests_are_ignored():
    events = [
        {'type': 'file_saved', 'path': 'flaskr/blog.py'},
        {'type': 'tool_limit_reached'}, {'type': 'tool_limit_reached'},
        {'type': 'tool_finished', 'name': 'run_tests', 'status': 'error'},
    ]
    result = evaluate_rules(CHALLENGE, events, {'flaskr/blog.py': 'old'}, {'flaskr/blog.py': 'new'})
    assert result['checks']['tool_limit'] == 'observed'
    assert result['score'] == 25
    assert result == evaluate_rules(CHALLENGE, events[:-1], {'flaskr/blog.py': 'old'}, {'flaskr/blog.py': 'new'})


def test_unsafe_paths_and_large_inputs_are_unknown():
    config = {'relevant_files': ['../secret'], 'expected_files': ['../secret'], 'example_patterns': ['x']}
    result = evaluate_rules(config, [{'type': 'file_saved', 'path': '../secret'}],
                            {'../secret': 'x'}, {'../secret': 'x' * 300000})
    assert result['score'] is None
    assert result['checks']['file_changed'] == 'unknown'


def test_flask_challenge_configuration_with_reference_style_change():
    import json
    from pathlib import Path

    project = Path(__file__).resolve().parents[1]
    challenge = json.loads((project / 'challenges/flaskr-post-authorization/predictometer.json').read_text())
    original = (project.parent / 'broken-repos/broken-flaskr-blog/flaskr/blog.py').read_text()
    changed = original.replace('get_post(id)\n', 'get_post(id, check_author=True)\n')
    events = [{'type': 'tool_finished', 'name': 'read_file', 'path': 'flaskr/blog.py', 'status': 'completed'}]
    result = evaluate_rules(challenge, events, {'flaskr/blog.py': original}, {'flaskr/blog.py': changed})
    assert result['checks']['file_changed'] == 'observed'
    assert result['checks']['pattern_added'] == 'observed'
