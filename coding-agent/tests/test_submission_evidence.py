def test_summarizes_tool_calls_and_missing_token_usage_without_inventing_values():
    from coding_agent.submission_evidence import summarize_activity

    events = [
        {'type': 'prompt_accepted'},
        {'type': 'tool_started', 'name': 'read_file'},
        {'type': 'tool_finished', 'name': 'read_file', 'status': 'completed'},
        {'type': 'tool_started', 'name': 'edit_file'},
        {'type': 'tool_finished', 'name': 'edit_file', 'status': 'error'},
        {'type': 'model_call', 'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}},
        {'type': 'model_call', 'usage': None},
    ]
    result = summarize_activity(events)
    assert result['prompts'] == 1
    assert result['tools'] == {'read_file': 1, 'edit_file': 1}
    assert result['failed_tool_calls'] == 1
    assert result['model_calls'] == 2
    assert result['tokens'] == {'input': 10, 'output': 5, 'total': 15, 'coverage': 'partial'}


def test_unknown_usage_is_unavailable_and_duplicate_finished_events_do_not_increase_calls():
    from coding_agent.submission_evidence import summarize_activity

    result = summarize_activity([{'type': 'model_call', 'usage': None},
                                 {'type': 'tool_finished', 'name': 'read_file', 'status': 'completed'}])
    assert result['tokens']['coverage'] == 'unavailable'
    assert result['tokens']['total'] is None
    assert result['tools'] == {}


def test_timeline_keeps_user_and_tool_evidence_ids_without_unrelated_events():
    from coding_agent.submission_evidence import make_timeline
    rows = [{'id': 3, 'event': {'type': 'prompt', 'message': 'Find the bug'}},
            {'id': 4, 'event': {'type': 'tool_finished', 'name': 'run_tests', 'status': 'error', 'result': 'failed'}},
            {'id': 5, 'event': {'type': 'model_call', 'usage': None}}]
    timeline = make_timeline(rows)
    assert [event['id'] for event in timeline] == ['chat:3', 'chat:4']
    assert 'Find the bug' in timeline[0]['text']
    assert 'failed' in timeline[1]['text']


def test_editor_saves_are_attributed_without_fabricating_chat_order():
    from coding_agent.submission_evidence import make_activity_evidence
    rows = [{'id': 8, 'event': {'type': 'file_saved', 'source': 'user', 'path': 'app.py'}},
            {'id': 9, 'event': {'type': 'prompt_accepted'}}]
    evidence = make_activity_evidence(rows)
    assert len(evidence) == 1 and evidence[0]['id'] == 'activity:8'
    assert 'app.py' in evidence[0]['text'] and 'user' in evidence[0]['text']
    assert 'ordering relative to chat is unknown' in evidence[0]['text']


def test_change_collection_never_runs_code_from_snapshot(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace
    from coding_agent import submission_evidence
    (tmp_path / 'app.py').write_text('old', encoding='utf-8')
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=json.dumps({'files': ['app.py'], 'diff': 'old -> new', 'incomplete': False}))
    monkeypatch.setattr(submission_evidence.subprocess, 'run', run)
    result = submission_evidence.collect_changes('coding-agent-submission-' + 'a' * 32, tmp_path)
    assert result['files'] == ['app.py']
    assert '--network' in calls[0][0] and 'none' in calls[0][0]
    assert ',readonly' in next(arg for arg in calls[0][0] if arg.startswith('type=volume'))


def test_oversized_file_is_not_falsely_reported_deleted(tmp_path):
    import json
    import subprocess
    import sys
    from coding_agent.submission_evidence import DIFF_PROGRAM
    (tmp_path / 'app.py').write_text('x' * (256 * 1024 + 1), encoding='utf-8')
    program = DIFF_PROGRAM.replace("Path('/snapshot')", f'Path({str(tmp_path)!r})')
    result = subprocess.run([sys.executable, '-c', program], input=json.dumps({'app.py': 'original'}),
                            text=True, capture_output=True, check=True)
    output = json.loads(result.stdout)
    assert output['incomplete'] is True
    assert 'app.py' not in output['files']
