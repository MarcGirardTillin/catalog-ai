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

## Future / separate sprints (out of scope here)
- **AI imagery sprint — image presentation styles:** let the user choose **flat-lay** (source selection), **on-model** (Photoroom **Virtual Model API** — flat-lay/ghost-mannequin → on-model, 12+ preset or custom brand models, poses, scene presets), and **in-scene / lifestyle** (Photoroom **AI Backgrounds** — generative scene from a text prompt). Both are Photoroom **Image Editing API Plus plan** (credits per image). Larger feature → its own sprint; the `images.py` interface should leave room for a `presentation_style` param.
- **Per-category consistent sizing:** the per-category fill-ratio enhancement above, if pursued.

## Verification
1. **Unit (pytest):** suggest.json matcher returns the right handle for `G5FU-T081` on `https://gramicci.co.uk`; `apply_title_template`; weight conversion; `process_image` returns a **4:5** JPEG at target size on the configured bg color; `generate_copy` returns FR description+meta for **both** Claude and OpenAI.
2. **Integration:** run a job over 2–3 tagged test products → worker stages results → review queue shows before/after → approve one → confirm the Tillin product/variants/images updated and the existing Shopify sync reflects it.
3. **Scraping:** Firecrawl fetch on a non-Shopify page; per-product method override works; (Phase 3) unlocker succeeds on an Asics/Farfetch page.
4. **Cost sanity:** log per-product spend (Firecrawl + Photoroom + Claude) to validate unit economics before scaling batch size.

## Open items to confirm during build
- Exact template strings (proposed title `{Brand} {Title}`, filename `{reference}_{color}_{position}`).
- Resize pixels for 4:5 (proposed 1600×2000), default `padding` (proposed ~10%), and `off_center` flag threshold; confirm Photoroom param names (`outputSize`, `padding`, `horizontalAlignment`, `backgroundColor`) + that the cutout/RGBA can be returned for the Pillow manual-recenter path.
- Default AI model per provider (proposed `claude-sonnet-4-6`; `claude-opus-4-8` when quality matters).
- Output format (proposed WebP master, JPEG fallback) + target/cap weight (proposed q≈80, ≤200 KB at 1600×2000).
- Object storage choice for processed images (Cloudflare R2 vs S3 vs PaaS volume) — cheap + durable.
- How `brand.website_url` gets populated for the existing brand catalog (bulk set vs per-brand UI).
- Legal/ToS note for marketplace sources (Farfetch) vs brands' own sites.
