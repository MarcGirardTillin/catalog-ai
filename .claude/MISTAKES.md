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

## 2026-07-09 — Mocked transports can't catch live-API schema limits (structured outputs)

The import extractor's JSON schema used `anyOf`-nullable on every field (31
union-typed parameters). All 21 unit tests passed against httpx.MockTransport —
then the FIRST live call failed with a 400: the structured-outputs API caps
union-typed parameters at 16 per schema ("exponential compilation cost").
Root cause: a mock validates our parsing of the response, never the API's
validation of our request. Fix: union-free wire format (all fields required
strings, "" = absent, mapped back to None post-call) + a guard test that
counts unions in the schema (must be ZERO). Lesson: any feature talking to a
real external API needs ONE live smoke call before being declared done —
budget a few cents for it. Same live run also surfaced max_tokens truncation
(186 variants > 16K output tokens; thinking enabled by default on Sonnet 5
eating the budget) and a thousands-separator price bug ('1,143.00') that no
synthetic fixture contained.

## 2026-07-16 — Premier déploiement prod (Scaleway)

Trois écueils au premier passage, tous du même genre : « ça marchait en dev ».
(1) Bit exécutable de deploy.sh absent de Git (repo édité sous Windows) —
et le `git reset --hard` du script écrase tout chmod manuel : le mode doit
être DANS le commit (`git update-index --chmod=+x`). (2) Alembic
`set_main_option` passe par configparser : un mot de passe Postgres avec
caractères spéciaux (url-encodé en %xx) casse en « invalid interpolation
syntax » — doubler les % ; en prime la traceback logge le DSN complet, mot de
passe inclus → rotation. (3) `initial_data` créait un utilisateur non-admin
malgré le nom FIRST_SUPERUSER — le dev masquait le bug parce qu'on avait
promu à la main. Leçon transverse : un correctif backend ne se teste jamais
via `exec` après `git pull` — le conteneur exécute l'IMAGE, il faut rebuilder.

## 2026-07-16 — Xano jette les images sans le dire (upload panneau)

« Aucune image enregistrée par Tillin » en prod, alors que le studio
enregistrait très bien : même méthode `upload_product_images`, donc ni le
réseau ni les droits. Cause réelle : `POST /product_image/{id}/bulk` répond
**200 avec `images: []`** — pas une erreur — pour tout fichier qu'il ne sait
pas décoder. Deux déclencheurs confirmés par une matrice d'appels live : un
nom de fichier **sans extension**, et le **HEIC** (format par défaut des
photos iPhone, alors que « Prendre une photo » est un geste central du
produit). Le studio n'était pas touché parce qu'il fabrique lui-même des noms
`.webp/.jpg` — le navigateur, lui, envoie ce qu'il veut.

Deux leçons. (1) Une sonde doit être VALIDE : mon premier probe était un PNG
de 87 octets bricolé — Xano le rejetait aussi, ce qui m'a fait croire un
instant que la prod était cassée alors qu'elle ne l'était pas. Tester un
chemin d'échec avec un fixture douteux, c'est mesurer son propre bruit.
(2) Un mock qui renvoie la réponse qu'on espère (`{"images": [...]}`)
n'atteste rien du contrat réel : le test existant passait au vert depuis le
début sur des octets `b"\xff\xd8fakejpeg"` que Xano n'aurait jamais acceptés.
Fix : `app/imaging/uploads.py` décode chaque dépôt (Pillow + pillow-heif),
convertit en JPEG ce qui n'est pas transférable, renomme avec l'extension du
format RÉEL, et la route lève un 502 `images_rejected` si Tillin crée moins
d'images que demandé — plus jamais de « succès » à zéro image.
