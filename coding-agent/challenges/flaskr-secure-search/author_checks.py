"""Local author checks; the submission evaluator must not mount these in a candidate workspace."""
from flaskr.db import get_db


def add(app, title, body='sample'):
    with app.app_context():
        db = get_db()
        db.execute('INSERT INTO post (title, body, author_id) VALUES (?, ?, 1)', (title, body))
        db.commit()


def test_search_matches_body_as_well_as_title(app, client):
    add(app, 'Hidden in body', 'Special NeEdLe')
    response = client.get('/', query_string={'q': '  needle  '})
    assert b'Hidden in body' in response.data
    assert b'test title' not in response.data


def test_search_casefolds_unicode(app, client):
    add(app, 'CAFÉ notes')
    response = client.get('/', query_string={'q': 'café'})
    assert 'CAFÉ notes'.encode() in response.data


def test_search_treats_sql_wildcards_and_quotes_as_literal(app, client):
    add(app, 'Percent % here')
    add(app, 'Under_score')
    add(app, "Quote ' here")
    add(app, 'Ordinary')
    for query, expected in [('%', b'Percent % here'), ('_', b'Under_score'), ("'", b'Quote &#39; here')]:
        response = client.get('/', query_string={'q': query})
        assert expected in response.data
        assert b'Ordinary' not in response.data


def test_order_pagination_and_search_links(app, client):
    for index in range(7):
        add(app, f'Unique match {index}')
    first = client.get('/', query_string={'q': 'Unique match', 'page': 1})
    second = client.get('/', query_string={'q': 'Unique match', 'page': 2})
    assert b'Unique match 6' in first.data
    assert b'Unique match 1' not in first.data
    assert b'Unique match 1' in second.data
    assert b'q=Unique+match' in first.data
    assert b'page=2' in first.data
    assert client.get('/', query_string={'q': 'does-not-exist', 'page': 1}).status_code == 200
    assert client.get('/', query_string={'q': 'does-not-exist', 'page': 2}).status_code == 404
