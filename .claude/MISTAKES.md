# MISTAKES

Reusable failure learnings: what broke, root cause, fix, prevention. One entry
per learning, newest last. See `CLAUDE.md` for when to record here.

---

## 2026-06-18 — `make` is unusable on native Windows

**Symptom:** `make check` / `make init` cannot run on this machine.
**Root cause:** the Makefile's `RESOLVE_VENV_BIN` looks for `.venv/bin/python`
(Unix layout) but uv creates `.venv/Scripts/` on Windows; `scripts/dev-check.sh`
only re-delegates to `make` targets, so it inherits the same failure. `make`
itself is also absent from the default Windows toolchain.
**Fix:** run the underlying commands directly with the venv's `Scripts/` dir on
PATH: `ruff check/format`, `python -m mypy`, `pytest` (backend);
`bun run check` / `bun run build` (frontend).
**Prevention:** on Windows, treat `make` targets as documentation of the
canonical commands, not as the entrypoint. Note: the uv workspace puts `.venv`
and `uv.lock` at the **repo root**, not in `backend/`.

## 2026-06-18 — email-validator rejects reserved TLDs in tests

**Symptom:** login tests failed with 422 `validation_error` instead of
reaching the route.
**Root cause:** pydantic's `EmailStr` (email-validator) rejects reserved TLDs
like `.test` ("special-use or reserved name"), so `dev@catalogai.test` never
validated.
**Fix:** test fixtures use a real-looking domain (`dev@catalogai.io`).
**Prevention:** never use `.test`/`.example`/`.invalid`/`.localhost` TLDs in
fixtures that go through `EmailStr` validation.

## 2026-06-18 — pyjwt warns on short HS256 secrets

**Symptom:** `InsecureKeyLengthWarning` spam in pytest output.
**Root cause:** the dev-default `APP_SECRET` was 31 bytes; RFC 7518 wants
≥ 32 bytes for HS256.
**Fix:** lengthened the dev default; prod secrets are generated
(`secrets.token_urlsafe(48)`).
**Prevention:** any default HMAC secret must be ≥ 32 bytes.

## 2026-07-06 — `fastapi dev` crashes on the Windows cp1252 console

**Symptom:** the backend never starts under `fastapi dev app/main.py`;
`UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f680'`
(the 🚀 in the startup banner) from `fastapi_cli` → `rich_toolkit`.
**Root cause:** the FastAPI CLI's rich banner prints emoji to a legacy
Windows console whose default encoding is cp1252, which has no code point
for the rocket glyph. The app code is never reached — it's a console-encoding
crash in the launcher, not an app bug.
**Fix:** run uvicorn directly and force UTF-8:
`PYTHONUTF8=1 python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
**Prevention:** on Windows, start the local backend via uvicorn (not
`fastapi dev`), or set `PYTHONUTF8=1` in the environment. The API mounts at
the root (`/healthcheck`, `/version`, `/auth/*`, `/jobs`, `/items/*`,
`/products`), not under `/api/v1`.

## 2026-07-06 — winget PostgreSQL install left a half-installed server

**Symptom:** after a `winget install PostgreSQL.PostgreSQL.18` that appeared
to run, only the CLI tools existed (`bin/`), while `lib/` and the service were
missing; a manual `initdb` then failed with
`could not access file "dict_snowball"`.
**Root cause:** the install was a background task killed mid-run when the
session ended, so the EDB installer's server component never deployed. `winget
list` didn't even register the package. Letting the original background task
finish (exit 0, "Installé correctement") produced a complete install with the
`postgresql-x64-18` service Running and a cluster on port 5432.
**Fix:** don't interrupt the EDB installer; verify completeness via
`Test-Path 'C:\Program Files\PostgreSQL\18\lib'` + the running service before
running `initdb`/`alembic`.
**Prevention:** run long native installers to completion; a present `bin/`
without `lib/` and without a registered service means the server component
didn't deploy — re-run to completion rather than hand-initdb'ing.

## 2026-07-06 — Tests read the real .env, leaking live creds into assertions

**Symptom:** `test_returns_503_when_xano_not_configured` failed with 200 once
real Xano creds were added to `.env` — the "not configured" path actually made
a live Xano call.
**Root cause:** pydantic-settings loads the repo-root `.env` in tests too, so
`settings.xano_configured` became True and the real dependency ran (and hit the
live API).
**Fix:** the test now `monkeypatch`es `deps.settings.XANO_BASE_URL=""` and
resets the client singleton, forcing the unconfigured branch with no network.
**Prevention:** any test asserting "integration X disabled" must neutralize the
setting explicitly (monkeypatch), not assume the env is empty — the dev `.env`
may carry real credentials. Bonus gotcha: a process-wide client singleton
(`deps._xano_client`) must be reset in such tests to avoid a live client
leaking across tests.

## uvicorn --reload (Windows) silently misses new routes

Symptom: added `GET /items/{id}/product` + `POST /items/{id}/resolve`, all tests
green, but the running server 404'd them and `/openapi.json` didn't list them.
Cause: WatchFiles under Windows didn't reload after the route-file edits (it had
reloaded on an earlier model edit, then went stale). Fix: fully restart the
uvicorn process; don't trust `--reload` to have applied route/router changes.
Prevention: after backend router changes, verify with
`curl /openapi.json | grep <path>` before testing in the UI; restart if missing.
