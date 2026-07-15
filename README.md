# Techlab Full-Stack Starter Template

This repository is a clone-ready minimal full-stack template for Techlab
projects.

`make` is the only local interface you need in a cloned project.

## What You Get

- a minimal FastAPI backend
- PostgreSQL and Alembic
- a minimal Svelte frontend starter shell
- local onboarding, diagnostics, and validation through `make`
- minimal GitLab CI and GitHub Actions for checks and changelog-based releases

## Quick Start

From the repository root:

```bash
make init
make db-up
make migrate-upgrade
make backend-start
make frontend-start
```

Alternative local full-stack flow:

```bash
docker compose watch
```

Canonical validation commands:

```bash
make check
make check-back
make check-front
```

Useful diagnostics:

```bash
make doctor
```

Prepare a local release:

```bash
make release-techlab version=0.12.0
```

## Local Development Model

- `make init` is the onboarding entrypoint
- `make` is the day-to-day local operations layer
- `docs/post-clone-checklist.md` is the bootstrap guide for a newly cloned
  project

The backend stays minimal on purpose. The frontend keeps a small application
shell ready for functional migration.

## Repository Guide

- `backend/`: FastAPI app, Alembic, tests, scripts
- `frontend/`: Svelte starter shell
- `docs/`: project documentation
- `release-notes-techlab.md`: changelog source for GitHub releases
- `CLAUDE.md`: single agent operating guide for this repository and its clones

## Main Docs

- [Backend guide](./backend/README.md)
- [Frontend guide](./frontend/README.md)
- [Development guide](./docs/development.md)
- [Post-clone checklist](./docs/post-clone-checklist.md)
- [Deployment — Scaleway](./docs/deployment-scaleway.md)
- [Agent guide](./CLAUDE.md)

## Clone a New Project

When you create a real application from this template, the first cleanup and
bootstrap work usually includes:

- renaming template-visible values
- configuring PostgreSQL connection values
- replacing the frontend starter shell with your own application screens
- adding the first backend domain models, migrations, routes, and tests

Use [docs/post-clone-checklist.md](./docs/post-clone-checklist.md) as the
reference workflow.

## License

This repository is distributed under the MIT license.
