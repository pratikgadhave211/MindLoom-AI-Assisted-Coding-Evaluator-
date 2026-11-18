from types import SimpleNamespace

import pytest


def test_submit_requires_new_challenge_and_idle_workspace(monkeypatch):
    from coding_agent import attempts
    manager = attempts.AttemptManager()
    attempt = {'challenge_id': 'flaskr-secure-search', 'workspace': SimpleNamespace(active=True),
               'busy': True}
    manager.attempts['a'] = attempt
    connection = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: None))
    monkeypatch.setattr(manager, '_chat_memory', lambda attempt: SimpleNamespace(conn=connection))
    monkeypatch.setattr(attempts, 'create_snapshot', lambda workspace: pytest.fail('must not snapshot'))
    with pytest.raises(ValueError, match='Wait'):
        manager.submit('a', 'request')


def test_question_for_new_challenge_is_candidate_facing():
    from coding_agent.attempts import AttemptManager
    manager = AttemptManager()
    manager.attempts['a'] = {'challenge_id': 'flaskr-secure-search'}
    result = manager.question('a')
    assert 'pagination' in result['question'].lower() or 'page' in result['question'].lower()
    assert 'reference.patch' not in result['question']


def test_private_reference_lines_are_not_exposed_in_judge_feedback():
    from coding_agent.submissions import contains_reference
    reference = '+    post = get_post(id, check_author=True)\n'
    feedback = {'observations': [{'finding': 'Use post = get_post(id, check_author=True) in both routes.'}]}
    assert contains_reference(feedback, reference)
    assert contains_reference({'improvements': [{'suggestion': 'Pass check_author=True in both routes.'}]}, reference)
    assert not contains_reference({'observations': [{'finding': 'Check ownership on both routes.'}]}, reference)


def test_unsafe_reference_finding_is_removed_without_losing_safe_feedback():
    from coding_agent.submissions import sanitize_review
    reference = '+    post = get_post(id, check_author=True)\n'
    process = {'status': 'ready', 'usage': {'total': 100}, 'summary': {'observations': [
        {'finding': 'The user investigated access control.', 'evidence_ids': ['one']},
        {'finding': 'Set check_author=True.', 'evidence_ids': ['two']}],
        'improvements': [], 'unresolved': [], 'evidence_gaps': []}}
    result = sanitize_review(process, reference)
    assert result['status'] == 'partial'
    assert len(result['summary']['observations']) == 1
    assert result['usage']['total'] == 100


def test_process_review_requires_an_observed_user_prompt():
    from coding_agent.submissions import has_user_prompt
    assert not has_user_prompt([{'event': {'type': 'tool_finished'}}])
    assert has_user_prompt([{'event': {'type': 'prompt', 'message': 'Inspect authorization'}}])
