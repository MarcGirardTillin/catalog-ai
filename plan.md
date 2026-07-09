# Product Enrichment App — standalone, off-Xano

## Context

Tillin's multi-brand fashion retailers need to enrich batches of products (description, meta description, images, title, variant weights) by pulling official content from each **brand's own e-commerce site** (mostly Shopify), generating copy with an LLM, and processing images (background recolor + resize to **4:5** + format). Today a similar pipeline runs *inside Xano* one product at a time — but Xano already has performance issues, so we are **building a separate standalone app on its own infrastructure**. Xano keeps its existing role as catalog master and is touched only for **cheap final writes** (approved results), which then sync to Shopify via Tillin's existing integration.

This is a **new project, separate from the Xano repo** (new Git repository, e.g. `tillin-enrichment-app`). Only a few small XanoScript additions are needed for writeback glue (delegated to the Xano agents); the bulk is a normal web app.

### Locked decisions
- **Stack:** SvelteKit frontend + **FastAPI (Python)** backend + background worker + **Postgres**.
- **Hosting:** Managed PaaS — **Railway or Render** (web service + worker service + Postgres in one place).
- **Database:** Postgres on the same PaaS (app's own state; nothing extra on Xano).
- **Scraping:** **Shopify JSON first → Firecrawl fallback**, with a **manual method override per run and per product** (some Shopify pages hold data outside the JSON; sometimes go straight to Firecrawl). Pluggable fetcher so a heavy anti-bot backend can be added.
- **Anti-bot backend:** **Bright Data Web Unlocker** (chosen over Zyte) for WAF-protected sites like Farfetch / Asics — **deferred to a later phase/task**. Start with Shopify JSON + Firecrawl; the fetcher interface is built from day one so Web Unlocker plugs in without rework.
- **Images:** **Photoroom API** (bg removal + bg color + pad to **4:5** + format/quality in one call).
  - **Product-panel image tools (user-requested 2026-07-09, NOT built yet):** the product side panel (see IA section) reserves a disabled "Images (Photoroom)" section. Planned actions, per image: détourage (cutout), reformatage/redimensionnement (ratio/size presets), and generative: produit porté par un mannequin à partir d'un packshot à plat, et l'inverse (à plat depuis une photo portée). Every Photoroom call will be metered through `usage_event` like Claude calls (wrapper-level).
- **Copy:** **Claude** default (`claude-sonnet-4-6`), provider switch to OpenAI; configurable per job/brand.
- **Transforms (all):** description+meta, images (bg+recolor+resize 4:5), **title by template**, **image filename by template**, **variant weights on existing products**.
- **Write mode:** stage → **review queue** → approve → apply to Tillin (Xano) → Tillin syncs to Shopify.
- **Selection:** a list of product IDs **or** a tag.
- **Async, fire-and-forget:** you launch a job and **leave** — processing runs server-side on the worker, independent of the browser. You come back later (the job survives a closed tab / logout) and review staged results when they're ready. Optional **notification when the job finishes** (email/in-app).

> Per saved feedback for the Xano side: never auto-push (user does Ctrl+S + manual push), `enforce_hidden_fields = true` on every `db.add`/`db.edit`.

---

## Architecture

```
SvelteKit app (Railway/Render)        FastAPI backend + worker (Railway/Render)         External / Xano
──────────────────────────────        ─────────────────────────────────────────        ─────────────────
/jobs/new  select IDs|tag  ─POST─▶  POST /jobs  → create job + enqueue items (app Postgres)
/jobs/[id] progress        ◀GET───  worker loop (concurrency + rate limit + retry):
/jobs/[id]/review                     1. resolve_source_url(product, method)  ───────▶  Shopify .json / suggest.json
  before/after, approve    ─POST─▶                                                        Firecrawl (fallback / full page)
                                      2. generate_copy(provider, model)        ───────▶  Claude / OpenAI
                                      3. process_image(bg, 4:5, fmt)            ───────▶  Photoroom  → store to object storage
                                      4. apply_title_template / map_weights
                                      5. stage result on enrichment_item (ready_for_review)
  approve item            ─POST─▶  POST /items/{id}/approve  ──────────────────────────▶  Xano: write desc/meta/title/
                                                                                           weights/images (cheap)
                                                                                           → Tillin syncs to Shopify
```

All API keys (Firecrawl, Photoroom, Anthropic/OpenAI, Xano token, Bright Data) live **server-side in FastAPI**. The browser only talks to the backend.

### Async lifecycle (core requirement)
The pipeline is **fully asynchronous** — you do not wait on it:
1. `POST /jobs` returns **immediately** with a `job_id` after enqueuing items (status `pending`). The UI navigates to a job page; you can close the tab.
2. A **separate worker service** drains the queue on its own schedule (concurrency cap + per-host rate limit + retry). It keeps running whether or not anyone is connected.
3. Each finished item flips to `ready_for_review` with its staged result persisted in Postgres. The job moves `pending → processing → completed/partial`.
4. You return **any time later**, open `/jobs/[id]/review`, and approve/edit/reject staged results. Approval is itself fast and independent per item.
5. Optional **"notify when done"** (email or in-app badge) so you don't have to poll manually.

Because state lives in the app's Postgres (not the browser, not Xano), jobs are durable across logouts, restarts, and deploys, and can be resumed.

---

## Backend (FastAPI) — modules

- **`xano_client.py`** — Tillin REST API wrapper (service token).
  - Read: products by tag or ID list with fields the pipeline needs (title, brand + `brand.website_url`, `product_reference_code`, variants[sku, barcode, weight, weight_unit], images, season, category, department). Reuse existing `products_with_pagination*` endpoints where possible.
  - Write (approve): description+meta via existing `apis/.../3176_product_product_id_enrich_POST.xs`; **title** + **variant weights** via thin new endpoints (see Xano section); images via attach-from-URL endpoint.
- **`sources/`** — pluggable fetchers behind one interface `fetch_source(url|reference, method)`:
  - `shopify_json.py` — `/products/{handle}.json`; `/search/suggest.json` matcher + scoring **ported from** `functions/ai_process_image_feature/1079_import_single_shopify_product.xs` (SKU exact/contains, title, handle, tags).
  - `firecrawl.py` — scrape + `/extract` (LLM-structured) for full product pages / non-Shopify / data outside the JSON.
  - `unlocker.py` — **Bright Data Web Unlocker** (added in Phase 3, deferred task; interface ready now).
  - `resolver.py` — `resolve_source_url(product, website_urls[], method=auto|shopify_json|firecrawl|unlocker)` → `{url, score, method_used, candidates}` or skip-with-reason.

#### Product matching — how a Tillin product is found on the brand site (core)
Chain: **brand → site(s) → search → fetch candidates → score → confidence gate → human fallback.**
1. **Source site(s):** `product.brand_id` → `brand.website_urls` (one **or more** — a brand may sell across several stores/domains), **plus** any extra URLs the user supplies at the job level or per product. The resolver searches **all** provided URLs and aggregates candidates. No URL anywhere → skip with reason (or user pastes one in review).
2. **Search by identifier (in priority order):** query each site with `GET {site}/search/suggest.json?q={barcode}` then `{reference}` then `{title}` (`&resources[type]=product&resources[options][fields]=variants.sku`); HTML `/search?q=` fallback; Firecrawl search-page extraction for non-Shopify. **Do not use Tillin's SKU** — it is Tillin-generated and will not match the brand's SKU.
3. **Fetch candidates:** `{site}/products/{handle}.json` for each candidate across all sites.
4. **Score each candidate** and keep the global best above a confidence threshold. Identifier priority:
   1. **Variant barcode / EAN / UPC exact** — manufacturer code shared across catalogs; most reliable primary key.
   2. **Tillin `product_reference_code`** — match against the brand's variant SKU / handle / title / tags (exact → contains).
   3. **Product title + color** — fuzzy similarity tie-breaker.
   - Tillin SKU is **excluded**. This replaces the existing `1079` scorer's SKU-first logic (which assumed matching SKUs) and **adds barcode + reference + title/color** — the biggest reliability win for a multi-brand catalog.
5. **Confidence gate:** strong match (esp. barcode) → auto-stage; ambiguous/low → `needs_manual`, with top candidates from all sites surfaced in the review queue for the user to pick or paste the correct URL; early-exit on near-perfect match.

Port the `suggest.json` + `scoreProductMatch` logic from `functions/ai_process_image_feature/1079_import_single_shopify_product.xs` to Python, **re-rank to barcode → reference → title+color (drop Tillin SKU)**, and search across multiple URLs. Requires reading each variant's `barcode` + the product's `product_reference_code` from Xano (already in scope).
- **`enrich/`** — pipeline steps:
  - `copy.py` — `generate_copy(provider, model, product_ctx, editorial_instructions, translate)` → `{description_fr, meta_description_fr}` (Anthropic SDK / OpenAI SDK). Verify request shape via the `claude-api` skill.
  - `images.py` — `process_image(src, bg_color, ratio="4:5", long_edge, fmt, quality, padding, alignment, center_offset?)` via Photoroom → bytes → store to **object storage** (Cloudflare R2 / S3 / PaaS volume) → durable URL. Filename from `filename_template` (`{reference}_{color}_{position}`).
    - **Auto-centering (default):** Photoroom cuts out the subject and **centers it by default**; we set `outputSize` to the 4:5 target (e.g. `1600x2000`), `padding` (~`"10%"`), `backgroundColor`, and `horizontalAlignment` → consistent centered product shots with uniform margins across the catalog.
    - **Off-center detection (QA flag):** from the returned cutout's alpha, `Pillow.getbbox()` → compare subject-bbox center to frame center; if offset > threshold, badge the item `off_center` in the review queue.
    - **Manual recenter (exceptions):** request the **transparent cutout** from Photoroom and **composite in Python (Pillow)** at a user-supplied `center_offset` on the 4:5 canvas → pixel-perfect, deterministic. Triggered from the review UI when auto-centering isn't right.
    - **Output format/weight:** format preference **WebP > JPEG > PNG (no AVIF)**. Store a **WebP master** (q≈80) at 1600×2000, **capped ~200 KB** (step quality down to hit `max_kb`); JPEG fallback; PNG only if transparency is ever needed. Note: Shopify's CDN re-encodes (WebP) + resizes on the fly, so the stored format mainly matters for Tillin's own (POS/Bubble) display.
    - **Per-category consistent sizing (deferred enhancement):** optional per-category **fill ratio** (target % of frame the subject occupies, via Photoroom `padding`/`outputSize`), keyed off the product's category, so products within a category share scale/proportion. Feasible and low-cost but adds a per-category config + tuning UI → **not Phase 1**.
  - `title.py` — `apply_title_template(product, template)` tokens `{brand}{title}{season}{reference}{color}{category}{department}`.
  - `weights.py` — match Tillin variants to source variants by SKU then barcode; convert weight (kg/g/lb/oz) — port `toKg` from `1079`.
- **`jobs/`** — `enrichment_job` + `enrichment_item` tables (app Postgres) and the worker.
  - Worker: **DB-backed queue** (poll `enrichment_item` where `status=pending`), async concurrency cap, **per-host rate limiting**, retry with backoff (`tenacity`), `attempt_count` max 3 → `failed`. Runs as a separate PaaS worker service. (Upgrade path: ARQ+Redis if volume grows — Railway/Render add Redis trivially.)
- **`api/`** — routes: `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, `GET /items/{id}`, `PATCH /items/{id}` (edit staged), `POST /items/{id}/approve`, `POST /items/{id}/reject`, `POST /jobs/{id}/apply_approved`, `GET /products` (proxy to Xano for selection), `GET/PUT /brands` (manage `website_url`). Auth: simple app login (or proxy Xano user auth).

### App data model (Postgres)
- `enrichment_job(id, status, selection_json, config_json, counts, created_at)`.
- `enrichment_item(id, job_id, tillin_product_id, status, source_url, source_method, match_score, staged_title, staged_description, staged_meta, staged_images_json[urls], staged_weights_json, error, attempt_count, timestamps)`.
- `config_json`: transforms toggles; `title_template`; `filename_template`; image `{bg_color, ratio:"4:5", long_edge:2000, format:"webp" (fallback "jpeg"), quality:80, max_kb:200, padding, alignment, pad_strategy:"contain_pad"}`; ai `{provider, model, editorial_instructions, translate}`; scrape `{default_method, per_product_overrides}`; source `{extra_website_urls[], per_product_url_override}` (user-supplied search sites in addition to `brand.website_urls`).

---

## Frontend (SvelteKit) — routes
- `/login`
- `/jobs/new` — select products (paste IDs or pick a tag via `/products`), config form (transform toggles, title template, filename template, bg color, resize 4:5 target, AI provider/model, editorial instructions, translate, **default scrape method**, **extra search URLs** to add to the brands' own `website_urls`), launch.
- `/jobs/[id]` — progress (poll job status + counts).
- `/jobs/[id]/review` — per item: **before/after** for description, meta, title; original vs Photoroom image thumbnails; proposed weights; source URL + match score + **method used**, with a **"re-run with method X"** control (shopify_json / firecrawl / unlocker); approve / edit / reject; **Apply approved**. Per image: `off_center` badge when flagged, alignment + padding nudge, and a **"set center" pinpoint** that re-composites the cutout (Pillow) at the clicked anchor.
- `/settings/brands` — set/edit one or more `brand.website_urls` per brand (writes to Xano).

Talks only to FastAPI. Lightweight; no heavy client deps.

---

## Xano-side additions (minimal — delegated to Xano agents)
Cheap glue only; no pipeline compute on Xano:
- **`brand.website_urls`** (text **array**, Table Designer) — one *or more* source sites per brand (a brand may sell across several stores/domains) + expose in brand GET/`295_brand_POST`. The app searches all of them, plus any extra URLs the user supplies per job or per product.
- Thin **`POST product/{id}/attach_images_from_urls`** — wraps existing `functions/ai_process_image_feature/2040_import_images_from_urls.xs` (it already does `storage.create_image` from a URL + `db.add product_image`). App uploads Photoroom output to object storage, passes those URLs here to register Tillin `product_image` rows; returns IDs for the enrich call.
- Thin **`POST product/{id}/set_variant_weights`** — accepts `[{variant_id|sku, weight, weight_unit}]`, `db.edit product_variant` (`enforce_hidden_fields = true`). (No existing endpoint writes variant weight.)
- Confirm the product update path accepts **title**; if not, add a thin title-update endpoint. Reuse `3176 enrich` for description+meta.
- Provision a **Xano API token / service user** for the app.

---

## Phasing
- **Phase 0 — skeleton:** repo + SvelteKit + FastAPI deployed on Railway/Render with Postgres; `xano_client` reads products by tag; login. Proves the read path.
- **Phase 1 — pipeline correctness (run on one product):** Shopify JSON match by reference → Claude copy → Photoroom 4:5 image → title template → weight mapping → stage → review UI → approve → write back to Xano (desc/meta/title/weights/images). Validates every transform on a single product before scaling.
- **Phase 2 — async batch (the real UX):** job/item queue + separate **worker service** so you launch a job, leave, and come back to review. Concurrency + rate limit + retry, progress page, apply-approved, optional notify-when-done.
- **Phase 3 — robust scraping (deferred task):** Firecrawl fallback + manual method override + full-page LLM extraction; for WAF sites (Farfetch/Asics) plug in **Bright Data Web Unlocker** via the ready-made `unlocker.py` interface.
- **Phase 4 — polish:** brand `website_urls` settings UI, optional direct Shopify push, run history + per-provider cost tracking.
- **Steerable generation sprint ("Sprint B") — SHIPPED 2026-07-08:** move the account "Enrichissement" defaults out of the Paramètres page into their **own settings tab/section**, built around an **instruction library**: as many named editorial instructions/prompts as the user wants (CRUD + per-category defaults), selectable at job creation (or free-text one-off), instead of the single `editorial_instructions` default shipped 2026-07-08. Same tab hosts the per-client context (.md rules per boutique, à la L'Espion/Bambinoh), per-item extra source URLs + SEO keywords, and the title-template builder (clickable tokens + separator — the builder itself shipped early on the Paramètres page and moves here with the rest). Delivered: `instruction_template` table + /instructions CRUD, job-creation snapshot (`instruction_id` → editorial_instructions, per-category defaults via `category_instructions`), `client_context` account setting prefixed to the copy prompt, `seo_keywords` + `extra_website_urls` job config keys, parameterized `meta_max_length` (review counter reads it too), Paramètres tabs (Préférences / Enrichissement / Compte) with the instruction library UI and a shared JobOptionsPanel at job creation. Still open from this scope: per-ITEM source URLs/keywords overrides in review (job-level shipped; per-item manual URL resolution already existed) and the image dedupe guard to make `applied` items retryable.
- **Import sprint (parallel track):** supplier file (PDF/Excel/CSV) → analyze → create products in Tillin — see the dedicated section below; can run alongside Phases 2–4 once the platform pieces (jobs/review/writeback) exist.
- **Information architecture — SHIPPED 2026-07-09 (user-validated decisions):** the sidebar now tells the pipeline story: section **Pipeline** (Tableau de bord, Imports, Produits, Enrichissements — ex-« Jobs ») and section **Configuration** (Profils d'import, Instructions — ex-« Enrichissement », Consommation), Paramètres at the bottom; URLs unchanged. Harmonized status wording everywhere: « À vérifier » (ready_for_review), « Écarter/Écarté » (rejected — replaces both « Rejeter » and « Exclure »), final state stays contextual (« Transféré » for imports = creation, « Appliqué » for enrichments = update). Products page has two tabs: **Catalogue** (Tillin search + filters) and **Par import** (an import's products, isolated — resolved to Tillin by reference_code via POST /imports/{id}/link-products since /product_import returns no ids; stored on import_item.tillin_product_id, migration 0014). Product **side panel** (ProductPanel) on row click in both tabs: two completeness scores — « Prêt boutique » (titre, réf, ≥1 variante, prix, catégorie, marque) and « Prêt e-commerce » (≥1 image, description, meta, poids) + non-blocking « titre harmonisé » indicator — plus images gallery and « Enrichir ce produit ». Bridge from a transferred import: « Voir les produits créés » / « Enrichir les produits créés ». Dashboard gained « Imports à vérifier ». Orphan /jobs/new removed.
- **Current priority order (user decision 2026-07-09):** 1. Usage metering M2/M3 (Consommation UI + pricing) and Enrichment workspace — both IN PROGRESS; 2. infra/prod items; 3. LAST: import I3 direct Xano creation (the /product_import CSV transfer covers the need for now — keep the I3 checkpoints/reminders when it comes up).
- **Enrichment workspace sprint (user-requested 2026-07-09, IN PROGRESS):** Marc finds the « Enrichissement » settings tab too big for a settings page — it is a feature, not a preference, especially once multiple named instruction sets are in daily use. When we work on it: promote it out of Paramètres into its **own sidebar section** (like Imports/Produits), likely an "Enrichissement" or "Instructions" workspace: the instruction library as a first-class list page (30+ instructions must stay manageable: search, per-category defaults visible at a glance), the boutique context (.md) and title-template builder as sub-pages or panels, and room for the coming per-item overrides + versioning of instructions. Settings keeps only true preferences (density, dark mode, account). Mirror the pattern chosen for import profiles (dedicated page + inline editing from the place where it's used). No code yet — design pass first with Marc.

---

## Import sprint — supplier file → product creation in Tillin (dedicated sprint)

A second product line **upstream** of enrichment: instead of enriching products that already exist in Tillin, the user uploads a **supplier file** (order PDF, Excel, or CSV), the app analyzes it, and **creates** the products in Tillin. This automates the manual workflows already done for the **L'Espion** and **Bambinoh** boutiques (supplier PDF/Excel → Tillin import CSV), and chains naturally into enrichment afterwards (import creates the products; an enrichment job completes them).

It is a **dedicated sprint**, not Phase 5 of enrichment: it has its own pipeline (parse → normalize → stage), its own domain (per-boutique/supplier conventions), and only shares the platform (jobs/worker/review/writeback). It can be built **in parallel** with the remaining enrichment phases.

### Flow

```
/imports/new  upload file + pick boutique/supplier profile
   → POST /imports  (job type "import", file stored to object storage)
   → worker: 1. parse file        (pdf → text/tables via LLM; xlsx/csv → rows)
             2. extract products  (LLM-structured → normalized product schema)
             3. apply profile     (pricing rule, brand rule, category mapping, season…)
             4. stage import_item (ready_for_review, with per-field confidence)
   → /imports/[id]/review  edit/approve/reject per product (spreadsheet-like grid)
   → apply approved → destination port:
        a) MVP: generate the Tillin import CSV (download / hand to existing import)
        b) later: create directly via Xano API (products + variants + barcodes)
```

### Backend modules (reuses the existing skeleton)

- **`imports/`** — new package, sibling of `enrich/`:
  - `parsers/` — one parser per file family behind `parse_file(bytes, mime) -> RawDocument`:
    - `pdf.py` — supplier order PDFs. Extraction via **Claude with document/vision input** (PDFs are heterogeneous per supplier; deterministic table extraction is the fallback, LLM is the default).
      - **Cheaper-extraction alternatives (bonus, post-v1 — decided 2026-07-09):** v1 ships Claude doc/vision ONLY, with no extraction-strategy abstraction beyond the existing `parse_file(bytes, mime)` seam. After real usage, the metering brick's `GET /usage/by-job` gives actual per-file token costs; if they warrant it, cheaper paths slot in behind the same seam (text-layer extraction + a smaller model for born-digital PDFs, deterministic table extraction per recurring supplier format, Haiku for simple column-mapping on tabular files). Do NOT pre-build a strategy/plugin system for this.
    - `tabular.py` — Excel (`openpyxl`) + CSV; header detection and column mapping are LLM-assisted, values are read deterministically from the rows (prices/EANs must never be hallucinated).
  - `extract.py` — LLM-structured extraction to a **normalized product schema**: `{supplier_ref, ean/barcode, title, color, sizes[], qty, wholesale_price, retail_price?, category?, brand?}` with a per-field `confidence`. Numeric/EAN fields are cross-checked against the raw cells (no generated values).
    - **Schema decision (2026-07-09):** the internal schema is a **clean model informed by Tillin's product data design** (product / variant / barcode, as already mapped by `clients/xano.py`) — NOT the Tillin import CSV template. The template is a flat, lossy destination format; the internal schema must also carry review-only data (confidence, wholesale price, ordered qty, raw supplier ref). Two constraints lock it: it must render **losslessly to the Tillin import CSV** (I2 path) and map cleanly to the Xano product entities (I3 path). Freeze it in the main thread at sprint start by confronting the import template + the Xano product model + the real fixture files below.
    - **Tillin product data model (reference):** XanoScript table definitions live in `tables_xano/` (one file per table, prefixed by Xano table id). Semantics confirmed by Marc (2026-07-09):
      - Import CSV = one row per variant, product grouped by `reference_code`; **color is a product option** (option1 Couleur, option2 Taille) — the "new color, same reference" case adds variants + an option value to an existing product.
      - `weight_unit` enum: 1=kg, 2=g, 3=lb, 4=oz.
      - `product.title` is the main display field; at creation fill BOTH `title` and `title_label` with the same value.
      - CSV `gender` (Homme/Femme/Unisexe) is matched to the `department` table inside the Xano import workflow.
      - Category path `A > B > C` fills BOTH `category_id` (first category of the path) and `category_ids[]` (every category of the path).
      - Do NOT fill `supplier_product_reference_code`.
      - The CSV importer creates the `price` rows itself and fills the variant's denormalized decimals from `price`/`wholesale_price`/`tax_rate` — direct creation (I3) must replicate this (checkpoint discussion).
    - **Why not just the CSV template (trade-off, discussed 2026-07-09):** normalizing on the CSV would be simpler to wire (the existing Tillin import path needs zero Xano API work) — but that import path is slow (~5 min per 250-variant file) and the CSV can't carry review metadata. Decoupling the internal schema from both destinations means the SAME extraction feeds the CSV path (I2, ships immediately, no Xano work) and later the fast direct-creation path (I3, once the Xano bulk API is reworked) — no re-extraction, just a second destination adapter. The 5-min cost lives in Xano's import processing, not in our file analysis; I3 is the fix for it.
  - `profiles.py` — **boutique/supplier convention profiles**, data-driven (DB table + seed), one per (boutique, supplier):
    - pricing rule: e.g. L'Espion = round-up-to-nearest-5 of `wholesale × coefficient`; Garcia/Bambinoh = use `retailPrice` as-is
    - brand rule: fixed brand, or derived (Bambinoh: from supplier folder name, no uppercase)
    - category mapping: supplier label → Tillin category list; **leave empty when not deducible** (never guess)
    - season, VAT, and any boutique defaults
  - `csv_out.py` — render approved items to the **Tillin import CSV** format (the proven path used manually today).
- **`jobs/`** — reuse `queue.py`/`runner.py` with a job `type` (`enrichment` | `import`); new `import_item` staging table mirroring `enrichment_item`.
- **`destinations/`** — the existing port gains a `create_products` capability on the Tillin adapter (phase b); phase a ships with the CSV renderer only.
- **`api/`** — `POST /imports` (multipart upload), `GET /imports/{id}`, `PATCH /import_items/{id}`, approve/reject, `GET /imports/{id}/csv`, `GET/PUT /import_profiles`.

### Frontend (SvelteKit)
- `/imports/new` — file dropzone + boutique/supplier profile picker + option overrides (coefficient, season…).
- `/imports/[id]` — progress (same pattern as jobs).
- `/imports/[id]/review` — editable grid of extracted products (title, EAN, sizes/qty, computed retail price, category, brand) with per-field confidence highlighting; approve/reject; **Download Tillin CSV** / (later) **Create in Tillin**.
- `/settings/import-profiles` — manage convention profiles.

### Import sprint phasing
- **I1 — parse & extract — SHIPPED 2026-07-09:** upload → worker parses PDF/Excel/CSV → normalized products staged (with usage metering M1 wired in). Validated live: LTDC Excel → 19 products / 184 variants / 184 EANs cross-check-verified; L'Espion PDF (Paul Smith) → 36 products / 88 variants via Claude doc/vision. Real fixtures live in `everyday-tasks/` (user-provided, 2026-07-09):
  - `everyday-tasks/integration LEspion/pdfs traites/Confirmation12610566.pdf` (L'Espion order PDF)
  - `everyday-tasks/integration LEspion/pdfs traites/ORDER_PJLESPION--EURL-SAMANTA_2026-02-04_19026798.pdf` (L'Espion order PDF, larger)
  - `everyday-tasks/integration LEspion/pdfs traites/2026-06-30-19037114-Y-s.xlsx` (L'Espion Excel)
  - `everyday-tasks/integration Bambinoh/Le Temps Des Cerises/Commande BAMB3201 - 02359226.xlsx` (Bambinoh supplier Excel)
- **I2 — profiles & review — SHIPPED 2026-07-09:** convention profiles (data-driven per account/supplier: price retail-as-is or wholesale×coefficient rounded UP to `round_up_to`, barcode EAN or constructed REF-COLOR-SIZE, brand as-extracted/fixed, supplier/season labels, gender/category defaults, tax_rate, status), editable review grid (PATCH item payload validated against ImportedProduct + exclude/restore), Tillin import CSV rendered by ONE engine (`app/imports/tillin_csv.py`, 30 columns frozen against the real everyday-tasks files) feeding preview (`GET /rows`), download (`GET /csv`) and **direct transfer** (`POST /transfer` → Xano `POST /product_import`, multipart `file_import` + `location_id`; locations from `get_all_informations` minus third-party origins). Items become `applied` after transfer; CSV download kept as backup path. `import_profile` table = migration 0011.
  - **Transfer validated LIVE 2026-07-09**: Marc confirmed a real `POST /product_import` succeeded from the app (after fixing `list_locations` — `origin` is an object, filter on `origin.third_party`).
- **I3 — direct creation — DEPRIORITIZED to the END of the plan (user decision 2026-07-09, after the CSV transfer path proved sufficient):** `create_products` on the Xano destination adapter (products + variants + EANs), duplicate detection against the existing Tillin catalog at **two levels** (semantics confirmed by Marc, 2026-07-09):
  - **EAN/barcode → variant-level check** (this exact variant already exists in Tillin)
  - **`product_reference_code` → product-level check** (the parent product already exists)
  - Either match → flag, don't recreate; surface the conflicting Tillin product/variant in review.
  - **Edge case — new color on an existing reference:** same `product_reference_code`, new color → the product exists but the incoming variants are new. When importing that into Tillin, the write must ADD the new color's variants and must NOT delete/replace the product's other colors. The safe write path is primarily a **Xano-side concern** (how the creation/update endpoint merges variants), but CatalogAI should detect the case and show an explicit indication in the review grid ("référence existante — ajout de coloris"). ⚠️ **REMIND MARC of this edge case when I3 starts** — he wants to weigh in on the Xano-side handling.
  - ⚠️ **CHECKPOINT before building I3 (user-requested, 2026-07-09):** the current Xano product-creation endpoint is NOT sized for volume writes. Stop and have Marc validate/rework the Xano API (bulk shape, rate, transactionality) before implementing the adapter — do not build against the existing endpoint as-is.

### Parallel agent workstreams
The sprint splits into lots with **disjoint write sets**, per the repo's delegation rules (one worker = one boundary; generated client + OpenAPI regen decided centrally in the main thread):

| Lot | Scope (write boundary) | Depends on |
|---|---|---|
| A — parsing/extraction | `backend/app/imports/parsers/`, `extract.py` + tests/fixtures | nothing (contract: normalized schema, frozen first) |
| B — profiles & CSV out | `backend/app/imports/profiles.py`, `csv_out.py`, seed + tests | schema contract only |
| C — jobs/API plumbing | `backend/app/api/` (import routes/schemas/services), `jobs/` job-type, `models/` + Alembic migration | schema contract only |
| D — frontend | `frontend/src/routes/imports/**`, settings page | C's OpenAPI contract (mock until regen) |
| E — Xano direct creation (I3) | `backend/app/destinations/` + Xano-side thin endpoints | A–C shipped |

Sequencing: freeze the normalized product schema + API contract in the main thread first, then A, B, C run fully in parallel; D starts against the contract; E last. OpenAPI/client regeneration happens once in the main thread after C settles.

### Verification (import sprint)
1. **Unit:** parser fixtures (the real `everyday-tasks/` files listed in I1: 2 L'Espion PDFs, 1 L'Espion Excel, 1 Bambinoh/Le Temps Des Cerises Excel, plus 1 generic CSV) → expected normalized rows; pricing rule (`wholesale × coef` rounded up to nearest 5); category mapping leaves unknowns empty; EAN/price values are byte-identical to the source cells.
2. **Integration:** upload a real supplier file → review grid → approve → generated CSV imports cleanly into Tillin (manual import path).
3. **I3:** direct creation on 2–3 test products → products/variants/EANs visible in Tillin; duplicate upload is flagged, not recreated.

---

## Usage metering & client billing sprint (user-requested 2026-07-09)

CatalogAI will be priced to Tillin's clients on consumption: AI tokens first, plus the other metered tools (Photoroom credits, Firecrawl, later Bright Data). This is a platform brick — every pipeline (enrichment, import, future imagery) must be metered at the source so billing never needs per-feature retrofits.

### Design
- **`usage_event` table** (app Postgres): `id, account_id, job_id?, item_id?, source (enrichment|import|…), provider (claude|photoroom|firecrawl|unlocker), model?, metric (input_tokens|output_tokens|cache_read_tokens|images|credits|requests), quantity, created_at`. One row per external call; append-only.
- **Record at the client-wrapper level**, not in pipelines: `ClaudeClient.generate_copy` reads `response.usage` (input/output/cache tokens) and emits events; the Photoroom/Firecrawl wrappers count credits/requests the same way. Pipelines stay metering-agnostic — any new feature using the wrappers is billed for free.
- **Pricing table** (config or DB): unit cost per (provider, model, metric) + per-account margin/coefficient → computed cost and billable amount are derived at query time, never stored on the event (repricing stays possible).
- **API**: `GET /usage/summary?period=` (per account: totals by provider/metric, computed cost), `GET /usage/by-job` (unit economics per job/product — replaces the plan's "cost sanity" logging item).
- **UI**: « Consommation » — dashboard tile (month-to-date) + dedicated page: per month, per provider, per job; export CSV for invoicing.

### Phasing
- **M1 — record:** usage_event table + Claude token capture (enrichment copy calls). Ship with the import sprint's extraction calls metered from day one.
- **M2 — read:** aggregation endpoints + Consommation UI.
- **M3 — rate:** pricing table + billable computation + per-account coefficient, CSV export for invoicing.

Multi-account note: today the app has a single "default" account; per-client billing becomes meaningful when client boutiques get their own accounts — the account_id dimension is in the schema from M1 so no backfill is needed.

## Future / separate sprints (out of scope here)
- **AI imagery sprint — image presentation styles:** let the user choose **flat-lay** (source selection), **on-model** (Photoroom **Virtual Model API** — flat-lay/ghost-mannequin → on-model, 12+ preset or custom brand models, poses, scene presets), and **in-scene / lifestyle** (Photoroom **AI Backgrounds** — generative scene from a text prompt). Both are Photoroom **Image Editing API Plus plan** (credits per image). Larger feature → its own sprint; the `images.py` interface should leave room for a `presentation_style` param.
- **Per-category consistent sizing:** the per-category fill-ratio enhancement above, if pursued.

## Verification
1. **Unit (pytest):** suggest.json matcher returns the right handle for `G5FU-T081` on `https://gramicci.co.uk`; `apply_title_template`; weight conversion; `process_image` returns a **4:5** JPEG at target size on the configured bg color; `generate_copy` returns FR description+meta for **both** Claude and OpenAI.
2. **Integration:** run a job over 2–3 tagged test products → worker stages results → review queue shows before/after → approve one → confirm the Tillin product/variants/images updated and the existing Shopify sync reflects it.
3. **Scraping:** Firecrawl fetch on a non-Shopify page; per-product method override works; (Phase 3) unlocker succeeds on an Asics/Farfetch page.
4. **Cost sanity:** per-product spend (Firecrawl + Photoroom + Claude) — superseded by the usage metering sprint's `GET /usage/by-job` (see the dedicated section); validate unit economics before scaling batch size.

## Open items to confirm during build
- Exact template strings (proposed title `{Brand} {Title}`, filename `{reference}_{color}_{position}`).
- Resize pixels for 4:5 (proposed 1600×2000), default `padding` (proposed ~10%), and `off_center` flag threshold; confirm Photoroom param names (`outputSize`, `padding`, `horizontalAlignment`, `backgroundColor`) + that the cutout/RGBA can be returned for the Pillow manual-recenter path.
- Default AI model per provider (proposed `claude-sonnet-4-6`; `claude-opus-4-8` when quality matters).
- Output format (proposed WebP master, JPEG fallback) + target/cap weight (proposed q≈80, ≤200 KB at 1600×2000).
- Object storage choice for processed images (Cloudflare R2 vs S3 vs PaaS volume) — cheap + durable.
- How `brand.website_url` gets populated for the existing brand catalog (bulk set vs per-brand UI).
- Legal/ToS note for marketplace sources (Farfetch) vs brands' own sites.
