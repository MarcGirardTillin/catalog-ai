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

## 2026-07-09 — Import sprint I1: supplier-file parse & LLM extraction shipped

Frozen contract in backend/app/imports/schema.py (main-thread owned): grain =
product per supplier reference, color × size as variant axes, Decimal prices,
per-field confidence; parsers produce RawDocument (pdf passthrough / tabular
raw cells), extraction returns ExtractionResult with token usage. Extraction
is Claude structured outputs with a UNION-FREE schema ("" = absent — the live
API caps union parameters at 16; see MISTAKES) — thinking disabled (mechanical
transcription; Sonnet 5 defaults to adaptive thinking which ate the output
budget), max_tokens 32K (~100 output tokens per variant; 16K truncated a
186-variant order), explicit 600s request timeout. Anti-hallucination:
tabular sources cross-check every EAN and price against the raw cells
(unverifiable value -> null + warning + confidence 0; verified -> 1.0); PDFs
validate EAN-13 check digits. Price parsing handles both separator
conventions incl. thousands separators ("1,143.00" — found by the live run).
Plumbing: enrichment_job.job_type + import_item + usage_event (migration
0010), POST /imports (multipart, UPLOAD_DIR uuid storage), import runner as
background task with injectable parse/extractor, GET /jobs excludes imports.
Metering M1 live: usage_event rows written for enrichment copy calls AND
import extractions (input+output tokens, provider/model/source/job).
Frontend: Imports nav + list (jobs-style table), dropzone upload page, detail
page with 2.5s polling, read-only product table (expandable variants, low-
confidence ambre < 0.7, "n sans EAN" badges) — editable review grid is I2.
Live validation on real files: LTDC Excel -> 19 products / 184 variants /
184 EANs verified at confidence 1.0 (~31K in / 26K out tokens); L'Espion PDF
(Paul Smith) -> 36 products / 88 variants, brand+colors+sizes+qty+prices, no
EANs (expected — profile territory, I2). Operational note: the org's Claude
rate limit is 4,000 output tokens/min — one big file consumes minutes of
quota; consider a tier bump before production import volume.

## 2026-07-09 — Import sprint I2: profiles, review grid, CSV + direct Xano transfer
Import profiles are data-driven per (account, supplier) — `import_profile`
table (migration 0011), frozen rule shapes in
`app/api/schemas/import_profiles.py`: price retail_as_is | coefficient
(wholesale x coef rounded UP to round_up_to, default 5 — Barbara Bui
440 x 2.8 -> 1235 verified against the real file), barcode ean | constructed
(REF-COLOR-SIZE), brand as_extracted | fixed, supplier/season labels,
gender/category defaults, tax_rate, status. ONE rendering engine
(`app/imports/tillin_csv.py`, 30-column template frozen against
everyday-tasks fixtures) feeds the JSON preview, the CSV download AND the
transfer — never divergent implementations. Direct transfer to Tillin:
`POST /imports/{id}/transfer` renders the CSV and posts it to Xano
`POST /product_import` (multipart `file_import` + `location_id`; user
confirmed contract 2026-07-09); locations come from `get_all_informations`
filtered of third-party origins (`GET /locations`). CSV download stays as
the backup path. Review: PATCH item payload validated against
ImportedProduct, statuses limited to ready_for_review/rejected; rejected +
failed items never reach the CSV; items become `applied` after transfer
(then read-only in the UI). Document-level extraction also captures
po_number + supplier (never guessed), used for auto-suggesting the profile
and naming the CSV (`import_{supplier}_{po}.csv`). Extraction schema stays
union-free; the change was validated with a live API call (PO-2026-0442 /
L'Espion correctly read). Source-file preview shipped alongside: inline PDF
+ client-side CSV preview pre-upload, server-parsed preview + original file
download on the detail page (`GET /file`, `GET /file/preview`).

## 2026-07-09 — Usage metering M2/M3 + Enrichment workspace
Billing brick shipped: `usage_price` table (migration 0012) holds the unit
price per (provider, model NULL=provider-wide fallback, metric); cost is
NEVER stored on usage_event — computed at read time so repricing stays
possible. billable = cost x account `billing_coefficient` (AccountSettings).
Endpoints: /usage/summary (monthly, per-model lines, unpriced lines counted),
/usage/by-job (import file_name / "Job #n" labels, sorted by cost),
/usage/export (invoice CSV with TOTAL row), CRUD /usage/prices. UI
« Consommation » page: month picker, cost/billable/token cards, per-model +
per-job tables, editable price grid (token prices entered per MILLION,
stored per unit), coefficient field, CSV export, dashboard tile.
Enrichment moved OUT of Paramètres into its own sidebar workspace
(user decision: it's a feature, not a preference): tabs Instructions
(library + search), Contexte boutique, Modèle de titre; components live
under lib/components/enrichment/. Cross-page AccountSettings writes go
through saveAccountSettingsPartial (GET->merge->PUT) so pages never
clobber each other's fields. Priorities reshuffled (user, 2026-07-09):
I3 direct Xano creation moved to the END of the plan — the live-validated
/product_import CSV transfer covers the need.

## 2026-07-09 — Title casing + monthly price freeze
Title casing: AccountSettings.title_case (none|upper|capitalize), snapshotted
into each job's config, applied in apply_title_template. `capitalize`
upper-cases the first letter of every word but leaves the rest untouched
(preserves acronyms/brands like COTON/ARMEDANGELS), unlike str.capitalize.
Price freeze (billing correctness): AccountSettings.billing_day (1..28,
default 1) = the day of the FOLLOWING month a period is billed on (July billed
on billing_day of August). A month is frozen once today >= its billing date.
On first read of a frozen month, an immutable UsageBillingSnapshot (migration
0013) pins the prices + coefficient; summary/by-job/export/timeseries then use
the frozen prices (usage_event quantities stay immutable, so recomputed costs
are stable). Current/future months keep the live grid. Safety net:
POST /usage/snapshot re-freezes from the current grid (400 not_frozen on a
non-billed month). `_now()` is an injectable module-level clock so freeze tests
are deterministic. New endpoint GET /usage/timeseries?group_by=none|model|
provider returns daily billable (+quantity) for the three chart views; the UI
draws them as inline SVG (no chart lib). Rationale for billing_day over
auto-at-rollover: it gives Marc a window after month-end to verify before the
figures lock — his explicit choice ("date de facturation dans les paramètres").

## 2026-07-09 — Information architecture: pipeline-first navigation
User-validated redesign. Sidebar in two sections — Pipeline (Tableau de bord,
Imports, Produits, Enrichissements) and Configuration (Profils d'import,
Instructions, Consommation) — URLs unchanged, only labels/breadcrumbs.
Renames: « Jobs » -> « Enrichissements » (the activity), « Enrichissement » ->
« Instructions » (the writing config), « Profils » -> « Profils d'import ».
Status wording harmonized: ready_for_review = « À vérifier » everywhere;
rejected = « Écarter/Écarté » (replaces both « Rejeter » and « Exclure »);
final state stays contextual: « Transféré » (import = creation) vs
« Appliqué » (enrichment = update) via a StatusBadge context prop.
Import->Tillin product link: /product_import returns no created ids, so
items are linked a posteriori by reference_code (Xano search, exact
normalized match, ambiguity -> not_found) into import_item.tillin_product_id
(migration 0014), POST /imports/{id}/link-products (idempotent). Verified
live: 4/4 sampled refs of the real transferred L'Espion order resolved.
Products page: tabs Catalogue / Par import (?import=ID deep link from a
transferred import). ProductPanel side panel (first drawer of the app):
completeness split validated by Marc — « Prêt boutique » = titre, réf,
≥1 variante, prix (new Product.price mapped from Tillin's nested
price.amount), catégorie, marque; « Prêt e-commerce » = ≥1 image,
description, meta, poids; « titre harmonisé » is a non-blocking bonus.
Photoroom actions in the panel are documented in plan.md only (détourage,
reformatage, mannequin porté <-> à plat) — not built. Orphan /jobs/new
removed. Bridge: « Voir / Enrichir les produits créés » on transferred
imports closes the pipeline loop import -> enrichment.

## 2026-07-09 — Product read-mapping fixes + panel expansion + category-tree matching

Product panel data gaps traced to a read-mapping omission, not a UI bug:
`_map_product` (xano.py) never read `season_id`, `department_id`,
`composition_id`, `tags_id` nor `manufacturing_country`, so « saison » and
« rayon » (and more) were always empty in the panel. Fixed by resolving them
through the classification maps (season/composition/tags, one cached
`/get_all_informations` call) and, for departments, a STATIC map
`{1: Homme, 2: Femme, 3: Unisex}` — Tillin exposes no department titles (no
`/department` endpoint, absent from get_all_informations); Marc supplied the
mapping. Variant couleur/taille are read from the positional `options` array
aligned to `product_options` (`{name, position}`, case-varying names matched by
substring); variant prix d'achat from `wholesale_price.amount`. Only the detail
read (get_product) resolves the full set — the list/search keeps its cheap
mapping (category from the nested object, department from the static map).
`Product`/`ProductVariant` gained composition, manufacturing_country, tags,
color, size, wholesale_price; OpenAPI client regenerated. Verified live on real
products before shipping (mock ≠ reality discipline).

Panel UX (Marc's asks): wider (`sm:w-[36rem]`), completeness moved to the
BOTTOM, added description + meta description + a full variants table (taille,
couleur, EAN, SKU, achat, vente) + composition/tags/pays, and local image
upload + camera capture (`<input type=file accept=image/* [capture]>`) that is
STAGED/preview-only — persistence needs an object-storage target that doesn't
exist yet, so it is deferred to the imagery/Photoroom phase (decided with Marc).

Import extraction now matches supplier categories onto the user-defined tree:
the extractor receives the boutique's category paths (« parent > enfant », built
best-effort in `import_runner._known_category_paths`) and is instructed to pick
an EXISTING leaf; a deterministic post-step canonicalizes the model's answer to
the tree's exact casing (confidence 1.0) and keeps unmatched labels verbatim.
This deliberately amends the earlier "extraction carries raw supplier facts
only; category mapping is a profile concern" stance, because the arborescence is
user-defined and matching at extraction is what Marc wants. Schema stays
union-free (category is still a plain string).

## 2026-07-09 (suite) — Enregistrement des images du panneau : direct vers Xano

Décision finalisée avec Marc : les images uploadées/capturées dans le panneau
sont enregistrées **directement dans le stockage Xano**, sans stockage objet
intermédiaire (ni Railway volume, ni R2). Marc a modifié l'endpoint Tillin
`product_image/{id}/bulk` pour accepter DEUX sources : `text[] image_urls`
(téléchargées/ré-hébergées via `storage.create_image` depuis l'URL) ET
`file[] files` (octets bruts uploadés, `storage.create_image` sur la ressource
fichier). Dans les deux cas `src` = URL hébergée par Xano.

Côté CatalogAI : `POST /products/{id}/images` (route FastAPI) reçoit les
UploadFile du navigateur et les refait suivre à Tillin en **multipart, champ
répété `files`** (le token Xano ne touche jamais le navigateur). Le client Xano
`_post_multipart` a été généralisé pour accepter une liste de tuples
`(field, (filename, bytes, content_type))` afin d'envoyer plusieurs fichiers
sous un même nom de champ sans les fusionner. Bouton « Enregistrer » dans le
panneau ; sur `created === 0` on garde les images en attente + toast d'erreur
(pas de faux succès).

Piège rencontré (mock ≠ réel) : le premier test live renvoyait `{images: []}`
pour tous les noms de champ — la branche fichiers de l'endpoint Xano échouait en
silence (try_catch → debug.log). Corrigé côté Xano (le `filename=""` était le
suspect). Validé end-to-end via l'UI CatalogAI par Marc.

## 2026-07-09 (suite) — Écriture du poids : PUT /product/weight (niveau produit)

Le writeback du poids d'enrichissement (en attente depuis Sprint B) est branché
sur l'endpoint Tillin fourni par Marc : **`PUT /product/weight`** (PAS POST —
POST /product/weight entre en collision avec une autre route et renvoie 400),
body `{product_ids:[…], weight_unit:"1", weight:N}`, codes d'unité 1=kg 2=g
3=lb 4=oz. L'endpoint est **au niveau produit** (un poids pour un lot de
produits), alors que le pipeline calcule un poids **par variante**. Convention
retenue avec Marc : toutes les variantes d'un produit partagent le même poids →
on prend **la 1re proposition sélectionnée**. Nos poids sont toujours en kg →
unité "1".

Implémentation : client `set_product_weight(product_ids, weight, weight_unit)`
(via un helper `_send_json(method, …)` généralisé pour supporter PUT en plus de
POST), câblé dans `xano_tillin.apply` là où le TODO était posé. Le piège
POST↔PUT n'a été révélé QUE par le test live (mock ≠ réel, encore) — d'où la
règle : toujours un appel réel avant de déclarer un writeback d'API externe
terminé. Validé live sur un produit test (poids écrit sur les 7 variantes),
valeur restaurée après.

## 2026-07-10 — Sprint imagerie : architecture de l'Image Processing Service

Specs consolidées dans plan.md (section « Sprint imagerie — Image Processing
Service ») à partir d'une réflexion d'architecture apportée par Marc, validée
puis amendée de trois réserves. Décisions durables :

- **API interne en verbes métier** (`normalize_product_image`,
  `generate_model_photo`, `generate_flat_photo` réservé) — les fournisseurs
  sont cachés derrière des adaptateurs interchangeables (anti-corruption
  layer). 1 interface + 1 implémentation par verbe ; PAS de moteur de routing
  multi-providers tant qu'il n'y a qu'un fournisseur par verbe.
- **Deux pipelines** : déterministe → **Photoroom** (~0,02 $/img) ; génératif
  → **FASHN `product-to-model`** (~0,04 $/img, priorité fidélité vêtement).
  FASHN supplante l'idée antérieure « Photoroom Virtual Model API ». Le code
  local (Pillow/CV) est un provider comme un autre.
- **Pas de nouveau broker** : la « file d'attente » = le job system existant
  (enrichment_job/item, queue Postgres SKIP LOCKED, BackgroundTask). Le
  volume cible (dizaines de milliers d'img/mois) tient largement dedans.
- **Module, pas microservice** : `backend/app/imaging/` ; l'« API interne
  stable » = les signatures Python des verbes. L'ACL rend une extraction
  future triviale — on ne la paie pas maintenant.
- **Stockage : pas d'object storage tiers.** Final = Xano (bulk
  `product_image/{id}/bulk`, branche fichiers, déjà validée) ; remplacement =
  `PUT /product_image/deactivate` (`product_image_ids: int[]`, créé par Marc
  le 2026-07-10 — le bulk ne fait qu'AJOUTER) ; staging = disque local
  éphémère `backend/var/imaging/`.
- **Traçabilité par asset** : provider + version modèle + seed, portée par la
  nouvelle table `image_asset` (qui sert aussi de suivi async pour les
  actions à la carte et d'audit — une seule table, trois usages).
- **Métrage au wrapper** : chaque appel Photoroom/FASHN émet des
  `usage_event` (provider photoroom/fashn, metric images/credits) — même
  pattern que Claude, aucun changement de schéma.
- **Cadrage (AskUserQuestion)** : Phase A = à la carte (panneau produit)
  d'abord — valide chaque verbe visuellement ; Phase B = batch dans le
  pipeline d'enrichissement (déterministe seulement ; le génératif reste à la
  carte).

## 2026-07-12 — Marque blanche, console admin, dashboard client, dette technique

Sprint post-audit UX (plan « logical-shimmying-squirrel », 9 commits
e885704→2e9b07d). Décisions durables :

- **Marque blanche par redaction SERVEUR, jamais par masquage UI.** Les
  clients ne doivent voir ni providers/modèles (claude, photoroom, fashn,
  firecrawl), ni coûts bruts, ni prix unitaires, ni le coefficient de
  facturation (la marge de l'opérateur). `/usage/summary`, `/usage/by-job`
  et `/usage/export` sont expurgés pour les non-admins (libellés de service
  neutres via `SERVICE_LABELS`, lignes FUSIONNÉES par service — même le
  nombre de modèles ne fuite pas) ; grille tarifaire, refreeze et timeseries
  par modèle/provider sont admin-only. Tout nouvel endpoint qui touche au
  coût DOIT passer par `redact`/`CurrentAdminDep`.
- **Rôle opérateur : `user.is_admin`** (migration 0016, promotion de
  marc.girard@tillin.fr incluse — table user LOCALE, pas Xano). Console
  `/admin` (clients, marge par compte, tarification) sous `RequireAdmin`
  frontend + `CurrentAdminDep` backend. Le PUT client des réglages de compte
  préserve les champs opérateur (`ADMIN_ONLY_SETTINGS`).
- **« Temps gagné »** : AccountSettings.minutes_saved_per_import_product
  (défaut 2) / minutes_saved_per_enriched_product (défaut 10), modifiables
  uniquement par l'admin ; le dashboard client affiche
  minutes_saved_this_month calculé côté serveur (DashboardStats).
- **Pas d'enrichissement avant transfert** (décision Marc 2026-07-11) : le
  stockage final des images est Xano, un produit doit exister. Seule
  exception actée : les transformations TEXTE bakées dans le CSV par le
  profil d'import (modèle de titre déjà livré) — extension possible plus
  tard, pas maintenant.
- **Contrats typés de bout en bout** : ImportItemPublic.payload et
  ImportItemUpdate.payload sont typés ImportedProduct (plus de dict[str,Any])
  → le client OpenAPI généré porte la vraie forme ; src/lib/api/* sont des
  ADAPTATEURS fins du client généré (aucun type API recopié à la main ; seuls
  raffinements : rendre requis les champs à default serveur). Multipart et
  blobs restent des appels bruts.
- **Sélections en masse = endpoints bulk atomiques** (PATCH
  /imports/{id}/items), jamais N requêtes côté client.
- **TanStack Query v6** est le pattern data-fetching cible (cache, polling
  par refetchInterval conditionnel, invalidations par préfixe de clé) —
  adopté sur les listes + détails du pipeline, à étendre aux écrans restants
  au fil de l'eau. Les compteurs affichés viennent TOUJOURS du serveur
  (job.counts, DashboardStats), jamais d'une page paginée.

## 2026-07-12 — Sprint imagerie configurable

- **Normalisation = segment + Pillow local** : Photoroom `/v1/segment`
  (0,02 $/image, seule étape facturée, modèle usage `photoroom-segment-v1`)
  fournit le cutout RGBA ; TOUTE la géométrie (fond hex, ratio, centrage
  bbox alpha seuil 8, offset/échelle, compression max_kb) est du Pillow
  maison (`app/imaging/compose.py`). `/v2/edit` (0,10 $) supprimé. Ombre
  produit écartée (imposerait l'API d'édition) — repensée comme génération
  FASHN future.
- **Le cutout et la source restent en staging** jusqu'au save : le
  repositionnement (`POST /imaging/assets/{id}/render`) recompose localement
  sans jamais re-payer le provider. `staged_files_json` porte rôle + octets +
  dimensions par fichier (assets legacy lus en repli sur staged_paths_json).
- **Toute opération d'image longue = 202 + BackgroundTask + polling**
  (normalize aligné sur generate-model) ; le re-render local reste synchrone.
- **Défauts d'imagerie par client dans AccountSettings** (`imaging_*`,
  éditables par le client, PAS admin-only) ; fusion défauts → champs
  explicitement envoyés (`exclude_unset`) → overrides config de job.
- **Nom d'image** : priorité nom saisi > modèle `image_title_template`
  (tokens {reference}/{color}/{position}/{brand}/{title}, rendu via le moteur
  de titre produit puis TOUJOURS slugifié — pas de casse pour un fichier) >
  défaut technique ; le rendu de nom ne fait jamais échouer un apply.
- **Filigrane sandbox Photoroom** (RÉSOLU 2026-07-15, clé prod en place) :
  tuilé semi-transparent, il polluait la bbox de centrage en dessous du seuil
  alpha — les validations visuelles sandbox étaient donc approximatives, sur
  le rendu ET sur le cadrage. Vérifié live avec la clé prod : sortie propre,
  centrage correct. Leçon : sur un provider d'image, une validation visuelle
  en sandbox ne vaut que pour la plomberie, jamais pour le rendu final.

## 2026-07-12 — Sprint chantiers app (soir)

- **Notifications e-mail (Brevo) abandonnées** au profit de **pastilles
  d'état sur les menus Imports/Enrichissements** : AppShell interroge
  /stats/dashboard toutes les 30 s (TanStack Query, cache partagé avec le
  dashboard — même queryKey ["stats","dashboard"]) ; une seule pastille par
  menu, priorité échec (rouge) > à vérifier (ambre) > en cours (pulsation).
  Le client Brevo (app/clients/brevo.py) reste en place mais rien ne l'appelle.
- **Retry 429 Anthropic via le SDK, pas de code maison** : `max_retries=5`
  sur anthropic.Anthropic (backoff exponentiel natif, honore Retry-After).
  Constante partagée `app/clients/claude.py::MAX_RETRIES`, réutilisée par
  l'extracteur d'imports.
- **Composants ui/ : primitives natives stylées, pas de lib headless** —
  select = <select> natif stylé (cn + classes de l'Input), tabs = TabBar
  (barre sobre role=tablist, panneaux à la charge de la page), switch =
  bouton role=switch (labellisable via <label for>), empty-state (message +
  action), confirm-button (armement destructif + retombée auto). Règle
  d'adoption : on ne convertit PAS un usage dont le rendu/les interactions
  divergent du composant (état vide avec icône, rejet de review couplé aux
  raccourcis clavier).
- **TanStack Query = pattern unique pour toute lecture serveur** :
  createQuery(() => ({...})) (options-fonction, réactivité Svelte 5), tous
  les paramètres dans la queryKey, mutations impératives + invalidateQueries,
  keepPreviousData pour les tables paginées/filtrées, formulaires = copie
  locale $state hydratée une fois depuis query.data (jamais de bind sur le
  cache). L'état de travail (studio images, sélections) reste du $state local.

## 2026-07-15 — Modèle crédits prépayés

- **Business model client = crédits prépayés, marge admin inchangée en €** :
  1 crédit = 0,10 € de valeur faciale ; le client voit un solde et une grille
  par action, jamais les coûts € (sauf le prix des packs). Toute la mécanique
  usage_event/grille €/coefficient/figement mensuel reste la vue marge de
  l'opérateur — les deux systèmes coexistent sans se toucher.
- **Grille par action (défauts, admin-only dans AccountSettings)** : produit
  importé 1, fiche enrichie 2, image traitée 1 (re-render gratuit), visuel
  généré 5 → fiche type 8 crédits = 0,80 € hors génération (cible Marc,
  marge ≈ ×5 sur les coûts réels mesurés).
- **Débit de la fiche AU TRAITEMENT** (passage « À vérifier » dans
  complete_item), jamais sur fail_item — décision Marc : on facture le
  travail produit, pas le résultat de la review.
- **Blocage 402 AVANT toute écriture** sur les routes de lancement
  (insufficient_credits) ; pas de blocage en cours de job — un batch peut
  finir légèrement négatif (standard prépayé). Côté client : toast explicite,
  boutons jamais désactivés (le serveur est la source de vérité).
- **Allocation d'abonnement paresseuse** (monthly_free_credits) : octroyée à
  la première lecture du solde du mois, idempotente par `period` YYYY-MM —
  même philosophie que le figement mensuel, pas de scheduler. Elle commit
  immédiatement (fait d'abonnement, indépendant de la requête déclencheuse).
- **consume() ne commit pas** (le caller possède la transaction, comme
  record_usage) ; ledger append-only, les actions gratuites (coût 0) et les
  re-renders n'écrivent RIEN (le ledger ne porte que des mouvements).
- **Achats de packs saisis manuellement par l'admin** (POST grant, credits
  signés + price_eur) — pas de Stripe dans ce périmètre.
- **Tests de routes : float de crédits par défaut** (conftest
  tests/api/routes, 1M de crédits sur le compte default, test_credits.py
  opt-out) — sinon les gardes 402 cassent tous les tests de lancement.

## 2026-07-16 — Multi-entreprises (SaaS) : tenancy par token utilisateur

Catalog est un SaaS multi-entreprises sur UNE instance. Décisions :

1. **Le scoping des données catalogue est délégué à Xano.** Chaque appel
   catalogue porte le token du user connecté (capturé au login, TTL 72 h,
   stocké sur `user.xano_token`) : Xano restreint à SA company. Nos filtres
   `account_id` scopent les données CatalogAI (jobs, crédits, réglages) ;
   Xano scope le catalogue. Un compte CatalogAI = une company Xano
   (`account.xano_company_id`, résolu via /auth/me au login).
2. **Jamais de repli service pour un compte d'entreprise.** Token absent ou
   expiré → 401 `xano_token_expired` (l'UI renvoie au login). Le repli sur
   l'identité de service n'existe QUE pour le compte default (opérateur/dev,
   sans company) — sinon on servirait le catalogue d'une autre entreprise.
3. **Jobs de fond au token le plus frais du compte** (n'importe quel user de
   la company convient, Xano scope par le token) : résolu à chaque lecture,
   la file étant partagée entre tenants.
4. **L'offre (modules) vit dans CatalogAI, pas dans la table company de
   Xano** : c'est la même décision commerciale que les crédits/packs — une
   seule source de vérité, éditable depuis la console admin sans migration
   Xano. `feature_import/enrich/studio` dans AccountSettings (admin-only),
   gardes 403 `feature_disabled` par router ; `role`/`permissions` Xano
   restent réservés aux droits PAR UTILISATEUR (plus tard).
5. **Frontières des modules** : l'upload d'images produit et la recherche
   catalogue sont du socle (pas de crédit, pas de provider) ; la
   normalisation d'images du review appartient à l'enrichissement, pas au
   studio.
