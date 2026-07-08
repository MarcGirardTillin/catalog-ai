<script lang="ts">
  import ImageIcon from "@lucide/svelte/icons/image"
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
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import FilterSelect from "@/lib/components/app/FilterSelect.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"

  let { appName }: { appName: string } = $props()

  const PER_PAGE = 20

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
        per_page: PER_PAGE,
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

  function onRowKeydown(event: KeyboardEvent, id: number) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      toggle(id)
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
      body: { selection: { ids: [...selected] }, config: { translate } },
    })
    submitting = false
    if (error || !data) {
      toast.error("Création du job impossible.")
      return
    }
    toast.success(`Job #${data.id} créé — traitement lancé`)
    navigate(`/jobs/${data.id}`)
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Produits" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4 pb-24">
        <h1 class="font-title text-lg font-bold">Sélectionner des produits</h1>

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
                      aria-pressed={checked}
                      aria-label={`Sélectionner ${label(product)}`}
                      class="border-border hover:bg-muted/50 focus-visible:bg-muted/50 cursor-pointer border-b outline-none transition-colors last:border-b-0 {checked
                        ? 'bg-primary/5'
                        : ''}"
                      onclick={() => toggle(product.id)}
                      onkeydown={(e) => onRowKeydown(e, product.id)}
                    >
                      <td class="px-4 py-2">
                        <input
                          type="checkbox"
                          class="accent-primary block size-4"
                          aria-label={`Sélectionner ${label(product)}`}
                          {checked}
                          onclick={(e) => e.stopPropagation()}
                          onchange={() => toggle(product.id)}
                        />
                      </td>
                      <td class="px-2 py-2">
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
                      <td class="px-4 py-2">
                        <div class="flex min-w-0 flex-col gap-0.5">
                          <span class="line-clamp-2 font-medium">{label(product)}</span>
                          {#if product.reference_code && product.reference_code !== label(product)}
                            <span class="text-muted-foreground font-mono text-xs">
                              {product.reference_code}
                            </span>
                          {/if}
                        </div>
                      </td>
                      <td class="px-4 py-2 whitespace-nowrap">
                        {product.brand?.name ?? "—"}
                      </td>
                      <td class="px-4 py-2">
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
                      <td class="px-4 py-2 text-right whitespace-nowrap tabular-nums">
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
      </div>

      <!-- Sticky selection/action bar (offset by the sidebar width on desktop) -->
      {#if selected.size > 0}
        <div class="border-border bg-card fixed inset-x-0 bottom-0 border-t p-3 sm:left-60">
          <div class="mx-auto flex max-w-4xl items-center gap-3 sm:justify-end">
            <label class="text-muted-foreground flex items-center gap-1.5 text-xs">
              <input type="checkbox" bind:checked={translate} class="accent-primary size-3.5" />
              Traduire
            </label>
            <Button class="flex-1 sm:min-w-44 sm:flex-none" disabled={submitting} onclick={createJob}>
              Créer un job ({selected.size})
            </Button>
          </div>
        </div>
      {/if}
    </AppShell>
  {/snippet}
</RequireAuth>
