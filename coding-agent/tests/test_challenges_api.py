from fastapi.testclient import TestClient


def test_challenge_catalog_requires_token_and_exposes_only_candidate_details():
    from coding_agent.api import create_app
    client = TestClient(create_app(manager=object(), token='test'))
    assert client.get('/challenges').status_code == 401
    response = client.get('/challenges', headers={'Authorization': 'Bearer test'})
    assert response.status_code == 200
    challenges = response.json()['challenges']
    assert len(challenges) == 1
    assert challenges[0]['id'] == 'flaskr-secure-search'
    assert challenges[0]['title']
    assert 'reference' not in repr(challenges).lower()
