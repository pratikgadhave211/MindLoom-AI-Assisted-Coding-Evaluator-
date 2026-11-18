from flaskr.db import get_db


def add_posts(app, titles):
    with app.app_context():
        db = get_db()
        for title in titles:
            db.execute("INSERT INTO post (title, body, author_id) VALUES (?, ?, 1)", (title, 'sample body'))
        db.commit()


def test_other_users_cannot_change_posts(app, client, auth):
    with app.app_context():
        db = get_db()
        db.execute('UPDATE post SET author_id = 2 WHERE id = 1')
        db.commit()
    auth.login()
    assert client.post('/1/update', data={'title': 'changed', 'body': ''}).status_code == 403
    assert client.post('/1/delete').status_code == 403


def test_search_ignores_case_and_surrounding_spaces(app, client):
    add_posts(app, ['Alpha Needle', 'Unrelated item'])
    response = client.get('/', query_string={'q': '  NeEdLe  '})
    assert response.status_code == 200
    assert b'Alpha Needle' in response.data
    assert b'Unrelated item' not in response.data


def test_results_are_paginated(app, client):
    add_posts(app, [f'Sample number {i}' for i in range(7)])
    first = client.get('/?page=1')
    second = client.get('/?page=2')
    assert first.status_code == second.status_code == 200
    assert first.data.count(b'<article class="post">') == 5
    assert second.data.count(b'<article class="post">') == 3


def test_invalid_pages_return_404(client):
    for page in ('0', '-1', 'invalid', '99'):
        assert client.get('/', query_string={'page': page}).status_code == 404
