import math

from coding_agent.predictometer import combine_signals


def test_combines_ready_signals_with_experimental_weights():
    signals = {'direction': {'status': 'ready', 'score': 80, 'revision': 4},
               'comparison': {'status': 'ready', 'score': 70, 'revision': 4},
               'rules': {'status': 'ready', 'score': 78, 'revision': 4}}
    result = combine_signals(signals, revision=4)
    assert result['score'] == 76
    assert result['status'] == 'ready'
    assert result['evidence_quality'] == 'complete'


def test_missing_and_stale_signals_are_never_counted_as_zero():
    signals = {'direction': {'status': 'ready', 'score': 80, 'revision': 3},
               'comparison': {'status': 'unavailable', 'score': None, 'revision': 4},
               'rules': {'status': 'ready', 'score': 78, 'revision': 4}}
    assert combine_signals(signals, revision=4)['status'] == 'insufficient_evidence'
    signals['direction']['revision'] = 4
    result = combine_signals(signals, revision=4)
    assert result['score'] == 79
    assert result['evidence_quality'] == 'partial'


def test_invalid_and_nonfinite_scores_are_unavailable():
    signals = {'direction': {'status': 'ready', 'score': True, 'revision': 1},
               'comparison': {'status': 'ready', 'score': math.nan, 'revision': 1},
               'rules': {'status': 'ready', 'score': 80, 'revision': 1}}
    assert combine_signals(signals, revision=1)['status'] == 'insufficient_evidence'


def test_attempt_predictometer_combines_saved_evidence_without_exposing_reference(monkeypatch):
    from coding_agent import attempts

    manager = attempts.AttemptManager()
    manager.attempts['one'] = {'workspace': object(), 'busy': False}
    rows = [
        {'id': 1, 'event': {'type': 'prompt_accepted', 'turn_id': 'turn'}},
        {'id': 2, 'event': {'type': 'tool_finished', 'name': 'read_file', 'path': 'app.py', 'status': 'completed'}},
        {'id': 3, 'event': {'type': 'direction_result', 'turn_id': 'turn', 'status': 'ready', 'score': 80,
                            'code_status': 'ready', 'code_score': 70, 'workspace_revision': 0}},
    ]
    monkeypatch.setattr(manager, '_chat_memory', lambda attempt: object())
    monkeypatch.setattr(attempts, 'get_evidence', lambda *args: {'events': rows, 'revision': 3, 'prompt_count': 1})
    monkeypatch.setattr(attempts, 'load_challenge', lambda: {'expected_files': ['app.py'], 'relevant_files': ['app.py'],
        'example_patterns': ['correct'], 'prompt_limit': 10})
    monkeypatch.setattr(attempts, 'load_code_context', lambda *args: {'original': {'app.py': 'broken'},
        'current': {'app.py': 'correct'}, 'reference_patch': 'private reference'})
    result = manager.predictometer('one')
    assert result['status'] == 'ready' and result['prompt_count'] == 1
    assert result['components']['comparison']['score'] == 70
    assert 'private reference' not in repr(result)


def test_predictometer_waits_for_assessment_and_explains_activity_gap(monkeypatch):
    from coding_agent import attempts

    manager = attempts.AttemptManager()
    manager.attempts['one'] = {'workspace': object(), 'busy': False, 'assessment_running': True}
    rows = [{'id': 1, 'event': {'type': 'prompt_accepted', 'turn_id': 'turn'}},
            {'id': 2, 'event': {'type': 'tool_started', 'name': 'run_command', 'changes_tracked': False}},
            {'id': 3, 'event': {'type': 'direction_result', 'turn_id': 'turn', 'status': 'ready', 'score': 80,
                                'code_status': 'ready', 'code_score': 70, 'workspace_revision': 2}}]
    monkeypatch.setattr(manager, '_chat_memory', lambda attempt: object())
    monkeypatch.setattr(attempts, 'get_evidence', lambda *args: {'events': rows, 'revision': 3, 'prompt_count': 1})
    monkeypatch.setattr(attempts, 'load_challenge', lambda: {'prompt_limit': 10})
    result = manager.predictometer('one')
    assert result['status'] == 'assessing' and result['score'] is None
    assert result['coverage_reasons'] == ['command_activity']


def test_predictometer_never_scores_using_an_outdated_code_assessment(monkeypatch):
    from coding_agent import attempts

    manager = attempts.AttemptManager()
    manager.attempts['one'] = {'workspace': object(), 'busy': False}
    rows = [{'id': 1, 'event': {'type': 'prompt_accepted', 'turn_id': 'turn'}},
            {'id': 2, 'event': {'type': 'direction_result', 'turn_id': 'turn', 'status': 'ready', 'score': 80,
                                'code_status': 'ready', 'code_score': 70, 'workspace_revision': 0}},
            {'id': 3, 'event': {'type': 'file_saved'}}]
    monkeypatch.setattr(manager, '_chat_memory', lambda attempt: object())
    monkeypatch.setattr(attempts, 'get_evidence', lambda *args: {'events': rows, 'revision': 3, 'prompt_count': 1})
    monkeypatch.setattr(attempts, 'load_challenge', lambda: {'expected_files': ['app.py'], 'relevant_files': [],
        'example_patterns': ['correct'], 'prompt_limit': 10})
    monkeypatch.setattr(attempts, 'load_code_context', lambda *args: {'original': {'app.py': 'broken'},
        'current': {'app.py': 'correct'}})
    result = manager.predictometer('one')
    assert result['components']['comparison']['status'] == 'stale'
    assert result['score'] is None
