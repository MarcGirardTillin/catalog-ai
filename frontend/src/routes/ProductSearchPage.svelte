<script lang="ts">
  import ChevronDown from "@lucide/svelte/icons/chevron-down"
  import ChevronUp from "@lucide/svelte/icons/chevron-up"
  import ImageIcon from "@lucide/svelte/icons/image"
  import Link2 from "@lucide/svelte/icons/link-2"
  import LoaderCircle from "@lucide/svelte/icons/loader-circle"
  import PackageSearch from "@lucide/svelte/icons/package-search"
  import Search from "@lucide/svelte/icons/search"
  import X from "@lucide/svelte/icons/x"
  import { onMount } from "svelte"
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import {
    catalogGetFilters,
    jobsCreateEnrichmentJob,
    productsListProducts,
  } from "@/client"
  import type { CatalogFilters, FilterOption, Product } from "@/client"
  import {
    getImportProducts,
    linkImportProducts,
    listImports,
    type ImportJobPublic,
    type ImportProductItem,
    type ImportProductsResponse,
  } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import { prefs } from "@/lib/preferences.svelte"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import FilterSelect from "@/lib/components/app/FilterSelect.svelte"
  import JobOptionsPanel from "@/lib/components/app/JobOptionsPanel.svelte"
  import ProductPanel from "@/lib/components/app/ProductPanel.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"

  let { appName }: { appName: string } = $props()

  // --- Onglets : « Catalogue » (recherche Tillin) / « Par import » (produits
  // créés par un import fournisseur). Même pattern qu'EnrichmentPage. ---
  const TABS = [
    { key: "catalog", label: "Catalogue" },
    { key: "import", label: "Par import" },
  ] as const
  type TabKey = (typeof TABS)[number]["key"]
  let tab = $state<TabKey>("catalog")

  // Densité des tables : padding vertical des cellules selon la préférence.
  const cellPad = $derived(prefs.density === "compact" ? "py-1" : "py-2")

  let search = $state("")
  let page = $state(1)
  let products = $state<Product[] | null>(null)
  let total = $state(0)
  let totalPages = $state(0)
  let loading = $state(false)
  let errorMessage = $state<string | null>(null)

  // Filter options (loaded once) + current selections.
  let filters = $state<CatalogFilters | null>(null)
  let brand = $state<number | null>(null)
  let category = $state<number | null>(null)
  let season = $state<number | null>(null)
  let supplier = $state<number | null>(null)
  let tag = $state<number | null>(null)

  // Selected product ids persist across pages/searches until the job is created.
  let selected = $state<Set<number>>(new Set())
  let translate = $state(false)
  let submitting = $state(false)

  // Options de génération (panneau dépliable au-dessus de la barre d'action ;
  // reste monté quand il est replié pour conserver les saisies).
  let optionsOpen = $state(false)
  let optionsPanel = $state<ReturnType<typeof JobOptionsPanel>>()

  let searchTimer: ReturnType<typeof setTimeout> | undefined

  // Active filter chips (dropdown selections + text search).
  type Chip = { key: string; label: string; clear: () => void }

  function optionTitle(options: FilterOption[] | undefined, id: number): string {
    return options?.find((o) => o.id === id)?.title ?? `#${id}`
  }

  const chips = $derived.by<Chip[]>(() => {
    const list: Chip[] = []
    const query = search.trim()
    if (query) {
      list.push({
        key: "search",
        label: `Recherche : « ${query} »`,
        clear: () => {
          search = ""
          onFilterChange()
        },
      })
    }
    const groups: {
      key: string
      group: string
      value: number | null
      options: FilterOption[] | undefined
      reset: () => void
    }[] = [
      { key: "brand", group: "Marque", value: brand, options: filters?.brands, reset: () => (brand = null) },
      { key: "category", group: "Catégorie", value: category, options: filters?.categories, reset: () => (category = null) },
      { key: "season", group: "Saison", value: season, options: filters?.seasons, reset: () => (season = null) },
      { key: "supplier", group: "Fournisseur", value: supplier, options: filters?.suppliers, reset: () => (supplier = null) },
      { key: "tag", group: "Tag", value: tag, options: filters?.tags, reset: () => (tag = null) },
    ]
    for (const g of groups) {
      if (g.value === null) continue
      list.push({
        key: g.key,
        label: `${g.group} : ${optionTitle(g.options, g.value)}`,
        clear: () => {
          g.reset()
          onFilterChange()
        },
      })
    }
    return list
  })

  function clearAll() {
    search = ""
    brand = category = season = supplier = tag = null
    onFilterChange()
  }

  async function load() {
    loading = true
    errorMessage = null
    const { data, error } = await productsListProducts({
      query: {
        search: search.trim() || null,
        brand,
        category,
        season,
        supplier,
        tag,
        page,
        // Lu au moment de l'appel : suit la préférence « produits par page ».
        per_page: prefs.products_per_page,
      },
    })
    loading = false
    if (error || !data) {
      errorMessage = "Recherche impossible. Vérifiez la connexion Xano."
      products = []
      return
    }
    products = data.items
    total = data.total
    totalPages = data.total_pages
  }

  onMount(() => {
    load()
    catalogGetFilters().then(({ data }) => {
      if (data) filters = data
    })
    // Pré-sélection d'un import via `?import=ID` (routeur svelte5-router :
    // lecture simple de location.search au montage).
    const param = new URLSearchParams(window.location.search).get("import")
    const importId = param ? Number(param) : NaN
    if (Number.isFinite(importId)) {
      tab = "import"
      selectedImportId = importId
      loadImportProducts(importId)
    }
    loadImportsList()
  })

  function onFilterChange() {
    page = 1
    load()
  }

  function onSearchInput() {
    clearTimeout(searchTimer)
    searchTimer = setTimeout(() => {
      page = 1
      load()
    }, 350)
  }

  function toggle(id: number) {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    selected = next
  }

  // Le clic/l'activation d'une ligne ouvre le panneau produit ; la sélection
  // passe par la checkbox (stopPropagation).
  function onRowKeydown(event: KeyboardEvent, product: Product) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      openCatalogPanel(product)
    }
  }

  // Header "select all" only covers the currently displayed page; the Set
  // keeps selections made on other pages.
  const pageIds = $derived((products ?? []).map((p) => p.id))
  const pageSelectedCount = $derived(pageIds.filter((id) => selected.has(id)).length)
  const allPageSelected = $derived(
    pageIds.length > 0 && pageSelectedCount === pageIds.length,
  )
  const somePageSelected = $derived(pageSelectedCount > 0 && !allPageSelected)

  function togglePage() {
    const next = new Set(selected)
    if (allPageSelected) {
      for (const id of pageIds) next.delete(id)
    } else {
      for (const id of pageIds) next.add(id)
    }
    selected = next
  }

  function goToPage(next: number) {
    page = Math.max(1, Math.min(totalPages || 1, next))
    load()
  }

  function label(product: Product): string {
    return product.title?.trim() || product.reference_code || `Produit ${product.id}`
  }

  // Tillin categories come in mixed casing ("ACCESSOIRES", "Chaussures") —
  // normalize for display only.
  function displayCategory(value: string): string {
    return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase()
  }

  async function createJob() {
    if (selected.size === 0) return
    submitting = true
    const { data, error } = await jobsCreateEnrichmentJob({
      body: {
        selection: { ids: [...selected] },
        // Seules les options réellement renseignées partent dans la config.
        config: { translate, ...(optionsPanel?.collectConfig() ?? {}) },
      },
    })
    submitting = false
    if (error || !data) {
      toast.error("Création de l'enrichissement impossible.")
      return
    }
    toast.success(`Enrichissement #${data.id} créé — traitement lancé`)
    navigate(`/jobs/${data.id}`)
  }

  // --- Onglet « Par import » : produits créés dans Tillin par un import. ---
  let importsList = $state<ImportJobPublic[] | null>(null)
  let selectedImportId = $state<number | null>(null)
  let importProducts = $state<ImportProductsResponse | null>(null)
  let importLoading = $state(false)
  let importError = $state<string | null>(null)
  let linking = $state(false)
  // Références restées introuvables au dernier « Relier » (détail sous le bandeau).
  let linkNotFound = $state<string[]>([])

  async function loadImportsList() {
    const { data } = await listImports({ page: 1, page_size: 100 })
    // Seuls les imports terminés ont des produits exploitables ; l'API
    // renvoie déjà les plus récents en premier.
    importsList = (data?.items ?? []).filter((i) => i.status === "completed")
  }

  async function loadImportProducts(id: number) {
    importLoading = true
    importError = null
    const { data, error } = await getImportProducts(id)
    importLoading = false
    if (error || !data) {
      importProducts = null
      importError = "Impossible de charger les produits de cet import."
      return
    }
    importProducts = data
  }

  function changeImport(event: Event) {
    const raw = (event.currentTarget as HTMLSelectElement).value
    linkNotFound = []
    importProducts = null
    if (raw === "") {
      selectedImportId = null
      return
    }
    selectedImportId = Number(raw)
    loadImportProducts(selectedImportId)
  }

  async function linkProducts() {
    if (selectedImportId == null || linking) return
    linking = true
    const { data, error } = await linkImportProducts(selectedImportId)
    linking = false
    if (error || !data) {
      const code = (error as { code?: string } | null)?.code
      toast.error(
        code === "not_transferred"
          ? "Cet import n'a pas encore été transféré vers Tillin."
          : "Liaison aux produits Tillin impossible.",
      )
      return
    }
    linkNotFound = data.not_found
    toast.success(
      `${data.linked} relié${data.linked > 1 ? "s" : ""}, ` +
        `${data.already_linked} déjà relié${data.already_linked > 1 ? "s" : ""}, ` +
        `${data.not_found.length} introuvable${data.not_found.length > 1 ? "s" : ""}`,
    )
    await loadImportProducts(selectedImportId)
  }

  function importItemLabel(item: ImportProductItem): string {
    return item.title?.trim() || item.supplier_ref
  }

  // Lignes reliées de l'import affiché (seules sélectionnables : les ids
  // Tillin alimentent la même sélection que l'onglet Catalogue).
  const importLinkedIds = $derived(
    (importProducts?.items ?? [])
      .map((i) => i.tillin_product_id)
      .filter((v): v is number => v != null),
  )
  const importSelectedCount = $derived(
    importLinkedIds.filter((id) => selected.has(id)).length,
  )
  const allImportSelected = $derived(
    importLinkedIds.length > 0 && importSelectedCount === importLinkedIds.length,
  )

  function toggleImportPage() {
    const next = new Set(selected)
    if (allImportSelected) {
      for (const id of importLinkedIds) next.delete(id)
    } else {
      for (const id of importLinkedIds) next.add(id)
    }
    selected = next
  }

  // --- Panneau latéral produit (les deux onglets). ---
  let panelOpen = $state(false)
  let panelProductId = $state<number | null>(null)
  let panelImportLabel = $state<string | null>(null)
  let panelFallback = $state<{
    title: string | null
    supplier_ref: string
    brand: string | null
    image_url: string | null
  } | null>(null)

  function openCatalogPanel(product: Product) {
    panelProductId = product.id
    panelImportLabel = null
    panelFallback = null
    panelOpen = true
  }

  function openImportPanel(item: ImportProductItem) {
    panelImportLabel = importProducts?.file_name ?? null
    if (item.tillin_product_id != null) {
      panelProductId = item.tillin_product_id
      panelFallback = null
    } else {
      panelProductId = null
      panelFallback = {
        title: item.title,
        supplier_ref: item.supplier_ref,
        brand: item.brand,
        image_url: item.image_url,
      }
    }
    panelOpen = true
  }

  function closePanel() {
    panelOpen = false
  }

  // Enrichissement direct depuis le panneau : job à un seul produit.
  async function enrichSingle(productId: number) {
    const { data, error } = await jobsCreateEnrichmentJob({
      body: { selection: { ids: [productId] } },
    })
    if (error || !data) {
      toast.error("Création de l'enrichissement impossible.")
      return
    }
    toast.success(`Enrichissement #${data.id} créé — traitement lancé`)
    navigate(`/jobs/${data.id}`)
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Produits" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4 pb-24">
        <h1 class="font-title text-lg font-bold">Produits</h1>

        <!-- Barre d'onglets sobre (même pattern qu'EnrichmentPage). -->
        <div
          class="border-border flex gap-4 border-b"
          role="tablist"
          aria-label="Sources de produits"
        >
          {#each TABS as t (t.key)}
            <button
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              class="-mb-px cursor-pointer border-b-2 px-1 pb-2 text-sm font-medium transition-colors {tab ===
              t.key
                ? 'border-primary text-foreground'
                : 'text-muted-foreground hover:text-foreground border-transparent'}"
              onclick={() => (tab = t.key)}
            >
              {t.label}
            </button>
          {/each}
        </div>

        {#if tab === "catalog"}
        <div class="relative">
          <Search
            size={16}
            class="text-muted-foreground pointer-events-none absolute top-1/2 left-3 -translate-y-1/2"
            aria-hidden="true"
          />
          <Input
            type="search"
            placeholder="Rechercher (titre, référence…)"
            bind:value={search}
            oninput={onSearchInput}
            class="h-9 pl-9 text-sm"
          />
        </div>

        {#if filters}
          <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            <FilterSelect label="Marque" options={filters.brands ?? []} bind:value={brand} onchange={onFilterChange} />
            <FilterSelect label="Catégorie" options={filters.categories ?? []} bind:value={category} onchange={onFilterChange} />
            <FilterSelect label="Saison" options={filters.seasons ?? []} bind:value={season} onchange={onFilterChange} />
            <FilterSelect label="Fournisseur" options={filters.suppliers ?? []} bind:value={supplier} onchange={onFilterChange} />
            <FilterSelect label="Tag" options={filters.tags ?? []} bind:value={tag} onchange={onFilterChange} />
          </div>
        {/if}

        {#if chips.length > 0}
          <div class="flex flex-wrap items-center gap-1.5">
            {#each chips as chip (chip.key)}
              <span
                class="bg-muted/50 inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs"
              >
                {chip.label}
                <button
                  type="button"
                  class="text-muted-foreground hover:text-foreground -mr-0.5 cursor-pointer rounded-full p-0.5"
                  aria-label={`Retirer le filtre ${chip.label}`}
                  onclick={chip.clear}
                >
                  <X size={12} aria-hidden="true" />
                </button>
              </span>
            {/each}
            {#if chips.length >= 2}
              <button
                type="button"
                class="text-muted-foreground hover:text-foreground hover:bg-muted/50 cursor-pointer rounded-full border border-dashed px-2.5 py-0.5 text-xs transition-colors"
                onclick={clearAll}
              >
                Tout effacer
              </button>
            {/if}
          </div>
        {/if}

        {#if errorMessage}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
        {/if}

        <div class="text-muted-foreground flex items-center justify-between text-xs">
          <span>{total} produit{total > 1 ? "s" : ""}</span>
          {#if selected.size > 0}
            <button
              type="button"
              class="text-primary cursor-pointer underline underline-offset-2"
              onclick={() => (selected = new Set())}
            >
              Vider la sélection ({selected.size})
            </button>
          {/if}
        </div>

        {#if products === null}
          <Skeleton class="h-16 w-full" />
          <Skeleton class="h-16 w-full" />
          <Skeleton class="h-16 w-full" />
        {:else if products.length === 0}
          <Card>
            <CardContent class="flex flex-col items-center gap-3 py-8 text-center">
              <span class="bg-muted flex size-14 items-center justify-center rounded-full">
                <PackageSearch size={24} class="text-muted-foreground" aria-hidden="true" />
              </span>
              <p class="text-muted-foreground text-sm">
                {chips.length > 0
                  ? "Aucun produit ne correspond à ces filtres."
                  : "Aucun produit ne correspond."}
              </p>
              {#if chips.length > 0}
                <Button variant="outline" size="sm" onclick={clearAll}>
                  Réinitialiser les filtres
                </Button>
              {/if}
            </CardContent>
          </Card>
        {:else}
          <Card class="py-0">
            <CardContent class="overflow-x-auto px-0">
              <table class="w-full min-w-xl text-sm" class:opacity-60={loading}>
                <thead>
                  <tr class="border-border border-b">
                    <th class="w-10 px-4 py-2.5">
                      <input
                        type="checkbox"
                        class="accent-primary block size-4"
                        aria-label="Sélectionner tous les produits de la page"
                        checked={allPageSelected}
                        indeterminate={somePageSelected}
                        onchange={togglePage}
                      />
                    </th>
                    <th class="w-14 px-2 py-2.5">
                      <span class="sr-only">Image</span>
                    </th>
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">
                      Produit
                    </th>
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">
                      Marque
                    </th>
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">
                      Catégorie
                    </th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">
                      Variantes
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {#each products as product (product.id)}
                    {@const checked = selected.has(product.id)}
                    <tr
                      role="button"
                      tabindex="0"
                      aria-label={`Voir ${label(product)}`}
                      class="border-border hover:bg-muted/50 focus-visible:bg-muted/50 cursor-pointer border-b outline-none transition-colors last:border-b-0 {checked
                        ? 'bg-primary/5'
                        : ''}"
                      onclick={() => openCatalogPanel(product)}
                      onkeydown={(e) => onRowKeydown(e, product)}
                    >
                      <td class="px-4 {cellPad}">
                        <input
                          type="checkbox"
                          class="accent-primary block size-4"
                          aria-label={`Sélectionner ${label(product)}`}
                          {checked}
                          onclick={(e) => e.stopPropagation()}
                          onchange={() => toggle(product.id)}
                        />
                      </td>
                      <td class="px-2 {cellPad}">
                        {#if product.images?.[0]?.url}
                          <img
                            src={product.images[0].url}
                            alt=""
                            loading="lazy"
                            class="bg-muted h-12.5 w-10 rounded object-cover"
                          />
                        {:else}
                          <span
                            class="bg-muted flex h-12.5 w-10 items-center justify-center rounded"
                          >
                            <ImageIcon
                              size={16}
                              class="text-muted-foreground"
                              aria-hidden="true"
                            />
                          </span>
                        {/if}
                      </td>
                      <td class="px-4 {cellPad}">
                        <div class="flex min-w-0 flex-col gap-0.5">
                          <span class="line-clamp-2 font-medium">{label(product)}</span>
                          {#if product.reference_code && product.reference_code !== label(product)}
                            <span class="text-muted-foreground font-mono text-xs">
                              {product.reference_code}
                            </span>
                          {/if}
                        </div>
                      </td>
                      <td class="px-4 {cellPad} whitespace-nowrap">
                        {product.brand?.name ?? "—"}
                      </td>
                      <td class="px-4 {cellPad}">
                        {#if product.category}
                          <span
                            class="bg-muted text-muted-foreground rounded-full px-1.5 py-0.5 text-xs whitespace-nowrap"
                          >
                            {displayCategory(product.category)}
                          </span>
                        {:else}
                          <span class="text-muted-foreground">—</span>
                        {/if}
                      </td>
                      <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                        {product.variants?.length ?? 0}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </CardContent>
          </Card>

          <!-- Pagination -->
          <div class="flex items-center justify-between gap-2 pt-1">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1 || loading}
              onclick={() => goToPage(page - 1)}
            >
              Précédent
            </Button>
            <span class="text-muted-foreground font-mono text-xs">
              {page} / {totalPages || 1}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages || loading}
              onclick={() => goToPage(page + 1)}
            >
              Suivant
            </Button>
          </div>
        {/if}
        {:else}
          <!-- Onglet « Par import » : produits créés dans Tillin par un import. -->
          <div class="flex flex-col gap-1.5 sm:max-w-80">
            <Label for="import-select">Import</Label>
            {#if importsList === null}
              <Skeleton class="h-9 w-full" />
            {:else if importsList.length === 0}
              <p class="text-muted-foreground text-xs">
                Aucun import terminé pour l'instant.
              </p>
            {:else}
              <select
                id="import-select"
                class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                value={selectedImportId == null ? "" : String(selectedImportId)}
                onchange={changeImport}
              >
                <option value="">Choisir un import…</option>
                {#each importsList as imp (imp.id)}
                  <option value={String(imp.id)}>{imp.file_name}</option>
                {/each}
              </select>
            {/if}
          </div>

          {#if importError}
            <p class="text-destructive text-xs" role="alert">{importError}</p>
          {:else if selectedImportId === null}
            <Card>
              <CardContent class="text-muted-foreground py-8 text-center text-sm">
                Choisissez un import pour voir les produits créés dans Tillin.
              </CardContent>
            </Card>
          {:else if importLoading || importProducts === null}
            <Skeleton class="h-16 w-full" />
            <Skeleton class="h-16 w-full" />
            <Skeleton class="h-16 w-full" />
          {:else}
            {#if importProducts.unlinked_count > 0}
              <!-- Bandeau : des items transférés ne sont pas encore reliés. -->
              <div
                class="border-border bg-muted/50 flex flex-wrap items-center justify-between gap-2 rounded-md border p-3"
              >
                <p class="text-muted-foreground text-xs">
                  {importProducts.unlinked_count}
                  produit{importProducts.unlinked_count > 1 ? "s" : ""} de cet import
                  {importProducts.unlinked_count > 1 ? "ne sont pas reliés" : "n'est pas relié"}
                  aux produits Tillin.
                </p>
                <Button size="sm" disabled={linking} onclick={linkProducts}>
                  {#if linking}
                    <LoaderCircle size={14} class="animate-spin" aria-hidden="true" />
                  {:else}
                    <Link2 size={14} aria-hidden="true" />
                  {/if}
                  Relier aux produits Tillin
                </Button>
              </div>
            {/if}
            {#if linkNotFound.length > 0}
              <p class="text-warning-foreground text-xs">
                Références introuvables dans Tillin : {linkNotFound.join(", ")}
              </p>
            {/if}

            <div class="text-muted-foreground flex items-center justify-between text-xs">
              <span>
                {importProducts.items.length}
                produit{importProducts.items.length > 1 ? "s" : ""} —
                {importProducts.linked_count} relié{importProducts.linked_count > 1 ? "s" : ""}
              </span>
              {#if selected.size > 0}
                <button
                  type="button"
                  class="text-primary cursor-pointer underline underline-offset-2"
                  onclick={() => (selected = new Set())}
                >
                  Vider la sélection ({selected.size})
                </button>
              {/if}
            </div>

            {#if importProducts.items.length === 0}
              <Card>
                <CardContent class="text-muted-foreground py-8 text-center text-sm">
                  Aucun produit dans cet import.
                </CardContent>
              </Card>
            {:else}
              <Card class="py-0">
                <CardContent class="overflow-x-auto px-0">
                  <table class="w-full min-w-xl text-sm">
                    <thead>
                      <tr class="border-border border-b">
                        <th class="w-10 px-4 py-2.5">
                          <input
                            type="checkbox"
                            class="accent-primary block size-4"
                            aria-label="Sélectionner tous les produits reliés"
                            disabled={importLinkedIds.length === 0}
                            checked={allImportSelected}
                            indeterminate={importSelectedCount > 0 && !allImportSelected}
                            onchange={toggleImportPage}
                          />
                        </th>
                        <th class="w-14 px-2 py-2.5">
                          <span class="sr-only">Image</span>
                        </th>
                        <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">
                          Titre
                        </th>
                        <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">
                          Référence
                        </th>
                        <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">
                          Variantes
                        </th>
                        <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">
                          État
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each importProducts.items as item (item.item_id)}
                        {@const linked = item.tillin_product_id != null}
                        {@const checked = linked && selected.has(item.tillin_product_id ?? -1)}
                        <tr
                          role="button"
                          tabindex="0"
                          aria-label={`Voir ${importItemLabel(item)}`}
                          class="border-border hover:bg-muted/50 focus-visible:bg-muted/50 cursor-pointer border-b outline-none transition-colors last:border-b-0 {checked
                            ? 'bg-primary/5'
                            : ''}"
                          onclick={() => openImportPanel(item)}
                          onkeydown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault()
                              openImportPanel(item)
                            }
                          }}
                        >
                          <td class="px-4 {cellPad}">
                            {#if linked && item.tillin_product_id != null}
                              <input
                                type="checkbox"
                                class="accent-primary block size-4"
                                aria-label={`Sélectionner ${importItemLabel(item)}`}
                                {checked}
                                onclick={(e) => e.stopPropagation()}
                                onchange={() => toggle(item.tillin_product_id ?? -1)}
                              />
                            {/if}
                          </td>
                          <td class="px-2 {cellPad}">
                            {#if item.image_url}
                              <img
                                src={item.image_url}
                                alt=""
                                loading="lazy"
                                class="bg-muted h-12.5 w-10 rounded object-cover"
                              />
                            {:else}
                              <span
                                class="bg-muted flex h-12.5 w-10 items-center justify-center rounded"
                              >
                                <ImageIcon
                                  size={16}
                                  class="text-muted-foreground"
                                  aria-hidden="true"
                                />
                              </span>
                            {/if}
                          </td>
                          <td class="px-4 {cellPad}">
                            <div class="flex min-w-0 flex-col gap-0.5">
                              <span class="line-clamp-2 font-medium">{importItemLabel(item)}</span>
                              {#if item.brand}
                                <span class="text-muted-foreground text-xs">{item.brand}</span>
                              {/if}
                            </div>
                          </td>
                          <td class="px-4 {cellPad} font-mono text-xs whitespace-nowrap">
                            {item.supplier_ref}
                          </td>
                          <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                            {item.variant_count}
                          </td>
                          <td class="px-4 {cellPad} whitespace-nowrap">
                            {#if linked}
                              <span
                                class="bg-success text-success-foreground inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
                              >
                                Relié
                              </span>
                            {:else if item.status !== "applied"}
                              <StatusBadge status={item.status} context="import" />
                            {:else}
                              <span
                                class="bg-muted text-muted-foreground inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
                              >
                                Non relié
                              </span>
                            {/if}
                          </td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            {/if}
          {/if}
        {/if}
      </div>

      <!-- Sticky selection/action bar (offset by the sidebar width on desktop) -->
      {#if selected.size > 0}
        <div class="border-border bg-card fixed inset-x-0 bottom-0 border-t sm:left-60">
          <!-- Panneau d'options replié/déplié (monté en permanence : les
               saisies survivent au repli, jusqu'à vider la sélection). -->
          <div
            class="border-border max-h-[55vh] overflow-y-auto border-b"
            hidden={!optionsOpen}
          >
            <div class="mx-auto max-w-4xl p-3">
              <JobOptionsPanel bind:this={optionsPanel} />
            </div>
          </div>
          <div class="p-3">
            <div class="mx-auto flex max-w-4xl items-center gap-3 sm:justify-end">
              <label class="text-muted-foreground flex items-center gap-1.5 text-xs">
                <input type="checkbox" bind:checked={translate} class="accent-primary size-3.5" />
                Traduire
              </label>
              <Button
                variant="outline"
                aria-expanded={optionsOpen}
                onclick={() => (optionsOpen = !optionsOpen)}
              >
                Options
                {#if optionsOpen}
                  <ChevronDown size={14} aria-hidden="true" data-icon="inline-end" />
                {:else}
                  <ChevronUp size={14} aria-hidden="true" data-icon="inline-end" />
                {/if}
              </Button>
              <Button class="flex-1 sm:min-w-44 sm:flex-none" disabled={submitting} onclick={createJob}>
                Enrichir la sélection ({selected.size})
              </Button>
            </div>
          </div>
        </div>
      {/if}

      <!-- Panneau latéral produit (fiche Tillin ou fallback d'import). -->
      {#if panelOpen}
        <ProductPanel
          productId={panelProductId}
          importLabel={panelImportLabel}
          fallback={panelFallback}
          onClose={closePanel}
          onEnrich={enrichSingle}
        />
      {/if}
    </AppShell>
  {/snippet}
</RequireAuth>
