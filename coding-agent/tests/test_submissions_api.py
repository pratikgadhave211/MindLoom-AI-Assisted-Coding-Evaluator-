from fastapi.testclient import TestClient


def test_question_and_submission_endpoints_are_authenticated_and_attempt_scoped():
    from coding_agent.api import create_app

    class Manager:
        def question(self, attempt_id):
            if attempt_id != 'a':
                raise KeyError(attempt_id)
            return {'title': 'Challenge', 'question': 'Solve it'}
        def submit(self, attempt_id, request_id):
            if attempt_id != 'a':
                raise KeyError(attempt_id)
            return {'submission_id': 'sub', 'status': 'running'}
        def submission(self, attempt_id, submission_id):
            if attempt_id != 'a' or submission_id != 'sub':
                raise KeyError(submission_id)
            return {'submission_id': 'sub', 'status': 'completed', 'report': {'result': 'passed'}}

    client = TestClient(create_app(manager=Manager(), token='token'))
    headers = {'Authorization': 'Bearer token'}
    assert client.get('/attempts/a/question').status_code == 401
    assert client.get('/attempts/a/question', headers=headers).json()['title'] == 'Challenge'
    request_id = 'da78c1bd-4ef8-4bd6-99ec-d5dc493981d2'
    response = client.post('/attempts/a/submissions', headers=headers, json={'request_id': request_id})
    assert response.status_code == 202 and response.json()['submission_id'] == 'sub'
    assert client.get('/attempts/a/submissions/sub', headers=headers).json()['report']['result'] == 'passed'
    assert client.get('/attempts/other/submissions/sub', headers=headers).status_code == 404
    assert client.post('/attempts/a/submissions', headers=headers, json={'request_id': 'invalid'}).status_code == 400
