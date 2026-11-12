# Challenge: Item access control

This full-stack application uses a FastAPI backend, React frontend, and PostgreSQL. An access-control regression has been introduced in the backend.

## Expected behavior

- A signed-in user can read items they own.
- A regular user cannot read another user's item by its ID.
- A superuser can read any item.
- Missing items still return `404`.

Find and fix the regression without changing the public API contract or weakening other item operations. Review the existing tests and add focused coverage if needed.

## Visible check

With the project's backend dependencies and test database configured, run:

```sh
cd backend
pytest tests/api/routes/test_items.py -q
```

The upstream repository's setup instructions are in `README.md` and `development.md`. This challenge is a deliberately broken copy of the [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template), used under its MIT license.
