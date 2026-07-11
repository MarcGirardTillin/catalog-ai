<script lang="ts">
  // Page de détail d'un import : orchestration seulement — le chargement/
  // polling du job et des items, le référentiel et les magasins vivent ici,
  // les trois blocs métier sont des composants (lib/components/imports/) :
  // synthèse, grille de review, export Tillin.
  import { navigate } from "svelte5-router"

  import {
    loadCatalogFilters,
    type CatalogFiltersData,
  } from "@/lib/api/catalogFilters"
  import {
    listImportItems,
    listImportProfiles,
    listLocations,
    readImport,
    type ImportItemPublic,
    type ImportJobPublic,
    type ImportProfilePublic,
    type LocationPublic,
  } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"
  import ImportExportSection from "@/lib/components/imports/ImportExportSection.svelte"
  import ImportReviewTable from "@/lib/components/imports/ImportReviewTable.svelte"
  import ImportSummaryCard from "@/lib/components/imports/ImportSummaryCard.svelte"

  let { appName, id }: { appName: string; id: string } = $props()

  const PAGE_SIZE = 100
  const importId = $derived(Number(id))

  let job = $state<ImportJobPublic | null>(null)
  let items = $state<ImportItemPublic[] | null>(null)
  let page = $state(1)
  let totalPages = $state(1)
  let errorMessage = $state<string | null>(null)

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

  const running = $derived(job?.status === "pending" || job?.status === "processing")
  const completed = $derived(job?.status === "completed")

  // --- Profils d'import (liste + sélection du job) ---
  let profiles = $state<ImportProfilePublic[] | null>(null)
  let selectedProfileId = $state<number | null>(null)
  // Pré-sélection faite une seule fois (job.profile_id, sinon correspondance
  // fournisseur ≈ supplier_match en minuscules).
  let profileInitDone = false

  $effect(() => {
    listImportProfiles().then(({ data }) => {
      profiles = data ?? []
    })
  })

  $effect(() => {
    if (profileInitDone || !job || profiles === null) return
    profileInitDone = true
    if (job.profile_id != null) {
      selectedProfileId = job.profile_id
      return
    }
    const supplier = (job.supplier ?? "").trim().toLowerCase()
    if (supplier === "") return
    const match = profiles.find((p) => {
      const needle = p.supplier_match.trim().toLowerCase()
      return needle !== "" && (supplier.includes(needle) || needle.includes(supplier))
    })
    if (match) selectedProfileId = match.id
  })

  const selectedProfile = $derived(
    (profiles ?? []).find((p) => p.id === selectedProfileId) ?? null,
  )

  // Saison imposée par le profil : valeur effective affichée dans la grille.
  const profileSeason = $derived((selectedProfile?.config.season_label ?? "").trim())

  // Prix de vente calculé par le profil (mode coefficient uniquement) —
  // aperçu local dans la grille, le calcul réel est appliqué au CSV.
  const coefficientConfig = $derived.by(() => {
    const config = selectedProfile?.config
    if (!config || config.price_mode !== "coefficient") return null
    const coefficient = Number(config.coefficient)
    if (!Number.isFinite(coefficient) || coefficient <= 0) return null
    const step = Number(config.round_up_to)
    return {
      coefficient,
      step: Number.isFinite(step) && step > 0 ? step : 0,
    }
  })

  // --- Référentiel de classification (datalists de la grille de review).
  // Échec silencieux : les champs restent de simples champs texte. ---
  let catalogFilters = $state<CatalogFiltersData | null>(null)
  $effect(() => {
    loadCatalogFilters().then((data) => {
      catalogFilters = data
    })
  })

  // --- Magasins Tillin (synthèse + panneau de transfert) ---
  let locations = $state<LocationPublic[] | null>(null)
  let locationsLoading = $state(false)
  let locationsError = $state<string | null>(null)

  async function loadLocations() {
    if (locationsLoading) return
    locationsLoading = true
    locationsError = null
    const { data, error } = await listLocations()
    locationsLoading = false
    if (error || !data) {
      locationsError = "Impossible de charger les magasins."
      return
    }
    locations = data
  }

  $effect(() => {
    loadLocations()
  })

  // --- Invalidation de l'aperçu CSV (profil changé, item édité/écarté). ---
  let renderVersion = $state(0)

  function invalidateRender() {
    renderVersion += 1
  }

  async function refreshJob() {
    const { data } = await readImport(Number(id))
    if (data) job = data
  }

  function onItemsChanged() {
    invalidateRender()
    refreshJob()
  }
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

          <ImportSummaryCard
            {importId}
            bind:job
            bind:profiles
            bind:selectedProfileId
            {locations}
            onRenderConfigChanged={invalidateRender}
          />

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
            <ImportReviewTable
              {importId}
              bind:items
              bind:page
              {totalPages}
              {completed}
              {profileSeason}
              {coefficientConfig}
              {catalogFilters}
              onChanged={onItemsChanged}
            />
          {/if}

          <!-- Export Tillin : aperçu des lignes générées, CSV et transfert.
               Toujours visible quand l'analyse est terminée (actions
               désactivées + explication tant qu'aucun profil n'est choisi). -->
          {#if completed}
            <h2 class="font-title mt-1 text-sm font-bold">Export Tillin</h2>
            <ImportExportSection
              {importId}
              {job}
              {selectedProfileId}
              {locations}
              {locationsError}
              onRetryLocations={loadLocations}
              {renderVersion}
              onTransferred={load}
            />
          {/if}
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
