<script lang="ts">
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
  } from "@/client"
  import type { ItemPublic, Product } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent, CardHeader, CardTitle } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Skeleton } from "@/lib/components/ui/skeleton"
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

  // Editable staged fields (review-time corrections).
  let title = $state("")
  let description = $state("")
  let meta = $state("")

  // Recommended SEO meta length; past this we warn (soft limit).
  const META_MAX = 160

  function hydrate(data: ItemPublic) {
    item = data
    title = data.staged_title ?? ""
    description = data.staged_description ?? ""
    meta = data.staged_meta ?? ""
  }

  $effect(() => {
    const itemId = Number(id)
    itemsReadItem({ path: { item_id: itemId } }).then(({ data, error }) => {
      if (error || !data) {
        errorMessage = "Item introuvable."
        return
      }
      hydrate(data)
    })
    // Fetch the current Tillin product in parallel; ignore failures.
    itemsReadItemProduct({ path: { item_id: itemId } }).then(({ data }) => {
      product = data ?? null
    })
  })

  const reviewable = $derived(item?.status === "ready_for_review")
  const applicable = $derived(item?.status === "approved")
  // Full re-generation allowed while under review or after reject/failure
  // (`applied` is excluded: Tillin's bulk image endpoint appends, no replace).
  const retryable = $derived(
    item?.status === "ready_for_review" ||
      item?.status === "rejected" ||
      item?.status === "failed",
  )
  const dirty = $derived(
    item !== null &&
      (title !== (item.staged_title ?? "") ||
        description !== (item.staged_description ?? "") ||
        meta !== (item.staged_meta ?? "")),
  )
  const images = $derived(
    (item?.staged_images_json ?? []) as { url: string; position?: number }[],
  )
  const weights = $derived(
    (item?.staged_weights_json ?? []) as {
      variant_id: number
      weight: number
      weight_unit: string
    }[],
  )

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

  function formatDuration(seconds: number): string {
    const s = Math.round(seconds)
    if (s < 60) return `${s} s`
    const m = Math.floor(s / 60)
    const rem = s % 60
    return rem === 0 ? `${m} min` : `${m} min ${rem} s`
  }

  async function save(): Promise<boolean> {
    if (!item) return false
    busy = true
    const { data, error } = await itemsPatchItem({
      path: { item_id: item.id },
      body: {
        staged_title: title || null,
        staged_description: description || null,
        staged_meta: meta || null,
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
    toast.success(decision === "approve" ? "Item validé" : "Item rejeté")
    navigate(`/jobs/${data.job_id}`)
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
    navigate(`/jobs/${applied.job_id}`)
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
    navigate(`/jobs/${data.job_id}`)
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

  // Fil d'Ariane : tant que l'item n'est pas chargé, on ne connaît pas le job.
  const breadcrumbs = $derived.by((): { label: string; href?: string }[] => {
    if (!item) return [{ label: "Jobs", href: "/jobs" }]
    return [
      { label: "Jobs", href: "/jobs" },
      { label: `Job #${item.job_id}`, href: `/jobs/${item.job_id}` },
      { label: `Produit #${item.tillin_product_id}` },
    ]
  })
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} {breadcrumbs}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4 pb-24">
        {#if errorMessage && item === null}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
          <Button variant="secondary" class="w-full sm:w-auto" onclick={() => navigate("/jobs")}>
            Retour aux jobs
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
            </CardHeader>
            <CardContent class="flex flex-col gap-4">
              <!-- Titre : actuel vs proposé -->
              <div class="flex flex-col gap-1.5">
                <div class="flex items-center justify-between">
                  <Label for="staged-title">Titre</Label>
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
                  <div class="flex flex-col gap-1">
                    <span class="text-muted-foreground text-xs">Proposé</span>
                    <textarea
                      id="staged-title"
                      rows="1"
                      class="border-input bg-background placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1 disabled:pointer-events-none disabled:opacity-50"
                      bind:value={title}
                      disabled={!reviewable}
                    ></textarea>
                  </div>
                </div>
              </div>
              <!-- Description : actuelle vs proposée -->
              <div class="flex flex-col gap-1.5">
                <Label for="staged-description">Description</Label>
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
                  <div class="flex flex-col gap-1">
                    <span class="text-muted-foreground text-xs">Proposé</span>
                    <textarea
                      id="staged-description"
                      rows="6"
                      class="border-input bg-background placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content max-h-80 min-h-24 w-full resize-none overflow-y-auto rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1 disabled:pointer-events-none disabled:opacity-50"
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
                  <Label for="staged-meta">Meta description</Label>
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
                  <div class="flex flex-col gap-1">
                    <span class="text-muted-foreground text-xs">Proposé</span>
                    <textarea
                      id="staged-meta"
                      rows="2"
                      class="border-input bg-background placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1 disabled:pointer-events-none disabled:opacity-50"
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
                <CardTitle class="font-title text-sm">Images source ({images.length})</CardTitle>
              </CardHeader>
              <CardContent>
                <div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {#each images as image (image.url)}
                    <img
                      src={image.url}
                      alt={`Source ${image.position ?? ""}`}
                      loading="lazy"
                      class="bg-muted aspect-4/5 w-full rounded-md object-cover"
                    />
                  {/each}
                </div>
              </CardContent>
            </Card>
          {/if}

          {#if weights.length > 0}
            <Card>
              <CardHeader>
                <CardTitle class="font-title text-sm">Poids proposés</CardTitle>
              </CardHeader>
              <CardContent class="flex flex-col gap-1 text-xs">
                {#each weights as row (row.variant_id)}
                  <div class="flex items-center justify-between gap-2">
                    <span class="text-muted-foreground font-mono">variante {row.variant_id}</span>
                    <span class="font-mono font-medium">{row.weight} {row.weight_unit}</span>
                  </div>
                {/each}
              </CardContent>
            </Card>
          {/if}

          {#if reviewable}
            <!-- Sticky decision bar: thumb-reachable on mobile (offset by the sidebar on desktop). -->
            <div
              class="border-border bg-card fixed inset-x-0 bottom-0 border-t p-3 sm:left-60"
            >
              <div class="mx-auto flex max-w-4xl flex-col gap-2 sm:flex-row sm:justify-end">
                <Button
                  class="w-full sm:order-3 sm:w-auto sm:min-w-44"
                  disabled={busy}
                  onclick={approveAndApply}
                >
                  {busy ? "…" : "Valider et appliquer"}
                </Button>
                <div class="flex gap-2 sm:contents">
                  <Button
                    variant="outline"
                    class="text-destructive flex-1 sm:order-1 sm:w-auto sm:min-w-28 sm:flex-none"
                    disabled={busy}
                    onclick={() => decide("reject")}
                  >
                    Rejeter
                  </Button>
                  <Button
                    variant="secondary"
                    class="flex-1 sm:order-2 sm:w-auto sm:min-w-28 sm:flex-none"
                    disabled={busy}
                    onclick={() => decide("approve")}
                  >
                    Valider
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
                </Button>
              </div>
            </div>
          {/if}
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
