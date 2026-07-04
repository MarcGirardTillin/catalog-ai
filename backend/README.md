# Backend (Minimal Template)

This backend is a minimal FastAPI base with PostgreSQL:

- PostgreSQL connection validation at application startup
- `GET /healthcheck` endpoint
- `GET /version` endpoint
- `GET /example` endpoint
- Alembic ready for future business tables, with no default application table

## Run Locally

From the repository root:

```bash
docker compose watch
```

or backend only:

```bash
make backend-start
```

For local developer onboarding, start with `make init`.
After that, `make` remains the local operations interface for the database,
the backend, migrations, and quality commands.

The frontend follows the same pattern with `make frontend-start` as the
canonical name.

For standard validation of a backend Python change, use `make check` as the
canonical command. The `make check-back` and `make check-front` variants let
you target a smaller scope.

## Endpoints

- `GET /healthcheck`
  - `200` if PostgreSQL is reachable
  - `503` otherwise
- `GET /version`
  - returns `app`, `version`, `environment`
  - adds `build`, `commit`, `branch` when those metadata are provided by the runtime environment
- `GET /example`
  - reference endpoint showing the route layout
  - does not touch the database
- the bootstrap checklist for a new application is in [docs/post-clone-checklist.md](../docs/post-clone-checklist.md)

Docstrings:

- the template documents its key extension points with short docstrings
- the recommended convention and tools for generating them are described in [backend/docs/docstrings.md](docs/docstrings.md)

Versioning:

- `version` corresponds to the stable application version read from `backend/pyproject.toml`
- `build`, `commit`, and `branch` can be set by the runtime environment without replacing the application version

Release:

- prepare local release metadata with `make release-techlab version=X.Y.Z`
- keep release notes in `release-notes-techlab.md`
- push a `techlab-vX.Y.Z` tag to publish the GitLab release after checks pass

## Backend Structure

```text
backend/
├─ app/
│  ├─ api/
│  │  ├─ main.py
│  │  └─ routes/
│  │     ├─ example.py
│  │     └─ system.py
│  ├─ core/
│  │  ├─ config.py
│  │  ├─ db.py
│  │  └─ security/
│  ├─ models/
│  │  └─ base.py
│  ├─ schemas/
│  │  ├─ error.py
│  │  └─ pagination.py
│  ├─ utils/
│  │  └─ filters.py
│  └─ main.py
├─ scripts/
│  ├─ format.sh
│  ├─ lint.sh
│  ├─ test.sh
│  └─ tests-start.sh
└─ tests/
   └─ api/routes/
      ├─ test_errors.py
      ├─ test_example.py
      └─ test_system.py
```

## Migrations (Alembic)

Alembic is kept in the template for future data model changes.

Useful commands:

```bash
make migrate-create msg="init"
make migrate-upgrade
make migrate-current
```

Policy:

- the application checks PostgreSQL availability at startup, including when using `make backend-start`, so it fails fast if the database is unreachable
- migrations are run explicitly with `make migrate-upgrade` when schema changes are introduced
