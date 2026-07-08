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

## 2026-07-06 — Design system: adopt Tillin rounded corners (reverses square)

Superseded the "keep square corners" trade-off above. The `--radius-*` theme
tokens in `frontend/src/app.css` now match the DS `radius` group (sm 8 / md 12 /
lg 16 / xl 20 px) instead of deriving from a single `--radius`, and every
component's hardcoded `rounded-none` was swapped for a token class: buttons
`rounded-md` (small/icon sizes `rounded-sm`), inputs/textarea/skeleton
`rounded-md`, cards `rounded-lg`, dropdown surfaces `rounded-md` with items
`rounded-sm`. Left square on purpose: full-bleed card images
(`*:[img]:rounded-none`, clipped by the card's `overflow-hidden rounded-lg`)
and the interior card-header/footer (no visible outer corner). Favicon replaced
with the Tillin "smile" mark (white on a violet `#716df6` tile, path lifted from
the DS `tillin-logo-navy.svg`); tab title set to `CatalogAI`. HomePage now has a
"Se connecter" CTA routing to `/login` (was template filler with no auth entry).

Also closed two remaining DS gaps: (1) the status `dot` swatches
(`--*-dot` → `bg-success-dot` etc.) added alongside the existing bg/fg pairs
for review-queue badge indicators; (2) the DS `text.body` tone (`#3a3a55`,
`--body` → `text-body`) applied as the base document text color while headings
keep `ink` (`--foreground`). Mono font switched to `Roboto Mono` (DS
`font.mono`), replacing JetBrains Mono. Still intentionally NOT migrated: the
DS's `--tl-*` explicit hover hues (shadcn uses opacity-based hovers) and the
wordmark logo in the app header.

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

## 2026-07-04 — Queue: worker-terminal rollup, retry without backoff (yet)

`enrichment_item` is claimed FIFO via `SELECT ... FOR UPDATE SKIP LOCKED`
(SQLite in tests ignores the lock, keeping logic testable). Failures requeue
immediately up to 3 attempts, then `failed`; the job rolls up to
completed/partial/failed once no item is pending/processing. Exponential
backoff (tenacity) and per-host rate limiting are deliberately deferred to
Phase 2 (marked TODO in `app/jobs/queue.py` / `worker.py`). The
`backend/worker.py` entrypoint refuses to start until the real pipeline is
wired, rather than silently draining the queue.

## 2026-07-04 — Claude client: official SDK, not raw httpx

`clients/claude.py` uses the official `anthropic` SDK (per claude-api skill
guidance) with an injectable `http_client` so tests mock at the httpx
transport level — consistent with the other clients, zero real calls in the
suite. Copy generation uses structured outputs (`output_config.format`
json_schema), and the default model is `claude-sonnet-5` (plan-locked); no
sampling parameters are sent (rejected on Sonnet 5).

## 2026-07-04 — Frontend: hand-written input/label ui components

The shadcn-svelte CLI wasn't used to add input/label (network/interactive);
minimal hand-written components matching the "lyra" style (rounded-none,
h-9, text-xs) live in `src/lib/components/ui/{input,label}/`. If the CLI is
run later for the same components, diff against these before overwriting.

## 2026-07-04 — Job creation by tag defers item expansion

`POST /jobs` with `{tag}` stores the selection but creates zero items — the
worker will expand tags into product ids via the Xano read path once real
credentials exist (TODO in `api/services/enrichment.py`). Ids-based
selections create items immediately.

## 2026-07-06 — Worker wired: composed pipeline with explicit degraded mode

`app/enrich/pipeline.py` composes the Leg A steps into the worker `Processor`:
title template (default `{brand} {title}`, per-job override) → source
resolution (Shopify JSON) → weights + raw source images from the resolved
page → optional Claude copy. `backend/worker.py` no longer refuses to start
(supersedes the 2026-07-04 note): it builds the pipeline from settings and
degrades explicitly — no Xano creds → placeholder product reader (loud
LOCAL-DEV-ONLY warning), no Anthropic key → copy skipped. Photoroom image
processing remains TODO (Phase 1); staged images are the raw source URLs.

## 2026-07-06 — Review surface: `/jobs`, `/jobs/:id`, `/items/:id`

Added `GET /jobs/{id}/items` (paginated, optional status filter) and the
mobile-first review UI: `JobsListPage` (hub), `JobDetailPage` (progress bar +
counts + items, polls every 2.5s while pending/processing), `ItemReviewPage`
(editable staged title/description/meta, source link + score, image grid,
weight proposals, sticky bottom approve/reject bar — approve auto-saves dirty
edits). Shared `AppHeader` + `StatusBadge` (Tillin bg/fg/dot triplets). Typed
client regenerated (`jobsListJobItems`).

## 2026-07-06 — Xano read path wired against the live contract

Confirmed the Tillin Xano contract against the live API and rewrote
`clients/xano.py`. Auth is **email/password login → bearer `authToken`**
(JWT; cached, re-login once on 401) — there is no static service token, so
`XANO_SERVICE_TOKEN` is replaced by `XANO_LOGIN_EMAIL`/`XANO_LOGIN_PASSWORD`.
An `X-Data-Source: test` header (`XANO_DATA_SOURCE=test`) selects the seeded
test datasource (381 products) vs the near-empty live default. Two reads:
`search_products` (free text + brand/category/supplier/season/tag filters over
`/products_with_pagination`, parsing the `{items,itemsTotal,curPage}` envelope)
and `get_product` (`/product/{id}` detail, 404 → None) — the worker reader now
uses the latter. The client is a process-wide singleton in `deps.py` (one login
reused across requests). `GET /products` exposes search+filters+pagination.

Two contract facts that shape the app: (1) the product payload carries only
`brand_id` — **no nested brand and no website URL**, so the brand's source
site(s) for scraping must live in CatalogAI (deferred); (2) images live on
variants (`product_image.src`), not the product. Verified live end-to-end:
search returns 381, a job over real ids stages real Tillin titles through the
worker (source resolution `skipped` until brand websites exist).

## 2026-07-06 — Product selection happens in CatalogAI

`products_with_pagination` has no by-ids filter, and (per the user) its search
+ filters are the natural way to pick products. So selection is a CatalogAI
screen (`ProductSearchPage`, `/products`): search/paginate the Tillin catalog,
tick products, "Créer un job" builds a job from the selected ids. The main
flow is now search → select → job (the header/CTAs point to `/products`;
`/jobs/new` remains for direct id/tag entry). The Xano bearer token never
reaches the browser — the backend proxies behind the session cookie.

## 2026-07-06 — Search filters from /get_all_informations; CatalogAI selection

Product search exposes classification filters (brand, category, season,
supplier, tag) sourced from Tillin's `/get_all_informations`
(`company_all_informations.{brands,categories,seasons,suppliers,tags}`,
normalized to `{id,title,parent_id?}` and cached). New `XanoClient.
get_classification()` + `GET /catalog/filters` back the frontend
`FilterSelect` dropdowns on `ProductSearchPage`, which also now shows each
product's brand name + category. Brand website URLs are normalized to add a
scheme (Tillin stores bare hosts like `salomon.com`).

## 2026-07-06 — Auth: Xano credentials accepted as a login fallback

`/auth/login` tries app-local users first, then falls back to validating the
credentials against Xano (`verify_login` → `/auth/login` + `/auth/me`). On
success a local "federated" user is upserted (random unusable password;
`get_or_create_federated_user`) and the normal session cookie is issued. This
lets Tillin/Xano users sign in with their Xano identifiers without a separate
account, while keeping the session model unchanged. Gated on `xano_configured`.
Verified live end-to-end (real Xano user → CatalogAI session). Does NOT
supersede the 2026-06-18 "app-local users" decision — local users still work;
Xano is an additional provider, not a proxy.

## 2026-07-06 — Full Leg A pipeline verified on live data

End-to-end proof with real integrations: Xano product read (brand name,
category, website URLs) → Shopify JSON resolution (ARMEDANGELS matched by
barcode, score 1.0, 6 images + source URL scraped) → Claude copy (real FR
description + meta via `claude-sonnet-5`). Confirms the injectable pipeline
works with real clients, not just mocks. Still TODO: Photoroom 4:5 image
processing, weight mapping coverage, apply/writeback to Xano.

## 2026-07-06 — Writeback (apply): destinations/ port + Tillin adapter

Approved items are written back through a destination port
(`app/destinations/base.py::Destination`), keeping the engine
destination-agnostic. First adapter `xano_tillin.py` maps staged fields onto
Tillin's write endpoints: copy → `POST /product/{id}/enrich`
(`{title, description, meta_description}`), images → `POST /product_image/
{id}/bulk` (`{image_urls: [...]}`, URLs directly — Tillin ingests them, so no
Photoroom upload needed). Images pushed before copy. `POST /items/{id}/apply`
(approved → applied) drives it via `apply_item`; only `approved` items apply
(guards double-writes — critical because the bulk endpoint APPENDS images, it
does not replace). Manual push only (a button), per the saved "never auto-push"
feedback. `staged_weights_json` is NOT written (Tillin weight endpoints are
per-product/per-variant and separate; left review-only for now). Verified live:
the adapter wrote a real title/description/image to a Tillin test product.

## 2026-07-08 — Jobs auto-trigger on creation + run duration

`POST /jobs` now schedules processing via FastAPI `BackgroundTasks`
(`app/jobs/runner.py::process_pending` drains the queue in-process using a
cached pipeline). The standalone `worker.py` still works (same pipeline via the
shared `build_pipeline` factory; safe to run alongside thanks to
`FOR UPDATE SKIP LOCKED`) but is no longer required for the UI to process jobs.
The runner is injected as a dependency (`get_job_runner`) so tests override it
with a no-op (TestClient runs background tasks inline; the autouse default keeps
job-count assertions valid). Run duration: `enrichment_job` gained
`started_at` (set at first claim) / `finished_at` (set when `_rollup_job`
settles the job); `JobPublic.duration_seconds` is computed and shown on the Job
page (live "en cours depuis …" while running). Migration `0004`.

## 2026-07-08 — Review screen: manual resolution + Tillin context + persisted candidates

The resolver already produced `candidates` + `reason`; the pipeline now
persists them on the item (`resolution_json`, migration `0005`) so the review
UI can (a) diagnose why a product landed in `needs_manual` and (b) offer the
below-threshold candidates as one-click picks. `POST /items/{id}/resolve`
(`{source_url}`) re-stages an item from a chosen/pasted Shopify product URL via
`EnrichmentPipeline.stage_from_url` (source_method="manual"); allowed while
ready_for_review/approved, 422 on an unreachable/non-product URL. Injected as
`PipelineDep` (`get_enrichment_pipeline`). `GET /items/{id}/product` returns the
current Tillin product (canonical Product gained `description`/`meta_description`)
for before/after context. Review page redesigned: "Produit actuel (Tillin)"
card (ref/brand/category/variants/current images+description), source card with
diagnostic + candidate picker + manual-URL input, char counters on title/meta,
meta as a textarea. NOTE: Windows uvicorn `--reload` did not pick up new routes
until a full restart (WatchFiles miss) — see MISTAKES.

## 2026-07-08 — Sprint A review/apply UX (parallel workers) + retry

Executed with two parallel workers (backend-only / frontend-only write sets), per
the delegation workflow. Ships:
- Title fix: `apply_title_template` drops the `{brand}` token when the brand
  name already appears in the title (word-boundary, case-insensitive) — Tillin
  titles usually embed the brand, so `{brand} {title}` duplicated it.
- Category on detail: Tillin's `/product/{id}` carries only a flat
  `category_id` (list shape nests `{category:{title}}`); `_map_category`
  resolves it via a lazy non-fatal `_category_map()` built from
  `/get_all_informations` (same pattern as `_brand_map`). Verified live
  (#2680 → "T-SHIRTS").
- Review screen: before/after side-by-side (current Tillin title/description/
  meta read-only next to the editable proposed fields), variant count without
  SKU list, and a three-action bar: Rejeter / Valider / **Valider et
  appliquer** (save→approve→apply chained; if apply fails after approve the
  screen falls back to the existing "Appliquer" bar).
- Retry: `POST /items/{id}/retry` (full re-generation: wipes staged_*/
  resolution, resets attempts, re-opens the job, background-runs) and
  `POST /jobs/{id}/retry` (requeues failed+rejected). `applied` is NOT
  retryable yet — Tillin's bulk image endpoint appends, so re-apply needs an
  image-dedupe guard first (planned with Sprint B). UI: "Régénérer" button on
  the item screen, "Relancer les échecs (n)" on the job page.

## 2026-07-08 — UI refonte R1: SaaS app shell

The authenticated UI moved from a centered-column-with-navbar layout to a SaaS
app shell (`AppShell.svelte`): fixed 240px sidebar (wordmark, Dashboard/
Produits/Jobs nav with active state, user block + ThemePicker at the bottom),
sticky h-14 topbar with breadcrumbs (prop-driven `{label, href?}[]`, replaces
the artisanal "← back" links) and a user menu (initials avatar → bits-ui
dropdown, logout). Mobile: sidebar becomes a drawer. Action feedback moved from
inline text to svelte-sonner toasts (top-right, theme-synced); form-validation
errors stay inline. LoginPage restyled (wordmark + card on a soft radial halo);
HomePage became a dashboard placeholder (shortcut cards; KPIs planned for R2).
`AppHeader.svelte` deleted. Fixed bottom action bars are offset `sm:left-60` to
clear the sidebar. Remaining phases: R2 (KPI dashboard, jobs table, filter
chips), R3 (item-to-item review nav, keyboard shortcuts, confirmations).
Settings pages from Sprint B will live in the sidebar.

## 2026-07-08 — UI refonte R2: dashboard KPIs, jobs table, filter chips

New account-scoped `GET /stats/dashboard` (applied/ready/running counts, avg
per-item processing seconds over settled items, auto-resolution rate =
shopify_json share of settled source_methods; date math Python-side for
Postgres/SQLite parity). HomePage is a real dashboard: 4 stat tiles following
the dataviz stat-tile contract (sentence-case label, semibold proportional
figures, text tokens — no accent color on values), auto-resolve line, 5 recent
jobs, quick actions, empty state. JobsListPage: cards → SaaS table (status,
mini progress bar, products, duration, relative date; tabular-nums only in
table columns; keyboard-accessible row links). ProductSearchPage: active-filter
chips (removable, "Tout effacer" at ≥2) + richer empty state with reset.
Shared `lib/format.ts` (formatDuration, formatRelativeDate). R3 remains:
item-to-item review nav, keyboard shortcuts, confirmations, dark-mode polish.

## 2026-07-08 — Per-field apply selection + products-as-table

Reviewers can now decide field by field what gets written to Tillin:
`enrichment_item.apply_fields_json` (migration 0007; {"title": false, ...} —
missing key or null = apply). The Tillin adapter skips unchecked fields and
makes no enrich call when all copy fields are excluded; the images bulk call is
skipped when "images" is false. UI: an "Appliquer" checkbox per field on the
review screen (unchecked = dimmed proposed block), persisted through the
existing save-if-dirty flow (normalized comparison: true ≡ absent), plus a
non-blocking "nothing will be written" warning. ProductSearchPage's card grid
became a JobsListPage-style table (row selection + current-page select-all with
indeterminate state, thumbnail, title+ref, brand, category, variant count);
multi-page selection Set, chips, pagination and the sticky create-job bar are
unchanged.

## 2026-07-08 — UI refonte R3: serial review flow

ItemReviewPage gained sibling navigation (prev/next + "3/7" position from the
job's item list, ←/→ keys), decision chaining (Valider / Rejeter / Valider et
appliquer / Appliquer now jump to the NEXT ready_for_review item of the job —
forward first, wrap to start — and only fall back to the job page when nothing
is left to review), keyboard shortcuts (V approve, R reject, A
approve-and-apply or apply, inactive while typing in a field, kbd hints on the
buttons desktop-only), and a two-step reject (first activation arms the button
— "Confirmer le rejet", destructive variant, 4s auto-reset — second confirms;
no modal primitive needed). Navigating between items resets the page state so
each item shows a fresh skeleton.

## 2026-07-08 — Settings: user preferences + account defaults

New Paramètres section (sidebar entry + /settings page, 4 cards). Storage:
`user.preferences_json` + `account.settings_json` (migration 0008), validated
at the API boundary by UserPreferences / AccountSettings schemas (defaults fill
missing keys; PUT sends the full object). User prefs: shortcuts_enabled
(DEFAULT OFF — review V/R/A/arrows are opt-in, kbd hints hidden when off),
auto_advance (continueReview falls back to the job page when off), table
density (comfortable/compact cell padding), products_per_page (read at call
time). Account defaults: title_template + editorial_instructions are MERGED
into new jobs' config_json when the job doesn't override them (create_job),
meta_max_length, and notify_on_job_done/notify_email saved as a Brevo
placeholder (badge « Bientôt actif », no email sent yet). Also:
GET /settings/connection (configured/host/data_source, never a secret) and
POST /auth/password (current password required, min 8; federated Xano users
can't pass the current-password check by design — their credential lives
upstream). Frontend prefs live in a module-level runes store
(lib/preferences.svelte.ts) loaded once by RequireAuth.

## 2026-07-08 — Sprint B: steerable generation (instruction library, boutique context, job options)

Named editorial instructions live in their own table (`instruction_template`,
migration 0009: account_id, name, content, categories_json) with account-scoped
CRUD at /instructions — NOT in settings_json, because they are a growing list
with per-category defaults, not a single value. Jobs SNAPSHOT instructions at
creation: `config.instruction_id` is resolved server-side into
`config.editorial_instructions` and then dropped from the persisted config, so
deleting/editing a template never rewrites past jobs. When neither an
instruction nor free text is chosen, create_job snapshots
`category_instructions` ({category: content} from templates claiming
categories; newest wins a disputed category) and the pipeline picks by
product.category at stage time. Instruction precedence (locked by tests):
explicit editorial_instructions > instruction_id > account default
editorial_instructions > category_instructions. Account defaults merged into
job config grew to title_template, editorial_instructions, client_context,
meta_max_length. Pipeline: `extra_website_urls` extend the brand sites for
resolution (dedup, order kept); `seo_keywords` join the copywriter's product
context; `client_context` is prefixed as a "Contexte boutique :" block before
the instructions; meta_max_length parameterizes the Claude system prompt
(was hardcoded 160).

Frontend: Paramètres became 3 tabs (Préférences / Enrichissement / Compte) —
panels stay mounted (hidden) so unsaved input survives tab switches. The
Enrichissement tab hosts the relocated title-template builder, the boutique
context markdown, meta_max_length, and the instruction library
(lib/components/settings/InstructionLibrary.svelte, two-step delete). Job
options (instruction picker with "Automatique"/library/"Texte libre…", SEO
keyword chips, one-URL-per-line extra sources) live in a shared
JobOptionsPanel used by ProductSearchPage (collapsible above the sticky
selection bar) and JobNewPage; only filled keys are sent in config. The review
meta counter now reads meta_max_length from a lazy accountSettings store
(lib/accountSettings.svelte.ts) instead of a hardcoded 160. The /instructions
calls use the generated axios `client` with raw paths (lib/api/instructions.ts)
— written before regen, kept because they are thin and typed locally.

## 2026-07-08 — Per-image/per-weight apply selection + brand website_urls management

`apply_fields_json` grew per-entry selection keys next to the per-field booleans:
`image_urls` (subset of staged image URLs to send; absent = all, empty = none,
unknown URLs ignored, staged order preserved, no effect when `images: false`)
and `weights` + `weight_variant_ids` (same rules). The schemas' typing relaxed
from dict[str, bool] to dict[str, Any] to carry the lists. Weights writeback to
Tillin still does NOT exist (needs the Xano set_variant_weights endpoint, plan
infra) — the destination computes the filtered selection but sends nothing; the
review UI says so with a « Bientôt actif » badge. Review UX: whole thumbnail
toggles selection (deselected = opacity-40 + ring), "n/m sélectionnées" +
select-all/none; keys are OMITTED when everything is selected; selection
participates in `dirty` and is saved through the existing PATCH flow.

Brand reference websites are now manageable in-app: XanoClient.list_brands()
(GET /brand, errors surfaced — unlike the best-effort _brand_map cache) and
set_brand_website_urls() (POST /brand/{id}/website_urls per the user-provided
Xano endpoint, body {"website_urls": [...]}, URLs normalized via
_normalize_url, then the _brands cache is invalidated so subsequent product
reads see fresh URLs). App routes GET /brands + PUT /brands/{id}/website_urls
(max 20 URLs, 500 chars each). Settings gained a 4th « Marques » tab: lazy
first-open load, client-side name search, inline one-URL-per-line editing,
optimistic row update. The PUT's upstream write shape (body key) is assumed
from the endpoint name and must be confirmed against real Xano on first live
use.
