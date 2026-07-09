<script lang="ts">
  import ChevronDown from "@lucide/svelte/icons/chevron-down"
  import ChevronRight from "@lucide/svelte/icons/chevron-right"
  import Download from "@lucide/svelte/icons/download"
  import Eye from "@lucide/svelte/icons/eye"
  import EyeOff from "@lucide/svelte/icons/eye-off"
  import LoaderCircle from "@lucide/svelte/icons/loader-circle"
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert"
  import { navigate } from "svelte5-router"

  import {
    getImportFile,
    listImportItems,
    previewImportFile,
    readImport,
    type ImportFilePreview,
    type ImportItemPublic,
    type ImportJobPublic,
    type ImportedVariant,
  } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import { prefs } from "@/lib/preferences.svelte"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import FilePreviewTable from "@/lib/components/app/FilePreviewTable.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"
  import { formatDuration } from "@/lib/format"

  let { appName, id }: { appName: string; id: string } = $props()

  const PAGE_SIZE = 100
  const cellPad = $derived(prefs.density === "compact" ? "py-1" : "py-2.5")

  let job = $state<ImportJobPublic | null>(null)
  let items = $state<ImportItemPublic[] | null>(null)
  let page = $state(1)
  let totalPages = $state(1)
  let errorMessage = $state<string | null>(null)
  let expanded = $state<Set<number>>(new Set())

  async function load() {
    const jobId = Number(id)
    const [jobResult, itemsResult] = await Promise.all([
      readImport(jobId),
      listImportItems(jobId, { page, page_size: PAGE_SIZE }),
    ])
    if (jobResult.error || !jobResult.data) {
      errorMessage = "Import introuvable."
      return
    }
    job = jobResult.data
    if (itemsResult.data) {
      items = itemsResult.data.items
      totalPages = itemsResult.data.total_pages
    } else {
      items = items ?? []
    }
  }

  // Chargement initial + polling toutes les 2,5 s tant que l'analyse tourne
  // (même pattern que le suivi des jobs d'enrichissement).
  $effect(() => {
    // `page` est lu ici pour recharger quand la pagination change.
    void page
    load()
    const timer = setInterval(() => {
      if (job && (job.status === "pending" || job.status === "processing")) {
        load()
      }
    }, 2500)
    return () => clearInterval(timer)
  })

  // Durée effective ou « En cours depuis » live (tick chaque seconde).
  let now = $state(Date.now())
  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 1000)
    return () => clearInterval(t)
  })

  const timing = $derived.by(() => {
    if (!job) return null
    if (job.duration_seconds != null) {
      return { label: "Durée", value: formatDuration(job.duration_seconds) }
    }
    if (job.started_at) {
      const elapsed = (now - new Date(job.started_at).getTime()) / 1000
      return { label: "En cours depuis", value: formatDuration(Math.max(0, elapsed)) }
    }
    return null
  })

  const running = $derived(job?.status === "pending" || job?.status === "processing")

  // Fichier source : prévisualisation (PDF via blob, tabulaire via parse
  // serveur, chargée au premier dépliage) et re-téléchargement.
  const isPdf = $derived((job?.file_name ?? "").toLowerCase().endsWith(".pdf"))
  let previewOpen = $state(false)
  let previewLoading = $state(false)
  let previewError = $state<string | null>(null)
  let filePreview = $state<ImportFilePreview | null>(null)
  let filePdfUrl = $state<string | null>(null)
  let downloading = $state(false)

  $effect(() => () => {
    if (filePdfUrl) URL.revokeObjectURL(filePdfUrl)
  })

  async function togglePreview() {
    if (previewOpen) {
      previewOpen = false
      return
    }
    previewOpen = true
    if (filePreview || filePdfUrl || previewLoading) return
    previewLoading = true
    previewError = null
    if (isPdf) {
      const { data, error } = await getImportFile(Number(id))
      if (error || !data) previewError = "Le fichier source n'est plus disponible."
      else filePdfUrl = URL.createObjectURL(data)
    } else {
      const { data, error } = await previewImportFile(Number(id))
      if (error || !data) previewError = "Le fichier source n'est plus disponible."
      else filePreview = data
    }
    previewLoading = false
  }

  async function downloadFile() {
    if (!job || downloading) return
    downloading = true
    const { data, error } = await getImportFile(Number(id))
    downloading = false
    if (error || !data) {
      previewError = "Le fichier source n'est plus disponible."
      previewOpen = true
      return
    }
    const url = URL.createObjectURL(data)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = job.file_name || `import-${id}`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  function toggleExpanded(itemId: number) {
    const next = new Set(expanded)
    if (next.has(itemId)) next.delete(itemId)
    else next.add(itemId)
    expanded = next
  }

  /** Confiance basse (< 0,7) sur un champ extrait → mise en évidence ambre. */
  function lowConfidence(confidence: Record<string, number>, field: string): boolean {
    const value = confidence?.[field]
    return value !== undefined && value < 0.7
  }

  /** Tailles agrégées : liste courte, ou « min–max » quand il y en a beaucoup. */
  function sizeSummary(variants: ImportedVariant[]): string {
    const sizes = [...new Set(variants.map((v) => v.size).filter((s): s is string => !!s))]
    if (sizes.length === 0) return "—"
    if (sizes.length <= 3) return sizes.join(", ")
    return `${sizes[0]}–${sizes[sizes.length - 1]}`
  }

  function formatPrice(raw: string | null): string {
    if (raw == null) return "—"
    const value = Number.parseFloat(raw)
    if (Number.isNaN(value)) return raw
    return value.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })
  }

  /** Fourchette de prix de gros sur les variantes (ex. « 12,50 € – 18,00 € »). */
  function wholesaleRange(variants: ImportedVariant[]): string {
    const prices = variants
      .map((v) => (v.wholesale_price == null ? NaN : Number.parseFloat(v.wholesale_price)))
      .filter((p) => !Number.isNaN(p))
    if (prices.length === 0) return "—"
    const min = Math.min(...prices)
    const max = Math.max(...prices)
    const fmt = (p: number) => p.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })
    return min === max ? fmt(min) : `${fmt(min)} – ${fmt(max)}`
  }

  function missingEanCount(variants: ImportedVariant[]): number {
    return variants.filter((v) => !v.ean).length
  }

  // Champs produit secondaires affichés dans la ligne dépliée.
  const PRODUCT_FIELDS: { key: "category" | "season" | "gender" | "composition" | "hs_code" | "manufacturing_country"; label: string }[] = [
    { key: "category", label: "Catégorie" },
    { key: "season", label: "Saison" },
    { key: "gender", label: "Genre" },
    { key: "composition", label: "Composition" },
    { key: "hs_code", label: "Code SH" },
    { key: "manufacturing_country", label: "Pays de fabrication" },
  ]
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell
      {appName}
      {user}
      breadcrumbs={[
        { label: "Imports", href: "/imports" },
        { label: job?.file_name ?? `Import #${id}` },
      ]}
    >
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        {#if errorMessage}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
          <Button variant="secondary" class="w-full sm:w-auto" onclick={() => navigate("/imports")}>
            Retour aux imports
          </Button>
        {:else if job === null}
          <Skeleton class="h-24 w-full" />
          <Skeleton class="h-16 w-full" />
        {:else}
          <div class="flex items-center justify-between gap-2">
            <h1 class="font-title min-w-0 truncate text-lg font-bold" title={job.file_name}>
              {job.file_name}
            </h1>
            <StatusBadge status={job.status} />
          </div>

          <Card>
            <CardContent class="flex flex-col gap-3">
              <dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-xs sm:grid-cols-4">
                {#if job.po_number}
                  <div>
                    <dt class="text-muted-foreground">N° de commande (PO)</dt>
                    <dd class="font-mono font-medium">{job.po_number}</dd>
                  </div>
                {/if}
                {#if job.supplier}
                  <div>
                    <dt class="text-muted-foreground">Fournisseur</dt>
                    <dd class="font-medium">{job.supplier}</dd>
                  </div>
                {/if}
                <div>
                  <dt class="text-muted-foreground">Produits extraits</dt>
                  <dd class="font-mono font-medium">{job.counts.total}</dd>
                </div>
                <div>
                  <dt class="text-muted-foreground">À vérifier</dt>
                  <dd class="font-mono font-medium">{job.counts.ready_for_review}</dd>
                </div>
                {#if job.counts.failed > 0}
                  <div>
                    <dt class="text-muted-foreground">Échecs</dt>
                    <dd class="text-destructive font-mono font-medium">{job.counts.failed}</dd>
                  </div>
                {/if}
                {#if timing}
                  <div>
                    <dt class="text-muted-foreground">{timing.label}</dt>
                    <dd class="font-mono font-medium">{timing.value}</dd>
                  </div>
                {/if}
                {#if job.totals.quantity > 0}
                  <div>
                    <dt class="text-muted-foreground">Quantité totale</dt>
                    <dd class="font-mono font-medium">{job.totals.quantity}</dd>
                  </div>
                {/if}
                {#if job.totals.wholesale_amount != null}
                  <div>
                    <dt class="text-muted-foreground">Total prix de gros</dt>
                    <dd class="font-mono font-medium">
                      {formatPrice(job.totals.wholesale_amount)}
                    </dd>
                  </div>
                {/if}
                {#if job.totals.retail_amount != null}
                  <div>
                    <dt class="text-muted-foreground">Total prix conseillé</dt>
                    <dd class="font-mono font-medium">
                      {formatPrice(job.totals.retail_amount)}
                    </dd>
                  </div>
                {/if}
              </dl>

              {#if running}
                <p class="text-muted-foreground text-xs">
                  Analyse du fichier en cours — la page se met à jour automatiquement.
                </p>
              {/if}

              {#if job.warnings.length > 0}
                <ul class="flex flex-col gap-0.5">
                  {#each job.warnings as warning (warning)}
                    <li class="text-warning-foreground flex items-start gap-1.5 text-xs">
                      <TriangleAlert size={12} class="mt-0.5 shrink-0" aria-hidden="true" />
                      {warning}
                    </li>
                  {/each}
                </ul>
              {/if}

              {#if job.error}
                <p class="text-destructive text-xs" role="alert">{job.error}</p>
              {/if}

              <!-- Fichier source : aperçu à la demande + re-téléchargement. -->
              <div class="border-border flex flex-col gap-3 border-t pt-3">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <p class="text-muted-foreground text-xs">
                    Fichier source : <span class="text-foreground font-medium">{job.file_name}</span>
                  </p>
                  <div class="flex items-center gap-2">
                    <Button variant="outline" size="sm" onclick={togglePreview}>
                      {#if previewLoading}
                        <LoaderCircle size={14} class="animate-spin" aria-hidden="true" />
                      {:else if previewOpen}
                        <EyeOff size={14} aria-hidden="true" />
                      {:else}
                        <Eye size={14} aria-hidden="true" />
                      {/if}
                      {previewOpen ? "Masquer l'aperçu" : "Prévisualiser"}
                    </Button>
                    <Button variant="outline" size="sm" disabled={downloading} onclick={downloadFile}>
                      {#if downloading}
                        <LoaderCircle size={14} class="animate-spin" aria-hidden="true" />
                      {:else}
                        <Download size={14} aria-hidden="true" />
                      {/if}
                      Télécharger
                    </Button>
                  </div>
                </div>

                {#if previewOpen}
                  {#if previewError}
                    <p class="text-destructive text-xs" role="alert">{previewError}</p>
                  {:else if previewLoading}
                    <Skeleton class="h-40 w-full" />
                  {:else if filePdfUrl}
                    <iframe
                      src={filePdfUrl}
                      title="Aperçu de {job.file_name}"
                      class="border-border h-128 w-full rounded-md border"
                    ></iframe>
                  {:else if filePreview}
                    <FilePreviewTable sheets={filePreview.sheets} />
                  {/if}
                {/if}
              </div>
            </CardContent>
          </Card>

          <h2 class="font-title mt-1 text-sm font-bold">Produits extraits</h2>
          {#if items === null}
            <Skeleton class="h-16 w-full" />
          {:else if items.length === 0}
            <Card>
              <CardContent class="text-muted-foreground py-6 text-center text-sm">
                {running
                  ? "Les produits apparaîtront ici au fil de l'analyse."
                  : "Aucun produit n'a été extrait de ce fichier."}
              </CardContent>
            </Card>
          {:else}
            <Card class="py-0">
              <CardContent class="overflow-x-auto px-0">
                <table class="w-full min-w-2xl text-sm">
                  <thead>
                    <tr class="border-border border-b">
                      <th class="w-8 px-2 py-2.5"><span class="sr-only">Détail</span></th>
                      <th class="text-muted-foreground px-3 py-2.5 text-left text-xs font-medium">Référence</th>
                      <th class="text-muted-foreground px-3 py-2.5 text-left text-xs font-medium">Titre</th>
                      <th class="text-muted-foreground px-3 py-2.5 text-left text-xs font-medium">Marque</th>
                      <th class="text-muted-foreground px-3 py-2.5 text-right text-xs font-medium">Variantes</th>
                      <th class="text-muted-foreground px-3 py-2.5 text-left text-xs font-medium">Tailles</th>
                      <th class="text-muted-foreground px-3 py-2.5 text-right text-xs font-medium">Prix de gros</th>
                      <th class="text-muted-foreground px-3 py-2.5 text-left text-xs font-medium"><span class="sr-only">Alertes</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each items as item (item.id)}
                      {@const product = item.payload}
                      {@const isOpen = expanded.has(item.id)}
                      {@const noEan = missingEanCount(product.variants)}
                      <tr
                        class="border-border hover:bg-muted/50 cursor-pointer border-b transition-colors"
                        onclick={() => toggleExpanded(item.id)}
                      >
                        <td class="px-2 {cellPad}">
                          <button
                            type="button"
                            class="text-muted-foreground hover:text-foreground flex cursor-pointer items-center p-0.5 transition-colors"
                            aria-expanded={isOpen}
                            aria-label={isOpen
                              ? `Replier ${product.supplier_ref}`
                              : `Déplier ${product.supplier_ref}`}
                            onclick={(e) => {
                              e.stopPropagation()
                              toggleExpanded(item.id)
                            }}
                          >
                            {#if isOpen}
                              <ChevronDown size={14} aria-hidden="true" />
                            {:else}
                              <ChevronRight size={14} aria-hidden="true" />
                            {/if}
                          </button>
                        </td>
                        <td
                          class="px-3 {cellPad} font-mono text-xs whitespace-nowrap {lowConfidence(product.confidence, 'supplier_ref')
                            ? 'text-warning-foreground'
                            : ''}"
                        >
                          {product.supplier_ref}
                        </td>
                        <td
                          class="max-w-52 truncate px-3 {cellPad} {lowConfidence(product.confidence, 'title')
                            ? 'text-warning-foreground'
                            : ''}"
                          title={product.title ?? undefined}
                        >
                          {product.title ?? "—"}
                        </td>
                        <td
                          class="px-3 {cellPad} whitespace-nowrap {lowConfidence(product.confidence, 'brand')
                            ? 'text-warning-foreground'
                            : ''}"
                        >
                          {product.brand ?? "—"}
                        </td>
                        <td class="px-3 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {product.variants.length}
                        </td>
                        <td class="px-3 {cellPad} whitespace-nowrap">
                          {sizeSummary(product.variants)}
                        </td>
                        <td class="px-3 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {wholesaleRange(product.variants)}
                        </td>
                        <td class="px-3 {cellPad}">
                          <div class="flex items-center gap-1.5 whitespace-nowrap">
                            {#if noEan > 0}
                              <span
                                class="text-muted-foreground bg-muted rounded-full px-2 py-0.5 text-[11px]"
                              >
                                {noEan} sans EAN
                              </span>
                            {/if}
                            {#if item.warnings.length > 0}
                              <span
                                class="text-warning-foreground flex items-center gap-1 text-[11px]"
                                title={item.warnings.join(" · ")}
                              >
                                <TriangleAlert size={12} aria-hidden="true" />
                                {item.warnings.length}
                              </span>
                            {/if}
                          </div>
                        </td>
                      </tr>
                      {#if isOpen}
                        <tr class="border-border bg-muted/30 border-b">
                          <td colspan="8" class="px-4 py-3">
                            <div class="flex flex-col gap-3">
                              {#if item.warnings.length > 0}
                                <ul class="flex flex-col gap-0.5">
                                  {#each item.warnings as warning (warning)}
                                    <li class="text-warning-foreground flex items-start gap-1.5 text-xs">
                                      <TriangleAlert size={12} class="mt-0.5 shrink-0" aria-hidden="true" />
                                      {warning}
                                    </li>
                                  {/each}
                                </ul>
                              {/if}
                              {#if item.error}
                                <p class="text-destructive text-xs">{item.error}</p>
                              {/if}

                              {#if PRODUCT_FIELDS.some(({ key }) => product[key])}
                                <dl class="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs sm:grid-cols-3">
                                  {#each PRODUCT_FIELDS as { key, label } (key)}
                                    {#if product[key]}
                                      <div>
                                        <dt class="text-muted-foreground">{label}</dt>
                                        <dd
                                          class={lowConfidence(product.confidence, key)
                                            ? "text-warning-foreground"
                                            : ""}
                                        >
                                          {product[key]}
                                        </dd>
                                      </div>
                                    {/if}
                                  {/each}
                                </dl>
                              {/if}

                              <div class="overflow-x-auto">
                                <table class="w-full min-w-lg text-xs">
                                  <thead>
                                    <tr class="border-border border-b">
                                      <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">Couleur</th>
                                      <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">Taille</th>
                                      <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">EAN</th>
                                      <th class="text-muted-foreground px-2 py-1.5 text-right font-medium">Qté</th>
                                      <th class="text-muted-foreground px-2 py-1.5 text-right font-medium">Prix de gros</th>
                                      <th class="text-muted-foreground px-2 py-1.5 text-right font-medium">Prix conseillé</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {#each product.variants as variant, index (index)}
                                      <tr class="border-border/50 border-b last:border-b-0">
                                        <td
                                          class="px-2 py-1.5 {lowConfidence(variant.confidence, 'color')
                                            ? 'text-warning-foreground'
                                            : ''}"
                                        >
                                          {variant.color ?? "—"}
                                        </td>
                                        <td
                                          class="px-2 py-1.5 {lowConfidence(variant.confidence, 'size')
                                            ? 'text-warning-foreground'
                                            : ''}"
                                        >
                                          {variant.size ?? "—"}
                                        </td>
                                        <td
                                          class="px-2 py-1.5 font-mono {lowConfidence(variant.confidence, 'ean')
                                            ? 'text-warning-foreground'
                                            : ''}"
                                        >
                                          {variant.ean ?? "—"}
                                        </td>
                                        <td class="px-2 py-1.5 text-right tabular-nums">
                                          {variant.quantity ?? "—"}
                                        </td>
                                        <td
                                          class="px-2 py-1.5 text-right tabular-nums {lowConfidence(variant.confidence, 'wholesale_price')
                                            ? 'text-warning-foreground'
                                            : ''}"
                                        >
                                          {formatPrice(variant.wholesale_price)}
                                        </td>
                                        <td
                                          class="px-2 py-1.5 text-right tabular-nums {lowConfidence(variant.confidence, 'retail_price')
                                            ? 'text-warning-foreground'
                                            : ''}"
                                        >
                                          {formatPrice(variant.retail_price)}
                                        </td>
                                      </tr>
                                    {/each}
                                  </tbody>
                                </table>
                              </div>

                              <p class="text-muted-foreground text-xs">
                                Lecture seule — l'édition arrive avec l'étape de review.
                              </p>
                            </div>
                          </td>
                        </tr>
                      {/if}
                    {/each}
                  </tbody>
                </table>
              </CardContent>
            </Card>

            <div class="flex items-center justify-between gap-2">
              <p class="text-muted-foreground text-xs">
                <span class="text-warning-foreground">Texte ambre</span> : champ extrait avec une
                confiance faible — à vérifier.
              </p>
              {#if totalPages > 1}
                <div class="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page <= 1}
                    onclick={() => (page = page - 1)}
                  >
                    Précédent
                  </Button>
                  <span class="text-muted-foreground text-xs whitespace-nowrap tabular-nums">
                    Page {page} / {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page >= totalPages}
                    onclick={() => (page = page + 1)}
                  >
                    Suivant
                  </Button>
                </div>
              {/if}
            </div>
          {/if}
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
