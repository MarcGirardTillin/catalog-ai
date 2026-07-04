# DECISIONS

Durable structural, tooling, workflow, security, and governance decisions for
`catalog-ai`. One entry per decision, newest last. See `CLAUDE.md` for when to
record here.

---

## 2026-06-18 — Foundation: clone the full-stack template

CatalogAI is built by cloning the internal full-stack template
(`full-stack-fastapi-template`, Tiangolo lineage, "Techlab" custom) rather than
starting from scratch. Its value is the DX harness + wiring (Makefile, prek,
ruff/mypy strict, pytest, compose, CI, typed openapi-ts client), not domain
code. Worker + queue, auth, `intake/`, `enrich/`, `sources/`, `destinations/`
are all net-new.

## 2026-06-18 — CI: keep GitHub Actions, drop GitLab

The template shipped both `.github/workflows/ci.yml` and `.gitlab-ci.yml`.
No GitLab is used → `.gitlab-ci.yml` deleted. `AGENTS.md` renamed to
`CLAUDE.md` (3 references updated).

## 2026-06-18 — Auth: app-local users (not Xano-proxy)

Users live in the app's own Postgres (`user` table, bcrypt-hashed passwords),
session = HS256 JWT in an httpOnly cookie (`catalogai_session`, samesite=lax).
Rejected alternative: proxying Xano user auth — would couple auth to Xano,
which this project exists to move away from. First user seeded via
`python -m app.initial_data` (idempotent, reads `FIRST_SUPERUSER*` env vars).
`account_id` is deliberately absent from `user` until the `account` table
lands with the first business migration.

## 2026-06-18 — Xano boundary: canonical product schema

The engine consumes a destination-agnostic canonical schema
(`app/api/schemas/product.py`), never raw Tillin payloads. All Tillin field
mapping is isolated in `app/clients/xano.py` `_map_*` helpers so the live API
contract can be confirmed/adjusted in one place.

## 2026-07-04 — Frontend: responsive from the start

Every screen is built mobile-first with Tailwind breakpoints from Phase 1 —
no desktop-only layout to retrofit. Priority: review/approve screens and
intake upload (photo of a paper order taken on a phone). Dense tables degrade
to stacked cards below a breakpoint instead of forced horizontal scroll.

## 2026-07-04 — Design system: Tillin DS ported (colors + typography only)

Tokens ported from `github.com/MarcGirardTillin/tillin-design-system` into
`frontend/src/app.css`: brand palette (navy/violet/lavande), semantic status
colors (success/info/warning/draft) for review badges, Nunito (titles) +
Roboto (body). Kept as-is: the shadcn-svelte "lyra" style's square corners
(`rounded-none`), which diverge from the Tillin DS's rounded aesthetic —
accepted trade-off to stay compatible with shadcn-svelte updates. Dark palette
is derived (source DS is light-only). Open: lucide icons vs the DS's own
linear icon set.

## 2026-07-04 — Prod topology: single origin via nginx proxy

The httpOnly samesite=lax auth cookie does not survive cross-origin XHR, so
web (nginx) and api (FastAPI) must be served from one public origin: nginx
proxies `/api` to the backend (replace `frontend/nginx/backend-not-found.conf`
with a `proxy_pass` when deploying). CORS becomes prod-irrelevant.

## 2026-07-04 — Notifications email: Brevo

Job-completion emails go through Brevo (`BREVO_API_KEY`, future
`clients/brevo`). Non-blocking: in-app notification is the fallback.

## 2026-07-04 — Agent memory: `.claude/`, not `.codex/`

The template came from a codex-based workflow; this repo uses Claude. All
`.codex/` references migrated to `.claude/` (this directory).
