<script lang="ts">
  // Export Tillin d'un import : aperçu CSV, téléchargement, transfert vers un
  // magasin, et pont vers l'enrichissement des produits créés. Extrait
  // d'ImportDetailPage (scission P5.2) — aucune modification de comportement.
  import Download from "@lucide/svelte/icons/download"
  import Eye from "@lucide/svelte/icons/eye"
  import EyeOff from "@lucide/svelte/icons/eye-off"
  import LoaderCircle from "@lucide/svelte/icons/loader-circle"
  import Send from "@lucide/svelte/icons/send"
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert"
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import { jobsCreateEnrichmentJob } from "@/client"
  import {
    getImportCsv,
    getImportProducts,
    getImportRows,
    linkImportProducts,
    transferImport,
    type ImportJobPublic,
    type ImportRowsPreview,
    type LocationPublic,
  } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Label } from "@/lib/components/ui/label"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import EnrichChooser from "@/lib/components/app/EnrichChooser.svelte"
  import FilePreviewTable from "@/lib/components/app/FilePreviewTable.svelte"

  let {
    importId,
    job,
    selectedProfileId,
    locations,
    locationsError = null,
    onRetryLocations,
    renderVersion,
    onTransferred,
  }: {
    importId: number
    job: ImportJobPublic
    selectedProfileId: number | null
    /** Magasins Tillin (chargés par la page), null tant que non chargés. */
    locations: LocationPublic[] | null
    locationsError?: string | null
    onRetryLocations?: () => void
    /** Incrémenté par la page quand le rendu CSV doit être invalidé
     * (changement de profil, édition/statut d'un item). */
    renderVersion: number
    /** Transfert réussi : la page recharge job + items. */
    onTransferred: () => void
  } = $props()

  const selectClass =
    "border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"

  // Combien de produits partiront (non écartés) vs écartés vs déjà transférés.
  // Dérivé des counts SERVEUR : le transfert couvre tout le job, pas la page.
  const transferSummary = $derived({
    kept: job.counts.ready_for_review ?? 0,
    excluded: job.counts.rejected ?? 0,
    applied: job.counts.applied ?? 0,
  })

  // --- Aperçu CSV / téléchargement ---
  let rowsOpen = $state(false)
  let rowsLoading = $state(false)
  let rowsError = $state<string | null>(null)
  let rowsPreview = $state<ImportRowsPreview | null>(null)
  let csvDownloading = $state(false)

  // Invalidation externe (profil changé, item édité/écarté…).
  $effect(() => {
    void renderVersion
    rowsPreview = null
    rowsOpen = false
  })

  async function toggleCsvPreview() {
    if (rowsOpen) {
      rowsOpen = false
      return
    }
    rowsOpen = true
    if (rowsPreview || rowsLoading) return
    rowsLoading = true
    rowsError = null
    const { data, error } = await getImportRows(importId, selectedProfileId ?? undefined)
    rowsLoading = false
    if (error || !data) {
      rowsError = "Impossible de générer l'aperçu CSV."
      return
    }
    rowsPreview = data
  }

  async function downloadCsv() {
    if (csvDownloading) return
    csvDownloading = true
    const result = await getImportCsv(importId, selectedProfileId ?? undefined)
    csvDownloading = false
    if (result.error || !result.data) {
      toast.error("Téléchargement du CSV impossible.")
      return
    }
    // Nom depuis Content-Disposition si le header est accessible.
    let fileName = `import_${importId}.csv`
    const headers = (result as { response?: { headers?: Record<string, unknown> } })
      .response?.headers
    const disposition = headers?.["content-disposition"]
    if (typeof disposition === "string") {
      const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)
      if (match?.[1]) fileName = decodeURIComponent(match[1])
    }
    const url = URL.createObjectURL(result.data)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = fileName
    anchor.click()
    URL.revokeObjectURL(url)
  }

  // --- Transfert vers Tillin ---
  let transferOpen = $state(false)
  let selectedLocationId = $state("")
  let transferring = $state(false)
  let transferred = $state(false)

  function toggleTransfer() {
    transferOpen = !transferOpen
    if (transferOpen) {
      // Pré-sélectionne le magasin du job (modifiable avant confirmation).
      if (job.location_id != null) selectedLocationId = String(job.location_id)
      else if (
        selectedLocationId === "" &&
        locations !== null &&
        locations.length > 0
      ) {
        selectedLocationId = String(locations[0].id)
      }
    }
  }

  async function confirmTransfer() {
    if (selectedLocationId === "" || transferring) return
    transferring = true
    const { data, error } = await transferImport(importId, {
      location_id: Number(selectedLocationId),
      ...(selectedProfileId != null ? { profile_id: selectedProfileId } : {}),
    })
    transferring = false
    if (error || !data || !data.ok) {
      toast.error("Transfert vers Tillin impossible.")
      return
    }
    transferOpen = false
    transferred = true
    toast.success(
      `${data.row_count} ligne${data.row_count > 1 ? "s" : ""} transférée${data.row_count > 1 ? "s" : ""} vers Tillin`,
    )
    // La page recharge job + items : les items passent au statut « applied ».
    onTransferred()
  }

  // --- Pont import → enrichissement : une fois le transfert fait, on peut
  // voir les produits créés dans Tillin ou lancer directement un job
  // d'enrichissement sur eux (liaison à la volée si nécessaire). ---
  let enriching = $state(false)

  // Des items déjà transférés (counts serveur), ou transfert fait à l'instant.
  const hasTransferred = $derived(
    transferred || (job.counts.applied ?? 0) > 0,
  )

  async function enrichCreatedProducts(
    transforms: { copy: boolean; title: boolean; weights: boolean; images: boolean },
    instructionId: number | null,
  ) {
    if (enriching) return
    enriching = true
    let { data, error } = await getImportProducts(importId)
    if (error || !data) {
      enriching = false
      toast.error("Impossible de lire les produits de l'import.")
      return
    }
    if (data.unlinked_count > 0) {
      const linkResult = await linkImportProducts(importId)
      if (linkResult.error || !linkResult.data) {
        enriching = false
        const code = (linkResult.error as { code?: string } | null)?.code
        toast.error(
          code === "not_transferred"
            ? "Cet import n'a pas encore été transféré vers Tillin."
            : "Liaison aux produits Tillin impossible.",
        )
        return
      }
      const refreshed = await getImportProducts(importId)
      if (refreshed.data) data = refreshed.data
    }
    const ids = data.items
      .map((i) => i.tillin_product_id)
      .filter((v): v is number => v != null)
    if (ids.length === 0) {
      enriching = false
      toast.error(
        "Aucun produit Tillin relié à cet import — impossible de lancer l'enrichissement.",
      )
      return
    }
    const { data: jobData, error: jobError } = await jobsCreateEnrichmentJob({
      body: {
        selection: { ids },
        config: {
          transforms,
          ...(instructionId != null ? { instruction_id: instructionId } : {}),
        },
      },
    })
    enriching = false
    if (jobError || !jobData) {
      toast.error("Création de l'enrichissement impossible.")
      return
    }
    toast.success(
      `Enrichissement #${jobData.id} créé (${ids.length} produit${ids.length > 1 ? "s" : ""})`,
    )
    navigate(`/jobs/${jobData.id}`)
  }
</script>

<Card>
  <CardContent class="flex flex-col gap-3">
    {#if selectedProfileId == null}
      <p class="text-muted-foreground text-xs">
        Sélectionnez un profil d'import (section « Profil d'import »
        ci-dessus) pour générer l'aperçu, le CSV et le transfert
        vers Tillin.
      </p>
    {/if}
    <div class="flex flex-wrap items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        disabled={selectedProfileId == null}
        onclick={toggleCsvPreview}
      >
        {#if rowsLoading}
          <LoaderCircle size={14} class="animate-spin" aria-hidden="true" />
        {:else if rowsOpen}
          <EyeOff size={14} aria-hidden="true" />
        {:else}
          <Eye size={14} aria-hidden="true" />
        {/if}
        {rowsOpen ? "Masquer l'aperçu" : "Aperçu CSV"}
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={csvDownloading || selectedProfileId == null}
        onclick={downloadCsv}
      >
        {#if csvDownloading}
          <LoaderCircle size={14} class="animate-spin" aria-hidden="true" />
        {:else}
          <Download size={14} aria-hidden="true" />
        {/if}
        Télécharger le CSV
      </Button>
      <Button
        size="sm"
        disabled={transferSummary.kept === 0 || selectedProfileId == null}
        title={selectedProfileId == null
          ? "Sélectionnez d'abord un profil d'import"
          : transferSummary.kept === 0
            ? "Aucun produit à transférer"
            : undefined}
        onclick={toggleTransfer}
      >
        <Send size={14} aria-hidden="true" />
        Transférer {transferSummary.kept} produit{transferSummary.kept > 1
          ? "s"
          : ""} vers Tillin
      </Button>
      {#if transferSummary.applied > 0}
        <span
          class="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] text-emerald-600 dark:text-emerald-400"
        >
          {transferSummary.applied} déjà transféré{transferSummary.applied > 1
            ? "s"
            : ""}
        </span>
      {/if}
    </div>

    {#if hasTransferred}
      <!-- Pont vers la suite du pipeline : produits créés dans Tillin. -->
      <div class="border-border flex flex-col gap-2 border-t pt-3">
        <p class="text-muted-foreground text-xs">
          Les produits de cet import ont été créés dans Tillin —
          poursuivez le pipeline.
        </p>
        <div class="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onclick={() => navigate(`/products?import=${importId}`)}
          >
            Voir les produits créés
          </Button>
          <EnrichChooser
            label="Enrichir les produits créés"
            busy={enriching}
            onLaunch={enrichCreatedProducts}
          />
        </div>
      </div>
    {/if}

    {#if rowsOpen}
      {#if rowsError}
        <p class="text-destructive text-xs" role="alert">{rowsError}</p>
      {:else if rowsLoading}
        <Skeleton class="h-40 w-full" />
      {:else if rowsPreview}
        {#if rowsPreview.warnings.length > 0}
          <ul class="flex flex-col gap-0.5">
            {#each rowsPreview.warnings as warning, i (i)}
              <li class="text-warning-foreground flex items-start gap-1.5 text-xs">
                <TriangleAlert size={12} class="mt-0.5 shrink-0" aria-hidden="true" />
                {warning}
              </li>
            {/each}
          </ul>
        {/if}
        <FilePreviewTable
          sheets={[{ rows: [rowsPreview.columns, ...rowsPreview.rows] }]}
        />
        <p class="text-muted-foreground text-xs">
          {rowsPreview.row_count}
          ligne{rowsPreview.row_count > 1 ? "s" : ""} dans le CSV généré.
        </p>
      {/if}
    {/if}

    {#if transferOpen}
      <div class="border-border flex flex-col gap-3 rounded-md border p-3">
        <p class="text-sm font-medium">Transférer vers Tillin</p>
        {#if locationsError}
          <div class="flex flex-col items-start gap-2">
            <p class="text-destructive text-xs" role="alert">{locationsError}</p>
            {#if onRetryLocations}
              <Button variant="secondary" size="sm" onclick={onRetryLocations}>
                Réessayer
              </Button>
            {/if}
          </div>
        {:else if locations === null}
          <Skeleton class="h-9 w-full sm:max-w-80" />
        {:else if locations.length === 0}
          <p class="text-muted-foreground text-xs">
            Aucun magasin disponible dans Tillin.
          </p>
        {:else}
          <div class="flex flex-col gap-1.5 sm:max-w-80">
            <Label for="transfer-location">Magasin</Label>
            <select
              id="transfer-location"
              class={selectClass}
              bind:value={selectedLocationId}
            >
              {#each locations as location (location.id)}
                <option value={String(location.id)}>{location.title}</option>
              {/each}
            </select>
          </div>
          <p class="text-muted-foreground text-xs">
            <span class="text-foreground font-medium"
              >{transferSummary.kept} produit{transferSummary.kept > 1
                ? "s"
                : ""}</span
            >
            {transferSummary.kept > 1 ? "seront créés" : "sera créé"} dans
            Tillin sur ce magasin{#if transferSummary.excluded > 0}, {transferSummary.excluded}
              écarté{transferSummary.excluded > 1 ? "s" : ""} ne
              {transferSummary.excluded > 1 ? "seront" : "sera"} pas transféré{transferSummary.excluded >
              1
                ? "s"
                : ""}{/if}. Cochez ou décochez les produits dans la liste
            pour choisir ceux à transférer.
          </p>
        {/if}
        <div class="flex items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onclick={() => (transferOpen = false)}>
            Annuler
          </Button>
          <Button
            size="sm"
            disabled={transferring ||
              selectedLocationId === "" ||
              transferSummary.kept === 0}
            onclick={confirmTransfer}
          >
            {#if transferring}
              <LoaderCircle size={14} class="animate-spin" aria-hidden="true" />
            {/if}
            {transferring
              ? "Transfert…"
              : `Confirmer (${transferSummary.kept})`}
          </Button>
        </div>
      </div>
    {/if}
  </CardContent>
</Card>
