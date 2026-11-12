# Broken Flaskr Blog

This is a small blog with registration, login, posts, and a SQLite database. It comes from the official Flask tutorial. Its Python dependencies are already installed in the IDE environment.

## Task

A logged-in user can change or delete another user's post by requesting its URL directly. Fix the authorization behavior without breaking a user's ability to manage their own posts.

## Run

```sh
flask --app flaskr init-db
flask --app flaskr run --host 0.0.0.0 --port 5000
```

Open the forwarded port 5000 in the IDE. To check your repair:

```sh
python -m pytest -q
```

The app source and tests are in `flaskr/` and `tests/`. See `README.rst` for the upstream tutorial instructions.
