# Development

## Quick Start

If you are setting up a new application cloned from this template, start with
the [post-clone checklist](./post-clone-checklist.md) before the local
quick start.

1. Install tooling and hooks:

```bash
make init
```

If `uv` is missing, `make init` will prompt before installing it with the
official Astral installer.

`make init` also checks that Bun is available, can prompt to install it on
Linux/macOS with the official `https://bun.com/install` installer, and then
installs the frontend dependencies from `frontend/bun.lock`.

Frontend runtime note:

- Frontend tooling requires a runtime compatible with Node `>=24.0.0`
- if you use `nvm` or `fnm`, prefer a recent Node 22 release compatible with
  that range
- `make doctor` warns when Bun exposes an older Node compatibility version
- `make init` and `make check-front` fail early with a clear message instead of letting `vite` crash later
- `make frontend-start` and `make frontend-build` perform the same compatibility guard before invoking Vite

2. Start the local database:

```bash
make db-up
```

3. Apply pending migrations:

```bash
make migrate-upgrade
```

4. Start the backend locally:

```bash
make backend-start
```

5. Start the frontend locally in a second terminal:

```bash
make frontend-start
```

6. Open local services:

- Frontend: <http://localhost:5173>
- Backend API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>

## Frontend Starter

Configure these values in `frontend/.env` for local Vite development:

```env
VITE_API_URL=http://localhost:8000
VITE_APP_NAME=Techlab starter
VITE_ENV=local
```

Expected local behavior:

- users can open `/`
- the home page shows a minimal starter shell
- backend version remains visible in the footer

Current frontend scope at this stage:

- starter shell only
- no business UI yet

Optional full-stack workflow:

```bash
docker compose watch
```

This also starts the frontend and Adminer. In that mode, local services are:

- Frontend: <http://localhost:5173>
- Backend API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- Adminer: <http://localhost:8080>

## Logs

```bash
docker compose logs
docker compose logs backend
```

## Run Backend Locally (without backend container)

If you want to run backend from source while keeping DB in Docker:

```bash
docker compose stop backend
make backend-start
```

## Makefile Commands

For the concise daily workflow command list:

```bash
make help
make init
make doctor
make check
make check-back
make check-front
make db-up
make backend-start
make frontend-start
make frontend-build
make frontend-lint
make format
make lint
make mypy
make pytest
make migrate-create msg="your message"
make migrate-upgrade
make compose-watch
make release-techlab version=X.Y.Z
```

For less common advanced/internal commands, run:

```bash
make help-advanced
```

## Database and Migrations Policy

- The backend checks PostgreSQL reachability at startup and fails fast if the database is unavailable.
- Startup reachability checks do **not** run Alembic migrations.
- Apply migrations explicitly before starting local work that depends on the latest schema:

```bash
make migrate-upgrade
```

## Docker Compose Files

- `compose.yml`: base stack configuration.
- `compose.override.yml`: local development overrides (watch/sync, debug, ports).

## Pre-commit and Quality

This repository uses `prek` with `.pre-commit-config.yaml`.

Install hooks:

```bash
make precommit-install
```

This command also ensures `uv` is available and will prompt before installing
it if it is missing.

The hook installation includes:

- `pre-commit` hooks for formatting and validation

## Release Flow

The repository keeps minimal GitLab CI and GitHub Actions flows without
deployment jobs. Both run backend and frontend checks. Both can publish a
release from the matching `release-notes-techlab.md` section when you push a
tag named `techlab-vX.Y.Z`.

Local preparation:

```bash
make release-techlab version=X.Y.Z
```

This command:

- updates `backend/pyproject.toml`
- updates `frontend/package.json`
- moves `## Latest Changes` from `release-notes-techlab.md` into
  `## X.Y.Z-techlab`
- creates a fresh `## Latest Changes` section for future work

After reviewing and committing those changes, create and push the release tag:

```bash
git tag -a techlab-vX.Y.Z -m "Techlab release X.Y.Z"
git push origin techlab-vX.Y.Z
```

GitLab CI or GitHub Actions then runs the check jobs and publishes a release
from the matching `release-notes-techlab.md` section.

Run hooks manually:

```bash
make precommit-run
```

The standard validation sequences are:

```bash
make check
make check-back
make check-front
```

If you need the underlying commands individually, they remain available:

```bash
make format
make lint
make mypy
make pytest
make frontend-format
make frontend-lint
make frontend-build
```
