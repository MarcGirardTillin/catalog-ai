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
