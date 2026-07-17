<script lang="ts">
  // Page de détail d'un import : orchestration seulement — le chargement/
  // polling du job et des items, le référentiel et les magasins vivent ici,
  // les trois blocs métier sont des composants (lib/components/imports/) :
  // synthèse, grille de review, export Tillin.
  import { createQuery, useQueryClient } from "@tanstack/svelte-query"
  import { navigate } from "svelte5-router"

  import {
    loadCatalogFilters,
    type CatalogFiltersData,
  } from "@/lib/api/catalogFilters"
  import {
    getImportRows,
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

  // job/items restent des $state bindables (les composants enfants font des
  // mises à jour optimistes) mais leur source de vérité est TanStack Query :
  // cache + polling conditionnel (2,5 s tant que l'analyse tourne), chaque
  // refetch/invalidation resynchronise depuis le serveur.
  let job = $state<ImportJobPublic | null>(null)
  let items = $state<ImportItemPublic[] | null>(null)
  let page = $state(1)
  let totalPages = $state(1)

  const queryClient = useQueryClient()

  const jobQuery = createQuery(() => ({
    queryKey: ["imports", importId],
    queryFn: async () => {
      const { data, error } = await readImport(importId)
      if (error || !data) throw new Error("import_not_found")
      return data
    },
    refetchInterval: (query: { state: { data?: ImportJobPublic } }) => {
      const status = query.state.data?.status
      return status === "pending" || status === "processing" ? 2500 : false
    },
    retry: false,
  }))
  const jobRunning = $derived(
    jobQuery.data?.status === "pending" || jobQuery.data?.status === "processing",
  )
  const itemsQuery = createQuery(() => ({
    queryKey: ["imports", importId, "items", page],
    queryFn: async () => {
      const { data } = await listImportItems(importId, {
        page,
        page_size: PAGE_SIZE,
      })
      return data ?? null
    },
    // Les produits apparaissent au fil de l'analyse (accessor réactif).
    refetchInterval: jobRunning ? 2500 : false,
  }))

  $effect(() => {
    if (jobQuery.data) job = jobQuery.data
  })
  // Course de fin d'analyse : les items sont écrits en base au moment où le
  // job se termine, et les DEUX pollings s'arrêtent à cet instant — si le
  // dernier poll de la liste est passé juste avant, elle restait vide jusqu'à
  // un rechargement de la page. Un refetch final à la transition « en cours →
  // terminé » resynchronise la liste (et les compteurs de la synthèse).
  let wasRunning = false
  $effect(() => {
    if (jobRunning) {
      wasRunning = true
      return
    }
    if (wasRunning) {
      wasRunning = false
      void queryClient.invalidateQueries({
        queryKey: ["imports", importId, "items"],
      })
    }
  })
  $effect(() => {
    const data = itemsQuery.data
    if (data) {
      items = data.items
      totalPages = data.total_pages
    }
  })
  const errorMessage = $derived(
    jobQuery.isError ? "Import introuvable." : null,
  )

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

  function onItemsChanged() {
    invalidateRender()
    // Counts serveur : refetch du job (le préfixe couvre aussi les items).
    queryClient.invalidateQueries({ queryKey: ["imports", importId] })
  }

  // --- Aperçu du rendu Tillin (profil appliqué) pour la grille de review.
  // La grille édite les données EXTRAITES ; le profil ne s'applique qu'au
  // rendu (CSV/transfert). Pour lever l'ambiguïté (déjà vécue sur le prix et
  // la saison), on montre le rendu réel : titres/saisons issus de /rows —
  // la même fonction qui produit le CSV, donc aucun risque de divergence.
  const renderPreviewQuery = createQuery(() => ({
    queryKey: [
      "imports",
      importId,
      "render-preview",
      selectedProfileId,
      renderVersion,
    ],
    enabled: selectedProfileId !== null && !jobRunning,
    queryFn: async () => {
      const { data, error } = await getImportRows(
        importId,
        selectedProfileId ?? undefined,
      )
      if (error || !data) throw new Error("render_preview_failed")
      return data
    },
  }))
  /** reference_code extraite -> { title, season } rendus par le profil. */
  const renderedByRef = $derived.by(() => {
    const preview = renderPreviewQuery.data
    if (!preview) return null
    const refIdx = preview.columns.indexOf("reference_code")
    const titleIdx = preview.columns.indexOf("title")
    const seasonIdx = preview.columns.indexOf("season")
    if (refIdx < 0) return null
    const map: Record<string, { title: string; season: string }> = {}
    for (const row of preview.rows) {
      const ref = row[refIdx]
      if (!ref || map[ref]) continue
      map[ref] = {
        title: titleIdx >= 0 ? row[titleIdx] : "",
        season: seasonIdx >= 0 ? row[seasonIdx] : "",
      }
    }
    return map
  })

  function onTransferred() {
    queryClient.invalidateQueries({ queryKey: ["imports", importId] })
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
            onRenderConfigChanged={invalidateRender}
          />

          <h2 class="font-title mt-1 text-sm font-bold">Produits extraits</h2>
          {#if selectedProfile && !running}
            <div
              class="border-border bg-muted/40 flex flex-col gap-0.5 rounded-md border px-3 py-2 text-xs"
            >
              <p>
                <span class="font-medium">Profil « {selectedProfile.name} »</span
                >{#if profileSeason}
                  · saison <span class="font-medium">{profileSeason}</span
                  >{/if}{#if selectedProfile.config.apply_title_template}
                  · modèle de titre (aperçu « → » sous chaque titre){/if}
              </p>
              <p class="text-muted-foreground">
                Appliqué au transfert — la liste montre les données extraites,
                modifiables.
              </p>
            </div>
          {/if}
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
              {renderedByRef}
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
              {onTransferred}
            />
          {/if}
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
