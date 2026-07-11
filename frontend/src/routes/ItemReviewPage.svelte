<script lang="ts">
  import Check from "@lucide/svelte/icons/check"
  import ChevronLeft from "@lucide/svelte/icons/chevron-left"
  import ChevronRight from "@lucide/svelte/icons/chevron-right"
  import LoaderCircle from "@lucide/svelte/icons/loader-circle"
  import Scissors from "@lucide/svelte/icons/scissors"
  import Undo2 from "@lucide/svelte/icons/undo-2"
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import {
    itemsApplyItemRoute,
    itemsApproveItem,
    itemsPatchItem,
    itemsReadItem,
    itemsReadItemProduct,
    itemsRejectItem,
    itemsResolveItemRoute,
    itemsRetryItemRoute,
    jobsListJobItems,
  } from "@/client"
  import type { ItemPublic, Product } from "@/client"
  import { client } from "@/client/client.gen"
  import { normalizeItemImage } from "@/lib/api/imaging"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import { accountSettings, loadAccountSettings } from "@/lib/accountSettings.svelte"
  import { formatDuration } from "@/lib/format"
  import { prefs } from "@/lib/preferences.svelte"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"

  let { appName, id }: { appName: string; id: string } = $props()

  let item = $state<ItemPublic | null>(null)
  // Current Tillin product (before/after context); best-effort, may be null
  // when Xano is unavailable.
  let product = $state<Product | null>(null)
  let errorMessage = $state<string | null>(null)
  let busy = $state(false)
  let resolving = $state(false)
  let manualUrl = $state("")

  // Sibling items of the same job (serial review navigation).
  let siblings = $state<{ id: number; status: string }[]>([])
  // Two-step reject: first activation arms the button, second confirms.
  let confirmingReject = $state(false)
  let rejectTimer: ReturnType<typeof setTimeout> | undefined

  // Editable staged fields (review-time corrections).
  let title = $state("")
  let description = $state("")
  let meta = $state("")

  // Per-field apply choice: key absent or `true` = written to Tillin on apply,
  // `false` = skipped. Keys: "title" | "description" | "meta" | "images" | "weights".
  let applyFields = $state<Record<string, boolean>>({})

  // `apply_fields_json` accepte aussi des sélections partielles (le type
  // généré ne connaît que les booléens — cast local en attendant la
  // régénération OpenAPI) :
  // - `image_urls`: sous-ensemble des URLs de staged_images_json à appliquer
  //   (clé absente = toutes ; ignorée si `images: false`)
  // - `weight_variant_ids`: idem pour les poids (`weights` = master)
  type ApplyFieldsExtended = {
    [key: string]: boolean | string[] | number[] | null | undefined
    image_urls?: string[]
    weight_variant_ids?: number[]
  }

  // Sélection par image / par variante (sous le master du champ).
  let selectedImageUrls = $state<string[]>([])
  let selectedWeightIds = $state<number[]>([])

  // Recommended SEO meta length; past this we warn (soft limit). Suit le
  // réglage de compte `meta_max_length` (chargé une fois par session,
  // défaut 160 tant que le fetch n'a pas abouti ou s'il échoue).
  loadAccountSettings()
  const META_MAX = $derived(accountSettings.meta_max_length)

  function hydrate(data: ItemPublic) {
    item = data
    title = data.staged_title ?? ""
    description = data.staged_description ?? ""
    meta = data.staged_meta ?? ""
    void loadImagePreviews(data)
    const raw = (data.apply_fields_json ?? {}) as ApplyFieldsExtended
    const bools: Record<string, boolean> = {}
    for (const [key, value] of Object.entries(raw)) {
      if (typeof value === "boolean") bools[key] = value
    }
    applyFields = bools
    // Sélections partielles : clé absente = tout sélectionné.
    const allUrls = ((data.staged_images_json ?? []) as { url: string }[]).map(
      (i) => i.url,
    )
    const storedUrls = raw.image_urls
    selectedImageUrls = Array.isArray(storedUrls)
      ? allUrls.filter((u) => storedUrls.includes(u))
      : [...allUrls]
    const allIds = ((data.staged_weights_json ?? []) as { variant_id: number }[]).map(
      (w) => w.variant_id,
    )
    const storedIds = raw.weight_variant_ids
    selectedWeightIds = Array.isArray(storedIds)
      ? allIds.filter((v) => storedIds.includes(v))
      : [...allIds]
  }

  function isApplied(key: string): boolean {
    return applyFields[key] ?? true
  }

  function toggleApply(key: string) {
    applyFields = { ...applyFields, [key]: !isApplied(key) }
  }

  // Normalized signature: only explicitly-unchecked keys matter
  // (a key set to `true` is equivalent to an absent key).
  function excludedKeys(fields: ApplyFieldsExtended | null | undefined): string {
    return Object.keys(fields ?? {})
      .filter((key) => fields?.[key] === false)
      .sort()
      .join(",")
  }

  function toggleImage(url: string) {
    selectedImageUrls = selectedImageUrls.includes(url)
      ? selectedImageUrls.filter((u) => u !== url)
      : [...selectedImageUrls, url]
  }

  // Les images normalisées par le batch pointent vers la route authentifiée
  // /imaging/assets/{id}/files/{i} : un <img src> nu ne porte pas le cookie
  // de façon fiable en cross-origin — on les charge en blob (object URLs,
  // révoquées à chaque rechargement). Les URLs externes restent telles quelles.
  let imagePreviews = $state<Record<string, string>>({})
  // Bascule avant/après quand au moins une entrée porte sa source d'origine.
  let showOriginals = $state(false)

  async function loadImagePreviews(data: ItemPublic) {
    for (const url of Object.values(imagePreviews)) URL.revokeObjectURL(url)
    imagePreviews = {}
    showOriginals = false
    const entries = (data.staged_images_json ?? []) as { url: string }[]
    const previews: Record<string, string> = {}
    for (const entry of entries) {
      if (!entry.url.startsWith("/imaging/")) continue
      const { data: blob } = await client.get<{ 200: Blob }, unknown>({
        responseType: "blob",
        url: entry.url,
      })
      if (blob instanceof Blob) previews[entry.url] = URL.createObjectURL(blob)
    }
    imagePreviews = previews
  }

  $effect(() => () => {
    for (const url of Object.values(imagePreviews)) URL.revokeObjectURL(url)
  })

  function imageSrc(image: { url: string; source_url?: string }): string {
    if (showOriginals && image.source_url) return image.source_url
    return imagePreviews[image.url] ?? image.url
  }

  // Normalisation par image (les originales sont stagées par défaut) :
  // une opération à la fois, l'item rechargé porte la nouvelle entrée.
  let normalizingUrl = $state<string | null>(null)

  async function normalizeOne(image: { url: string; asset_id?: number }) {
    const it = item
    if (!it || normalizingUrl !== null) return
    normalizingUrl = image.url
    const revert = image.asset_id != null
    const { data, error } = await normalizeItemImage(it.id, image.url, revert)
    normalizingUrl = null
    if (error || !data) {
      toast.error(
        revert
          ? "Impossible de rétablir l'originale."
          : "Échec de la normalisation (service d'imagerie indisponible ?).",
      )
      return
    }
    hydrate(data)
  }

  function toggleWeight(variantId: number) {
    selectedWeightIds = selectedWeightIds.includes(variantId)
      ? selectedWeightIds.filter((v) => v !== variantId)
      : [...selectedWeightIds, variantId]
  }

  // Signature normalisée d'une sélection partielle : sélection complète
  // (ou clé absente/malformée) ≡ "" ; sinon la liste retenue, dans l'ordre
  // des éléments stagés.
  function selectionSignature(stored: unknown, all: (string | number)[]): string {
    if (!Array.isArray(stored)) return ""
    const kept = all.filter((x) => (stored as (string | number)[]).includes(x))
    return kept.length === all.length ? "" : kept.map(String).join("|")
  }

  // apply_fields_json envoyé au PATCH : booléens par champ + sélections
  // partielles. Une sélection complète est omise (clé absente = tout).
  function buildApplyFields(): ApplyFieldsExtended {
    const payload: ApplyFieldsExtended = { ...applyFields }
    const allUrls = images.map((i) => i.url)
    const keptUrls = allUrls.filter((u) => selectedImageUrls.includes(u))
    if (keptUrls.length < allUrls.length) payload.image_urls = keptUrls
    const allIds = weights.map((w) => w.variant_id)
    const keptIds = allIds.filter((v) => selectedWeightIds.includes(v))
    if (keptIds.length < allIds.length) payload.weight_variant_ids = keptIds
    return payload
  }

  $effect(() => {
    const itemId = Number(id)
    // Reset so navigating between sibling items shows a fresh skeleton.
    item = null
    product = null
    errorMessage = null
    confirmingReject = false
    itemsReadItem({ path: { item_id: itemId } }).then(({ data, error }) => {
      if (error || !data) {
        errorMessage = "Item introuvable."
        return
      }
      hydrate(data)
      // Siblings for prev/next navigation (same job, worker order).
      jobsListJobItems({
        path: { job_id: data.job_id },
        query: { page_size: 100 },
      }).then(({ data: page }) => {
        siblings = (page?.items ?? []).map((i) => ({ id: i.id, status: i.status }))
      })
    })
    // Fetch the current Tillin product in parallel; ignore failures.
    itemsReadItemProduct({ path: { item_id: itemId } }).then(({ data }) => {
      product = data ?? null
    })
  })

  const currentIndex = $derived(siblings.findIndex((s) => s.id === Number(id)))
  const prevId = $derived(currentIndex > 0 ? siblings[currentIndex - 1]?.id : null)
  const nextId = $derived(
    currentIndex >= 0 && currentIndex < siblings.length - 1
      ? siblings[currentIndex + 1]?.id
      : null,
  )

  // Next item still awaiting review — forward first, then from the start.
  function nextReviewableId(): number | null {
    const itemId = Number(id)
    const others = siblings.filter(
      (s) => s.id !== itemId && s.status === "ready_for_review",
    )
    if (others.length === 0) return null
    const after = others.find(
      (s) => siblings.findIndex((x) => x.id === s.id) > currentIndex,
    )
    return (after ?? others[0]).id
  }

  // After a decision, chain to the next item to review; else back to the job.
  function continueReview(jobId: number) {
    if (!prefs.auto_advance) {
      navigate(`/jobs/${jobId}`)
      return
    }
    const next = nextReviewableId()
    if (next !== null) navigate(`/items/${next}`)
    else navigate(`/jobs/${jobId}`)
  }

  const reviewable = $derived(item?.status === "ready_for_review")
  const applicable = $derived(item?.status === "approved")
  // Full re-generation allowed while under review or after reject/failure
  // (`applied` is excluded: Tillin's bulk image endpoint appends, no replace).
  const retryable = $derived(
    item?.status === "ready_for_review" ||
      item?.status === "rejected" ||
      item?.status === "failed",
  )
  const images = $derived(
    (item?.staged_images_json ?? []) as {
      url: string
      position?: number
      asset_id?: number
      source_url?: string
    }[],
  )
  const hasBeforeAfter = $derived(images.some((i) => i.source_url))
  const weights = $derived(
    (item?.staged_weights_json ?? []) as {
      variant_id: number
      weight: number
      weight_unit: string
    }[],
  )
  const storedApplyFields = $derived(
    (item?.apply_fields_json ?? {}) as ApplyFieldsExtended,
  )
  const dirty = $derived(
    item !== null &&
      (title !== (item.staged_title ?? "") ||
        description !== (item.staged_description ?? "") ||
        meta !== (item.staged_meta ?? "") ||
        excludedKeys(applyFields) !== excludedKeys(storedApplyFields) ||
        selectionSignature(
          selectedImageUrls,
          images.map((i) => i.url),
        ) !==
          selectionSignature(
            storedApplyFields.image_urls,
            images.map((i) => i.url),
          ) ||
        selectionSignature(
          selectedWeightIds,
          weights.map((w) => w.variant_id),
        ) !==
          selectionSignature(
            storedApplyFields.weight_variant_ids,
            weights.map((w) => w.variant_id),
          )),
  )

  // Every field that actually has staged content is unchecked: nothing will
  // be written to Tillin on apply. Warn, but do not block.
  const nothingApplied = $derived.by(() => {
    const withContent = (
      [
        ["title", title.trim() !== ""],
        ["description", description.trim() !== ""],
        ["meta", meta.trim() !== ""],
        ["images", images.length > 0],
      ] as const
    )
      .filter(([, has]) => has)
      .map(([key]) => key)
    return withContent.length > 0 && withContent.every((key) => !isApplied(key))
  })

  const allImagesSelected = $derived(
    images.length > 0 && images.every((i) => selectedImageUrls.includes(i.url)),
  )

  function toggleAllImages() {
    selectedImageUrls = allImagesSelected ? [] : images.map((i) => i.url)
  }

  type Candidate = { url: string; title?: string | null; score: number }
  const resolution = $derived(
    (item?.resolution_json ?? null) as {
      reason?: string | null
      candidates?: Candidate[]
    } | null,
  )
  const candidates = $derived(resolution?.candidates ?? [])
  const hasSource = $derived(item?.source_url != null && item.source_url !== "")

  // Human-friendly explanation of why no source was auto-resolved.
  const diagnostic = $derived.by(() => {
    if (hasSource) return null
    const reason = resolution?.reason
    switch (reason) {
      case "no website URL for brand":
        return "Aucun site web n'est renseigné pour cette marque dans Tillin."
      case "no candidate found":
        return "Aucun produit correspondant trouvé sur le(s) site(s) de la marque (souvent : site non-Shopify, ou code-barres/référence absents du site)."
      case "no candidate above confidence threshold":
        return "Des candidats ont été trouvés mais aucun n'est assez fiable (seuil 0,75). Choisis-en un ou colle l'URL exacte ci-dessous."
      default:
        return reason ?? "Pas de page source résolue automatiquement."
    }
  })

  // Variant count from the current Tillin product, for a quick sanity check.
  const variantCount = $derived((product?.variants ?? []).length)

  // Human-friendly resolution method (avoid raw enum values in the UI).
  const METHOD_LABELS: Record<string, string> = {
    shopify_json: "trouvée automatiquement",
    manual: "choisie manuellement",
    needs_manual: "résolution manuelle requise",
    skipped: "non recherchée",
  }
  const methodLabel = $derived(
    item?.source_method ? (METHOD_LABELS[item.source_method] ?? item.source_method) : null,
  )

  async function save(): Promise<boolean> {
    if (!item) return false
    busy = true
    const { data, error } = await itemsPatchItem({
      path: { item_id: item.id },
      body: {
        staged_title: title || null,
        staged_description: description || null,
        staged_meta: meta || null,
        // Le type généré ne connaît pas encore les clés de sélection
        // partielle (image_urls, weight_variant_ids) : cast local.
        apply_fields_json: buildApplyFields() as unknown as Record<string, boolean>,
      },
    })
    busy = false
    if (error || !data) {
      toast.error("Enregistrement impossible.")
      return false
    }
    hydrate(data)
    return true
  }

  async function saveCorrections() {
    if (await save()) toast.success("Corrections enregistrées")
  }

  async function decide(decision: "approve" | "reject") {
    if (!item) return
    if (decision === "approve" && dirty && !(await save())) return
    busy = true
    const call = decision === "approve" ? itemsApproveItem : itemsRejectItem
    const { data, error } = await call({ path: { item_id: item.id } })
    busy = false
    if (error || !data) {
      toast.error("Action impossible.")
      return
    }
    toast.success(decision === "approve" ? "Item validé" : "Item écarté")
    continueReview(data.job_id)
  }

  // Reject is destructive-ish: first activation arms, second confirms.
  function requestReject() {
    if (!confirmingReject) {
      confirmingReject = true
      clearTimeout(rejectTimer)
      rejectTimer = setTimeout(() => (confirmingReject = false), 4000)
      return
    }
    clearTimeout(rejectTimer)
    confirmingReject = false
    decide("reject")
  }

  async function approveAndApply() {
    if (!item) return
    if (dirty && !(await save())) return
    busy = true
    const { data: approved, error: approveError } = await itemsApproveItem({
      path: { item_id: item.id },
    })
    if (approveError || !approved) {
      busy = false
      toast.error("Action impossible.")
      return
    }
    const { data: applied, error: applyError } = await itemsApplyItemRoute({
      path: { item_id: item.id },
    })
    busy = false
    if (applyError || !applied) {
      // Approved but not written to Tillin: fall back to the "apply" bar.
      item = approved
      toast.error(
        "Validé, mais écriture vers Tillin impossible. Réessayez depuis le bouton Appliquer.",
      )
      return
    }
    toast.success("Appliqué à Tillin ✓")
    continueReview(applied.job_id)
  }

  async function apply() {
    if (!item) return
    busy = true
    const { data, error } = await itemsApplyItemRoute({ path: { item_id: item.id } })
    busy = false
    if (error || !data) {
      toast.error("Écriture vers Tillin impossible. Réessayez.")
      return
    }
    toast.success("Appliqué à Tillin ✓")
    continueReview(data.job_id)
  }

  async function retry() {
    if (!item) return
    busy = true
    const { data, error } = await itemsRetryItemRoute({ path: { item_id: item.id } })
    busy = false
    if (error || !data) {
      toast.error("Relance impossible.")
      return
    }
    toast.success("Régénération lancée")
    // The item is back in the queue; follow progress on the job page.
    navigate(`/jobs/${data.job_id}`)
  }

  async function resolveFrom(url: string) {
    if (!item || !url.trim()) return
    resolving = true
    const { data, error } = await itemsResolveItemRoute({
      path: { item_id: item.id },
      body: { source_url: url.trim() },
    })
    resolving = false
    if (error || !data) {
      toast.error(
        "Impossible de résoudre depuis cette URL (page introuvable ou site non pris en charge).",
      )
      return
    }
    toast.success("Source résolue")
    hydrate(data)
    manualUrl = ""
  }

  // Keyboard shortcuts for serial review (opt-in via les préférences,
  // flèches comprises). Inactive while typing in a field.
  function onKeydown(event: KeyboardEvent) {
    if (!prefs.shortcuts_enabled) return
    if (event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return
    const target = event.target as HTMLElement | null
    if (target?.closest("input, textarea, select, [contenteditable]")) return
    if (item === null) return

    if (event.key === "ArrowLeft" && prevId !== null) {
      event.preventDefault()
      navigate(`/items/${prevId}`)
    } else if (event.key === "ArrowRight" && nextId !== null) {
      event.preventDefault()
      navigate(`/items/${nextId}`)
    } else if (!busy && reviewable && (event.key === "v" || event.key === "V")) {
      event.preventDefault()
      decide("approve")
    } else if (!busy && reviewable && (event.key === "r" || event.key === "R")) {
      event.preventDefault()
      requestReject()
    } else if (!busy && (event.key === "a" || event.key === "A")) {
      if (reviewable) {
        event.preventDefault()
        approveAndApply()
      } else if (applicable) {
        event.preventDefault()
        apply()
      }
    }
  }

  // Fil d'Ariane : tant que l'item n'est pas chargé, on ne connaît pas le job.
  const breadcrumbs = $derived.by((): { label: string; href?: string }[] => {
    if (!item) return [{ label: "Enrichissements", href: "/jobs" }]
    return [
      { label: "Enrichissements", href: "/jobs" },
      { label: `Enrichissement #${item.job_id}`, href: `/jobs/${item.job_id}` },
      { label: `Produit #${item.tillin_product_id}` },
    ]
  })
</script>

{#snippet kbd(letter: string)}
  {#if prefs.shortcuts_enabled}
    <kbd
      class="pointer-events-none hidden rounded border border-current/30 px-1 font-mono text-[10px] leading-4 opacity-60 sm:inline-block"
      aria-hidden="true"
    >
      {letter}
    </kbd>
  {/if}
{/snippet}

{#snippet applyCheckbox(key: string)}
  <label
    class="text-muted-foreground flex cursor-pointer items-center gap-1.5 text-xs font-normal"
  >
    <input
      type="checkbox"
      class="accent-primary size-3.5"
      checked={isApplied(key)}
      disabled={!reviewable}
      onchange={() => toggleApply(key)}
    />
    Appliquer
  </label>
{/snippet}

<svelte:window onkeydown={onKeydown} />

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} {breadcrumbs}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4 pb-24">
        {#if errorMessage && item === null}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
          <Button variant="secondary" class="w-full sm:w-auto" onclick={() => navigate("/jobs")}>
            Retour aux enrichissements
          </Button>
        {:else if item === null}
          <Skeleton class="h-24 w-full" />
          <Skeleton class="h-40 w-full" />
        {:else}
          <div class="flex items-start justify-between gap-2">
            <h1 class="font-title text-lg font-bold">
              {product?.title ?? `Produit #${item.tillin_product_id}`}
            </h1>
            <div class="flex shrink-0 items-center gap-2">
              {#if siblings.length > 1 && currentIndex >= 0}
                <div class="border-border flex items-center rounded-md border">
                  <button
                    type="button"
                    class="text-muted-foreground hover:text-foreground flex size-7 cursor-pointer items-center justify-center disabled:cursor-default disabled:opacity-40"
                    aria-label="Item précédent"
                    title={prefs.shortcuts_enabled ? "Item précédent (←)" : "Item précédent"}
                    disabled={prevId === null}
                    onclick={() => prevId !== null && navigate(`/items/${prevId}`)}
                  >
                    <ChevronLeft size={16} aria-hidden="true" />
                  </button>
                  <span class="text-muted-foreground px-1 font-mono text-xs tabular-nums">
                    {currentIndex + 1}/{siblings.length}
                  </span>
                  <button
                    type="button"
                    class="text-muted-foreground hover:text-foreground flex size-7 cursor-pointer items-center justify-center disabled:cursor-default disabled:opacity-40"
                    aria-label="Item suivant"
                    title={prefs.shortcuts_enabled ? "Item suivant (→)" : "Item suivant"}
                    disabled={nextId === null}
                    onclick={() => nextId !== null && navigate(`/items/${nextId}`)}
                  >
                    <ChevronRight size={16} aria-hidden="true" />
                  </button>
                </div>
              {/if}
              {#if retryable}
                <Button variant="outline" size="sm" disabled={busy} onclick={retry}>
                  {busy ? "…" : "Régénérer"}
                </Button>
              {/if}
              <StatusBadge status={item.status} />
            </div>
          </div>

          <!-- Current Tillin product: the before/after context. -->
          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">Produit actuel (Tillin)</CardTitle>
            </CardHeader>
            <CardContent class="flex flex-col gap-3 text-xs">
              <div class="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1">
                <span class="font-mono">#{item.tillin_product_id}</span>
                {#if product?.reference_code}
                  <span>réf. {product.reference_code}</span>
                {/if}
                {#if product?.brand?.name}
                  <span>{product.brand.name}</span>
                {/if}
                {#if product?.category}
                  <span
                    class="bg-muted text-foreground rounded-full px-2 py-0.5 font-medium"
                    >{product.category}</span
                  >
                {/if}
              </div>
              {#if variantCount > 0}
                <div class="text-muted-foreground">
                  {variantCount} variante{variantCount > 1 ? "s" : ""}
                </div>
              {/if}
              {#if (product?.images ?? []).length > 0}
                <div class="flex gap-2 overflow-x-auto">
                  {#each product?.images ?? [] as img (img.url)}
                    <img
                      src={img.url}
                      alt="Visuel actuel du produit Tillin"
                      loading="lazy"
                      class="bg-muted h-20 w-16 shrink-0 rounded object-cover"
                    />
                  {/each}
                </div>
              {:else}
                <p class="text-muted-foreground italic">
                  Aucune image actuellement sur le produit Tillin.
                </p>
              {/if}
            </CardContent>
          </Card>

          <!-- Source resolution + manual override. -->
          <Card size="sm">
            <CardContent class="flex flex-col gap-2 text-xs">
              <div class="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1">
                {#if item.source_url}
                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer"
                    class="text-primary underline underline-offset-2"
                  >
                    Page source ↗
                  </a>
                {/if}
                {#if methodLabel}
                  <span>source : {methodLabel}</span>
                {/if}
                {#if item.match_score != null}
                  <span class="font-mono">score {item.match_score.toFixed(2)}</span>
                {/if}
                {#if item.duration_seconds != null}
                  <span class="font-mono">généré en {formatDuration(item.duration_seconds)}</span>
                {/if}
              </div>

              {#if diagnostic}
                <p class="text-muted-foreground">{diagnostic}</p>
              {/if}

              {#if reviewable}
                {#if candidates.length > 0}
                  <div class="flex flex-col gap-1">
                    <span class="text-muted-foreground">Candidats trouvés :</span>
                    {#each candidates as candidate (candidate.url)}
                      <button
                        type="button"
                        disabled={resolving}
                        onclick={() => resolveFrom(candidate.url)}
                        class="hover:bg-muted flex items-center justify-between gap-2 rounded border px-2 py-1 text-left disabled:opacity-50"
                      >
                        <span class="truncate">{candidate.title ?? candidate.url}</span>
                        <span class="shrink-0 font-mono"
                          >{candidate.score.toFixed(2)}</span
                        >
                      </button>
                    {/each}
                  </div>
                {/if}

                <div class="flex flex-col gap-1.5 pt-1">
                  <Label for="manual-url">Résoudre depuis une URL produit</Label>
                  <div class="flex gap-2">
                    <Input
                      id="manual-url"
                      placeholder="https://marque.com/products/handle"
                      bind:value={manualUrl}
                      disabled={resolving}
                    />
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={resolving || !manualUrl.trim()}
                      onclick={() => resolveFrom(manualUrl)}
                    >
                      {resolving ? "…" : "Résoudre"}
                    </Button>
                  </div>
                </div>
              {/if}
            </CardContent>
          </Card>

          <!-- Staged content (editable while ready_for_review) -->
          <Card>
            <CardHeader>
              <CardTitle class="font-title text-sm">Contenu proposé</CardTitle>
              <CardDescription class="text-muted-foreground text-xs">
                Décochez les champs à ne pas écrire dans Tillin.
              </CardDescription>
            </CardHeader>
            <CardContent class="flex flex-col gap-4">
              <!-- Titre : actuel vs proposé -->
              <div class="flex flex-col gap-1.5">
                <div class="flex items-center justify-between">
                  <div class="flex items-center gap-3">
                    <Label for="staged-title">Titre</Label>
                    {@render applyCheckbox("title")}
                  </div>
                  <span class="text-muted-foreground font-mono text-xs">{title.length}</span>
                </div>
                <div class="grid gap-2 sm:grid-cols-2">
                  <div class="flex flex-col gap-1">
                    <span class="text-muted-foreground text-xs">Actuel</span>
                    <div class="text-muted-foreground bg-muted/50 rounded-md p-2.5 text-sm">
                      {#if product?.title}
                        {product.title}
                      {:else}
                        <span class="italic">—</span>
                      {/if}
                    </div>
                  </div>
                  <div class="flex flex-col gap-1" class:opacity-60={!isApplied("title")}>
                    <span class="text-muted-foreground text-xs">Proposé</span>
                    <textarea
                      id="staged-title"
                      rows="1"
                      class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1 disabled:pointer-events-none disabled:opacity-50"
                      bind:value={title}
                      disabled={!reviewable}
                    ></textarea>
                  </div>
                </div>
              </div>
              <!-- Description : actuelle vs proposée -->
              <div class="flex flex-col gap-1.5">
                <div class="flex items-center gap-3">
                  <Label for="staged-description">Description</Label>
                  {@render applyCheckbox("description")}
                </div>
                <div class="grid gap-2 sm:grid-cols-2">
                  <div class="flex flex-col gap-1">
                    <span class="text-muted-foreground text-xs">Actuel</span>
                    <div
                      class="text-muted-foreground bg-muted/50 max-h-80 overflow-y-auto rounded-md p-2.5 text-sm whitespace-pre-wrap"
                    >
                      {#if product?.description}
                        {product.description}
                      {:else}
                        <span class="italic">—</span>
                      {/if}
                    </div>
                  </div>
                  <div class="flex flex-col gap-1" class:opacity-60={!isApplied("description")}>
                    <span class="text-muted-foreground text-xs">Proposé</span>
                    <textarea
                      id="staged-description"
                      rows="6"
                      class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content max-h-80 min-h-24 w-full resize-none overflow-y-auto rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1 disabled:pointer-events-none disabled:opacity-50"
                      placeholder="Pas de description générée (copie IA non branchée)."
                      bind:value={description}
                      disabled={!reviewable}
                    ></textarea>
                  </div>
                </div>
              </div>
              <!-- Meta description : actuelle vs proposée -->
              <div class="flex flex-col gap-1.5">
                <div class="flex items-center justify-between">
                  <div class="flex items-center gap-3">
                    <Label for="staged-meta">Meta description</Label>
                    {@render applyCheckbox("meta")}
                  </div>
                  <span
                    class="font-mono text-xs {meta.length > META_MAX
                      ? 'text-destructive'
                      : 'text-muted-foreground'}"
                  >
                    {meta.length}/{META_MAX}
                  </span>
                </div>
                <div class="grid gap-2 sm:grid-cols-2">
                  <div class="flex flex-col gap-1">
                    <span class="text-muted-foreground text-xs">Actuel</span>
                    <div class="text-muted-foreground bg-muted/50 rounded-md p-2.5 text-sm">
                      {#if product?.meta_description}
                        {product.meta_description}
                      {:else}
                        <span class="italic">—</span>
                      {/if}
                    </div>
                  </div>
                  <div class="flex flex-col gap-1" class:opacity-60={!isApplied("meta")}>
                    <span class="text-muted-foreground text-xs">Proposé</span>
                    <textarea
                      id="staged-meta"
                      rows="2"
                      class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1 disabled:pointer-events-none disabled:opacity-50"
                      placeholder="Pas de meta générée."
                      bind:value={meta}
                      disabled={!reviewable}
                    ></textarea>
                  </div>
                </div>
              </div>
              {#if reviewable && dirty}
                <Button
                  variant="secondary"
                  size="sm"
                  class="self-start"
                  disabled={busy}
                  onclick={saveCorrections}
                >
                  Enregistrer les corrections
                </Button>
              {/if}
            </CardContent>
          </Card>

          {#if images.length > 0}
            <Card>
              <CardHeader>
                <CardTitle class="font-title text-sm">
                  Images proposées ({images.length})
                </CardTitle>
                <CardAction>{@render applyCheckbox("images")}</CardAction>
              </CardHeader>
              <CardContent class="flex flex-col gap-2">
                <div
                  class="text-muted-foreground flex items-center justify-between text-xs"
                  class:opacity-60={!isApplied("images")}
                >
                  <span>
                    {selectedImageUrls.length}/{images.length} sélectionnée{selectedImageUrls.length >
                    1
                      ? "s"
                      : ""}
                  </span>
                  <span class="flex items-center gap-3">
                    {#if hasBeforeAfter}
                      <button
                        type="button"
                        class="hover:text-foreground cursor-pointer underline underline-offset-2"
                        aria-pressed={showOriginals}
                        onclick={() => (showOriginals = !showOriginals)}
                      >
                        {showOriginals
                          ? "Voir les images normalisées"
                          : "Voir les originales"}
                      </button>
                    {/if}
                    {#if reviewable && isApplied("images")}
                      <button
                        type="button"
                        class="hover:text-foreground cursor-pointer underline underline-offset-2"
                        onclick={toggleAllImages}
                      >
                        {allImagesSelected ? "Tout désélectionner" : "Tout sélectionner"}
                      </button>
                    {/if}
                  </span>
                </div>
                <div
                  class="grid grid-cols-2 gap-2 sm:grid-cols-3"
                  class:opacity-60={!isApplied("images")}
                >
                  {#each images as image (image.url)}
                    {@const selected = selectedImageUrls.includes(image.url)}
                    {@const busy = normalizingUrl === image.url}
                    <div class="relative">
                      <button
                        type="button"
                        class="focus-visible:ring-ring relative block w-full cursor-pointer rounded-md outline-none focus-visible:ring-2 disabled:cursor-default"
                        aria-pressed={selected}
                        aria-label={`Image ${image.position ?? ""} — ${
                          selected ? "sélectionnée" : "non sélectionnée"
                        }`}
                        disabled={!reviewable || !isApplied("images")}
                        onclick={() => toggleImage(image.url)}
                      >
                        <img
                          src={imageSrc(image)}
                          alt=""
                          loading="lazy"
                          class="bg-muted aspect-4/5 w-full rounded-md object-cover transition-opacity {selected
                            ? ''
                            : 'ring-muted-foreground/50 opacity-40 ring-2'}"
                        />
                        {#if image.asset_id != null}
                          <span
                            class="bg-card/90 text-muted-foreground absolute top-1.5 left-1.5 rounded px-1 text-[10px]"
                          >
                            {showOriginals && image.source_url
                              ? "originale"
                              : "normalisée"}
                          </span>
                        {/if}
                        <span
                          aria-hidden="true"
                          class="absolute top-1.5 right-1.5 flex size-5 items-center justify-center rounded border shadow-sm {selected
                            ? 'bg-primary border-primary text-primary-foreground'
                            : 'bg-card/90 border-input text-transparent'}"
                        >
                          <Check size={14} />
                        </span>
                      </button>
                      {#if reviewable && isApplied("images")}
                        <button
                          type="button"
                          class="bg-card/90 border-input text-foreground hover:bg-card absolute right-1.5 bottom-1.5 flex cursor-pointer items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] shadow-sm disabled:opacity-60"
                          disabled={normalizingUrl !== null}
                          onclick={() => normalizeOne(image)}
                        >
                          {#if busy}
                            <LoaderCircle
                              size={11}
                              class="animate-spin"
                              aria-hidden="true"
                            />
                          {:else if image.asset_id != null}
                            <Undo2 size={11} aria-hidden="true" />
                            Rétablir
                          {:else}
                            <Scissors size={11} aria-hidden="true" />
                            Normaliser
                          {/if}
                        </button>
                      {/if}
                    </div>
                  {/each}
                </div>
              </CardContent>
            </Card>
          {/if}

          {#if weights.length > 0}
            <Card>
              <CardHeader>
                <CardTitle class="font-title flex items-center gap-2 text-sm">
                  Poids proposés
                  <span
                    class="text-muted-foreground rounded-full border px-2 py-0.5 text-[10px] font-normal"
                  >
                    Bientôt actif
                  </span>
                </CardTitle>
                <CardDescription class="text-muted-foreground text-xs">
                  La sélection est enregistrée ; l'écriture des poids vers Tillin arrive
                  bientôt.
                </CardDescription>
                <CardAction>{@render applyCheckbox("weights")}</CardAction>
              </CardHeader>
              <CardContent
                class="flex flex-col gap-1 text-xs {isApplied('weights')
                  ? ''
                  : 'opacity-60'}"
              >
                {#each weights as row (row.variant_id)}
                  <label class="flex cursor-pointer items-center justify-between gap-2">
                    <span class="flex items-center gap-2">
                      <input
                        type="checkbox"
                        class="accent-primary size-3.5"
                        checked={selectedWeightIds.includes(row.variant_id)}
                        disabled={!reviewable || !isApplied("weights")}
                        onchange={() => toggleWeight(row.variant_id)}
                      />
                      <span class="text-muted-foreground font-mono">
                        variante {row.variant_id}
                      </span>
                    </span>
                    <span class="font-mono font-medium">{row.weight} {row.weight_unit}</span>
                  </label>
                {/each}
              </CardContent>
            </Card>
          {/if}

          {#if reviewable}
            <!-- Sticky decision bar: thumb-reachable on mobile (offset by the sidebar on desktop). -->
            <div
              class="border-border bg-card fixed inset-x-0 bottom-0 border-t p-3 sm:left-60"
            >
              {#if nothingApplied}
                <p class="text-destructive mx-auto max-w-4xl pb-2 text-xs" role="alert">
                  Aucun champ ne sera écrit dans Tillin.
                </p>
              {/if}
              <div class="mx-auto flex max-w-4xl flex-col gap-2 sm:flex-row sm:justify-end">
                <Button
                  class="w-full sm:order-3 sm:w-auto sm:min-w-44"
                  disabled={busy}
                  onclick={approveAndApply}
                >
                  {busy ? "…" : "Valider et appliquer"}
                  {@render kbd("A")}
                </Button>
                <div class="flex gap-2 sm:contents">
                  <Button
                    variant={confirmingReject ? "destructive" : "outline"}
                    class="flex-1 sm:order-1 sm:w-auto sm:min-w-28 sm:flex-none {confirmingReject
                      ? ''
                      : 'text-destructive'}"
                    disabled={busy}
                    onclick={requestReject}
                  >
                    {confirmingReject ? "Confirmer" : "Écarter"}
                    {@render kbd("R")}
                  </Button>
                  <Button
                    variant="secondary"
                    class="flex-1 sm:order-2 sm:w-auto sm:min-w-28 sm:flex-none"
                    disabled={busy}
                    onclick={() => decide("approve")}
                  >
                    Valider
                    {@render kbd("V")}
                  </Button>
                </div>
              </div>
            </div>
          {:else if applicable}
            <!-- Approved item: manual push to Tillin (no auto-push). -->
            <div class="border-border bg-card fixed inset-x-0 bottom-0 border-t p-3 sm:left-60">
              <div class="mx-auto flex max-w-4xl items-center gap-3 sm:justify-end">
                <span class="text-muted-foreground hidden text-xs sm:inline">
                  Validé — prêt à écrire dans Tillin.
                </span>
                <Button class="flex-1 sm:min-w-44 sm:flex-none" disabled={busy} onclick={apply}>
                  {busy ? "Écriture…" : "Appliquer vers Tillin"}
                  {@render kbd("A")}
                </Button>
              </div>
            </div>
          {/if}
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
