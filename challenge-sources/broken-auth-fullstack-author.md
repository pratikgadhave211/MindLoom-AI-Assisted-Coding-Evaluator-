# Broken auth full-stack challenge — author record

- Upstream: https://github.com/fastapi/full-stack-fastapi-template
- Pinned source commit: `aabb90126964a164e02aff39e7c385bb0598236d`
- License: MIT; original `LICENSE` remains in the candidate repository.
- Candidate repository: `broken-repos/broken-auth-fullstack`
- Candidate starting commit: `ce44c9040212a90336597922fe7c3c0a88ffe3e7` (separate Git history; no clean solution commit in the candidate repository).
- Seeded fault: removed the ownership authorization check from `read_item` in `backend/app/api/routes/items.py`. Other item operations remain unchanged.
- Visible regression check: `backend/tests/api/routes/test_items.py::test_read_item_not_enough_permissions` expects `403`; the broken implementation returns `200` for another user's item.
- Expected repair: restore an authorization check that permits the owner or a superuser and rejects other users, while preserving `404` for missing items.
- Verification performed: Python 3.14 byte-compilation of the candidate backend and tests, plus a comparison with the pinned clean source. The database-backed pytest suite has not yet been run in this workspace.

Keep this author record and the clean source outside the candidate IDE mount and submission snapshot.
