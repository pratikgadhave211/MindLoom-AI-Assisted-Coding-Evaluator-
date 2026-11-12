# Broken Flaskr Blog author note

Source: https://github.com/pallets/flask, tag `3.1.2`, commit `2c1b30d0503cfb064f1cb252e6614a06915a362a`, `examples/tutorial`. Upstream BSD-3-Clause license is retained in the challenge.

Intentional fault: in `flaskr/blog.py`, `get_post` defaults `check_author` to `False`. Both update and delete call it without an explicit flag, allowing a logged-in user to modify another user's post by URL. The upstream `test_author_required` test detects this. The intended repair is to restore the default authorization check while preserving the optional override for callers that deliberately need it.
