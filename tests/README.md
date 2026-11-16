# Tests

## Suites

| Location | Kind | Runner | Needs |
|---|---|---|---|
| `backend/tests/` | unit + API + integration | `pytest` | nothing (SQLite + fakes) |
| `backend/tests/test_security.py` | isolation and authorization | `pytest` | nothing |
| `backend/tests/test_integration.py` | whole-app HTTP journeys | `pytest -m integration` | nothing |
| `frontend/src/test/` | component + client | `vitest` | nothing (fetch stubbed) |
| `notebook-image/smoke-tests/` | environment smoke | `pytest` in the image | Docker |
| `tests/load/` | measured load test | `python` | a running stack |

## Running

```bash
make test              # backend + frontend
make test-security
make test-integration
make test-env          # builds the image and runs smoke tests inside it
make loadtest          # against a running stack
```

## What is faked, and what is not

Only the infrastructure seam is replaced (`app/integrations/*`:
`FakeNotebookBackend`, `FakeGrader`). Everything else runs for real:

- Pydantic validation and serialization
- authentication, session JWTs, cookie handling
- ownership and role checks
- dataset snippet composition
- notebook metadata and file-name generation
- progress and attempt bookkeeping

This is deliberate: a test that stubs authorization would prove nothing about
isolation.

## Load testing

`tests/load/run_loadtest.py` reports only measured values and exits non-zero
above a 1% error rate. See `docs/LOAD_TEST_PLAN.md` for the staged plan and the
reporting format. No 400-user readiness claim is made without running it.
