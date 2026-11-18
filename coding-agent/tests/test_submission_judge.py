import pytest


def test_short_evidence_uses_one_judge_call_with_valid_references():
    from coding_agent.submission_judge import review_events
    calls = []
    def judge(problem, rubric, summary, events):
        calls.append(events)
        return {'observations': [{'finding': 'Investigated.', 'evidence_ids': ['1']}], 'unresolved': [], 'evidence_gaps': []}
    result = review_events('problem', 'rubric', [{'id': '1', 'text': 'inspect'}], 200,
                           lambda value: len(str(value)), judge)
    assert len(calls) == 1
    assert result['status'] == 'ready'
    assert result['summary']['observations'][0]['evidence_ids'] == ['1']


def test_long_evidence_is_reviewed_sequentially_and_carries_summary():
    from coding_agent.submission_judge import review_events
    calls = []
    def judge(problem, rubric, summary, events):
        calls.append((summary, events))
        return {'observations': [{'finding': 'Step reviewed', 'evidence_ids': [events[0]['id']]}],
                'unresolved': [], 'evidence_gaps': []}
    events = [{'id': str(i), 'text': 'x' * 45} for i in range(3)]
    result = review_events('p', 'r', events, 300, lambda value: len(str(value)), judge)
    assert result['status'] == 'ready'
    assert len(calls) > 1
    assert calls[1][0]['observations'][0]['evidence_ids'] == ['0']


def test_previous_findings_are_not_silently_lost_between_batches():
    from coding_agent.submission_judge import review_events
    def judge(problem, rubric, summary, events):
        return {'observations': [{'finding': 'Reviewed', 'evidence_ids': [events[0]['id']]}],
                'unresolved': [], 'evidence_gaps': []}
    events = [{'id': str(i), 'text': 'x' * 45} for i in range(3)]
    result = review_events('p', 'r', events, 300, lambda value: len(str(value)), judge)
    assert result['status'] == 'ready'
    ids = {item['evidence_ids'][0] for item in result['summary']['observations']}
    assert '0' in ids


def test_invalid_evidence_reference_is_not_accepted():
    from coding_agent.submission_judge import review_events
    def judge(*args):
        return {'observations': [{'finding': 'Invented', 'evidence_ids': ['unknown']}], 'unresolved': [], 'evidence_gaps': []}
    result = review_events('p', 'r', [{'id': '1'}], 200, lambda value: len(str(value)), judge)
    assert result['status'] == 'unavailable'


def test_malformed_finding_is_rejected_before_report_display():
    from coding_agent.submission_judge import review_events
    def judge(*args):
        return {'observations': [{'finding': {'unexpected': 'object'}, 'evidence_ids': ['1']}],
                'unresolved': [], 'evidence_gaps': []}
    result = review_events('p', 'r', [{'id': '1'}], 300, lambda value: len(str(value)), judge)
    assert result['status'] == 'unavailable'


def test_improvement_requires_known_evidence():
    from coding_agent.submission_judge import review_events
    def judge(*args):
        return {'observations': [], 'unresolved': [], 'evidence_gaps': [],
                'improvements': [{'suggestion': 'Verify the fix', 'evidence_ids': ['missing']}]}
    result = review_events('p', 'r', [{'id': '1'}], 400, lambda value: len(str(value)), judge)
    assert result['status'] == 'unavailable'


def test_unknown_model_output_fields_are_not_returned():
    from coding_agent.submission_judge import review_events
    def judge(*args):
        return {'observations': [], 'unresolved': [], 'evidence_gaps': [], 'unexpected': 'private text'}
    result = review_events('p', 'r', [{'id': '1'}], 400, lambda value: len(str(value)), judge)
    assert result['status'] == 'ready'
    assert 'unexpected' not in result['summary']


def test_invalid_context_budget_never_calls_model():
    from coding_agent.submission_judge import review_events
    result = review_events('problem', 'rubric', [{'id': '1'}], 2, lambda value: len(str(value)), lambda *args: pytest.fail('model called'))
    assert result['status'] == 'unavailable'


def test_later_judge_failure_keeps_prior_findings_as_partial():
    from coding_agent.submission_judge import review_events
    calls = []
    def judge(problem, rubric, summary, events):
        calls.append(events)
        if len(calls) > 1:
            raise TimeoutError('offline')
        return {'observations': [{'finding': 'First batch reviewed.', 'evidence_ids': ['0']}],
                'unresolved': [], 'evidence_gaps': []}
    events = [{'id': str(i), 'text': 'x' * 45} for i in range(4)]
    result = review_events('p', 'r', events, 300, lambda value: len(str(value)), judge)
    assert result['status'] == 'partial'
    assert result['summary']['observations'][0]['evidence_ids'] == ['0']


def test_oversized_event_is_split_with_its_evidence_id():
    from coding_agent.submission_judge import review_events
    received = []
    def judge(problem, rubric, summary, events):
        received.extend(events)
        return {'observations': [{'finding': 'Reviewed', 'evidence_ids': ['large']}],
                'unresolved': [], 'evidence_gaps': []}
    result = review_events('p', 'r', [{'id': 'large', 'text': 'x' * 600}], 300,
                           lambda value: len(str(value)), judge)
    assert result['status'] == 'ready'
    assert len(received) > 1
    assert all(event['id'] == 'large' for event in received)
    assert all(event['partial'] is True for event in received)
    assert ''.join(event['text'] for event in received) == 'x' * 600


def test_judge_receives_problem_rubric_and_returns_validated_feedback():
    import json
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage
    from coding_agent.submission_judge import review_process

    requests = []
    class Model:
        def invoke(self, messages):
            requests.append(json.loads(messages[1].content))
            return AIMessage(content=json.dumps({'observations': [{'finding': 'Investigated', 'evidence_ids': ['1']}],
                                                   'unresolved': [], 'evidence_gaps': []}),
                             usage_metadata={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15})
    class Tokenizer:
        def encode(self, text):
            return SimpleNamespace(ids=list(text))
    result = review_process('problem', 'rubric', [{'id': '1', 'text': 'user prompt'}],
                            Model(), Tokenizer(), 2000)
    assert result['status'] == 'ready'
    assert requests[0]['problem'] == 'problem' and requests[0]['rubric'] == 'rubric'
    assert result['usage']['total'] == 15
