# CLAUDE.md

Agent guidance for `catalog-ai` (CatalogAI).

This repository uses a single agent guide. There is no separate project overlay:
everything an agent needs to work safely in this repo should live here.

## Quick Rules

- Explore before asking.
- Plan non-trivial work before implementing it.
- Prefer small, focused, reversible changes.
- Verify before concluding.
- Update tests and docs when behavior changes.
- Avoid destructive Git operations unless explicitly requested.
- Use `make` for onboarding, checks, and day-to-day local operations.
- Do not read or print secrets from `.env`, `*.crt`, vault exports, or untracked secret files.

## Project Identity

- Project name: `full-stack-fastapi-template`
- Main goal: provide a reusable full-stack application template with a minimal FastAPI backend, a frontend starter, and local developer onboarding
- In scope:
  - backend template structure and examples
  - frontend starter and generated client workflow
  - local developer tooling and onboarding
  - minimal GitLab/GitHub check and release workflow
  - template documentation
- Out of scope:
  - product-specific business features unrelated to template reuse
  - secret values and environment-owned infrastructure changes

## Repository Map

- `backend/`: FastAPI backend, Alembic, tests, CLI internals, scripts
- `frontend/`: Svelte 5 frontend and generated client
- `docs/`: project-level documentation
- `.claude/`: durable memory for decisions and mistakes
- `scripts/`: shared shell helpers and repo entrypoints

## Working Rules

- Inspect repository truth first: code, configs, docs, scripts, and entrypoints.
- Use a real plan for multi-step work, architectural changes, migrations, or risky refactors.
- Prefer the simplest solution that fully solves the problem.
- Fix root causes when reasonably possible; do not hide issues behind cosmetic patches.
- When a bug is reported, investigate and drive the fix instead of asking the user to orchestrate debugging.
- If reality diverges from the plan, stop, re-ground, and adjust.
- Keep explanations concise and implementation-oriented.
- Keep changes focused and template-oriented. Do not turn the template into a one-off project.

## Access Control (check on EVERY code change)

CatalogAI est multi-entreprises avec des droits par compte. À chaque
modification de code (nouvelle route, nouveau bouton, nouveau chemin
d'exécution), vérifier qu'elle ne permet PAS de contourner les droits :

- **Modules par compte** (`feature_import` / `feature_enrich` /
  `feature_studio`) : toute nouvelle route d'un module porte
  `require_feature(...)` (garde serveur — l'UI seule ne suffit jamais) ;
  tout nouveau geste UI d'un module est conditionné par les flags de
  `/stats/dashboard`.
- **Bypass admin assumé** : l'admin plateforme (`user.is_admin`) passe
  toutes les gardes de modules (support/prestation sur les comptes
  clients) et reçoit tous les flags à vrai dans `/stats/dashboard`.
  Ne PAS étendre ce bypass aux crédits ni au scoping des données.
- **Scoping multi-entreprises** : toute lecture/écriture locale est filtrée
  par `account_id` ; tout appel Xano catalogue passe par
  `xano_client_for_account` (token du compte — jamais l'identité de service
  pour un compte d'entreprise).
- **Admin-only** : grille tarifaire, coefficient, réglages
  `ADMIN_ONLY_SETTINGS`, routes `/admin/*` restent derrière
  `get_current_admin`.
- En cas de doute sur un nouveau chemin, écrire le test 403 d'abord.

## Sensitive Areas

- Never read or print secrets from `.env`, `*.crt`, vault exports, or untracked secret files.
- Never commit credentials, certificates, or tokens.
- Treat these paths as sensitive and validate carefully after edits:
  - `backend/app/core/config.py`
  - `Makefile`
  - `scripts/`
- If unrelated local changes appear, stop and check with the user before modifying the same files.

## Local Workflows

- Onboarding:
  - `make init`
  - `make doctor`
  - `make check`
- Local backend:
  - `make db-up`
  - `make migrate-upgrade`
  - `make backend-start`
  - `docker compose watch`
- Quality:
  - `make check`
  - `make format`
  - `make lint`
  - `make mypy`
  - `make pytest`
- Release flow:
  - keep upcoming changes in `release-notes-techlab.md`
  - finalize with `make release-techlab version=X.Y.Z`
  - publish with a `techlab-vX.Y.Z` tag
Defaults:

- `make` is the human-facing onboarding and local operations surface.
- `make format` is mutating; `make lint`, `make mypy`, and `make pytest` are validation commands.

## Validation Rules

- Use the repository's documented commands and workflows whenever possible.
- Prefer reproducible checks over ad hoc manual validation.
- Do not consider a task done until you have run the relevant checks yourself, unless the environment makes that impossible.
- If something cannot be verified locally, say what remains unverified and why.
- Backend code changes should normally end with `make check`.
- Tooling, onboarding, or local workflow changes should be validated with the relevant documented commands, especially `make init`, `make doctor`, or `make check`.
- Documentation-only changes should still be checked against the real commands and paths in the repo.
- CI/release changes should keep `.github/workflows/ci.yml` free of deployment jobs unless deployment is intentionally reintroduced (`.gitlab-ci.yml` was removed — this repo uses GitHub Actions only).

## Documentation and Memory

- Keep durable guidance in repository docs, not only in chat.
- Update public docs when behavior, workflows, or interfaces change.
- Update these docs when relevant:
  - `README.md` for top-level entrypoints and onboarding
  - `docs/development.md` for local workflow changes
  - `release-notes-techlab.md` for release notes
  - `backend/README.md` for backend structure and usage changes
  - `frontend/README.md` for frontend starter/auth changes
  - `docs/post-clone-checklist.md` for clone/bootstrap workflow changes
- Record structural, tooling, workflow, security, and template-governance decisions in `.claude/DECISIONS.md`.
- Record reusable failure learnings in `.claude/MISTAKES.md`.

## Delegation Workflow

- Use built-in agents before inventing project-local subagents.
- Default split for mixed backend/frontend work:
  - keep the main thread as orchestrator
  - assign one built-in `worker` to `backend/` only
  - assign one built-in `worker` to `frontend/` only
  - keep docs, release notes, generated-client decisions, and final validation in the main thread unless a task is explicitly isolated
- Ownership defaults:
  - `backend/`: backend worker
  - `frontend/`: frontend worker
  - `.github/workflows/`, `Makefile`, `scripts/`, docs, release notes: main thread by default
- Guardrails:
  - do not let both workers edit generated frontend client files at the same time
  - if OpenAPI regeneration is needed, decide centrally in the main thread after backend contract changes settle
  - tell each worker its write boundary explicitly and remind it not to revert the other worker's edits
  - prefer explorer sidecars for read-only review or repo scans; prefer workers only when the write sets are actually disjoint

## Telemetry & Feedback Loops

Use observable signals before declaring success.

Keep these concepts distinct:

- `DECISIONS`: durable choices about design, tooling, workflow, or security
- `MISTAKES`: retrospective learnings about failures, root causes, fixes, and prevention
- `Telemetry`: signals that help validate a milestone or diagnose a problem right now

Typical telemetry sources in this repo:

- stable commands:
  - `make doctor`
  - `make check`
- runtime/API signals:
  - `GET /healthcheck`
  - `GET /version`
  - `GET /example`
  - `/docs`
- business traces:
  - backend logs via `docker compose logs backend`

Blocking signals by default:

- failing tests
- broken `make init` onboarding flow
- unhealthy backend healthcheck
- migration failures
- inconsistent docs for the canonical onboarding path

Non-blocking signals by default:

- warnings that are expected and documented
- unavailable external integrations when the task is documentation-only or local-only

Completion rule:

- before calling a milestone done, prefer at least one direct telemetry signal, not only static reasoning

## Secrets / Environment Notes

- Secrets should live in a local password manager or secret manager, not in tracked files.
- Sensitive environment variables should not be copied into docs or commit messages.
- Use the post-clone checklist when validating whether the template still supports a fresh-project bootstrap.

## Optional Project-Specific Notes

- Keep the template generic and reusable; examples should teach patterns, not lock the repo into a fake business domain.
- When adding sample modules, prefer realistic cross-cutting examples like onboarding or client integration patterns.
- If a change affects how future teams clone or bootstrap the repo, treat it as a documentation and onboarding change, not only a code change.
