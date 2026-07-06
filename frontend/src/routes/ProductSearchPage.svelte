<script lang="ts">
  import { onMount } from "svelte"
  import { navigate } from "svelte5-router"

  import {
    catalogGetFilters,
    jobsCreateEnrichmentJob,
    productsListProducts,
  } from "@/client"
  import type { CatalogFilters, Product } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppHeader from "@/lib/components/app/AppHeader.svelte"
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

  const activeFilterCount = $derived(
    [brand, category, season, supplier, tag].filter((v) => v !== null).length,
  )

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

  function clearFilters() {
    brand = category = season = supplier = tag = null
    onFilterChange()
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

  function goToPage(next: number) {
    page = Math.max(1, Math.min(totalPages || 1, next))
    load()
  }

  function label(product: Product): string {
    return product.title?.trim() || product.reference_code || `Produit ${product.id}`
  }

  async function createJob() {
    if (selected.size === 0) return
    submitting = true
    const { data, error } = await jobsCreateEnrichmentJob({
      body: { selection: { ids: [...selected] }, config: { translate } },
    })
    submitting = false
    if (error || !data) {
      errorMessage = "Création du job impossible."
      return
    }
    navigate(`/jobs/${data.id}`)
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <div class="bg-background min-h-dvh">
      <AppHeader {appName} {user} />

      <main class="mx-auto flex max-w-2xl flex-col gap-3 p-4 pb-24">
        <h1 class="font-title text-lg font-bold">Sélectionner des produits</h1>

        <Input
          type="search"
          placeholder="Rechercher (titre, référence…)"
          bind:value={search}
          oninput={onSearchInput}
          class="h-10 text-sm"
        />

        {#if filters}
          <div class="flex flex-col gap-2">
            <div class="flex flex-wrap gap-2">
              <FilterSelect label="Marque" options={filters.brands ?? []} bind:value={brand} onchange={onFilterChange} />
              <FilterSelect label="Catégorie" options={filters.categories ?? []} bind:value={category} onchange={onFilterChange} />
              <FilterSelect label="Saison" options={filters.seasons ?? []} bind:value={season} onchange={onFilterChange} />
            </div>
            <div class="flex flex-wrap items-end gap-2">
              <FilterSelect label="Fournisseur" options={filters.suppliers ?? []} bind:value={supplier} onchange={onFilterChange} />
              <FilterSelect label="Tag" options={filters.tags ?? []} bind:value={tag} onchange={onFilterChange} />
              {#if activeFilterCount > 0}
                <Button variant="ghost" size="sm" class="h-9" onclick={clearFilters}>
                  Réinitialiser ({activeFilterCount})
                </Button>
              {/if}
            </div>
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
            <CardContent class="text-muted-foreground py-6 text-center text-sm">
              Aucun produit ne correspond.
            </CardContent>
          </Card>
        {:else}
          <ul class="flex flex-col gap-2" class:opacity-60={loading}>
            {#each products as product (product.id)}
              {@const checked = selected.has(product.id)}
              <li>
                <label
                  class="border-border bg-card hover:ring-primary/40 flex cursor-pointer items-center gap-3 rounded-lg border p-3 ring-1 ring-transparent transition-shadow"
                  class:ring-primary={checked}
                >
                  <input
                    type="checkbox"
                    class="accent-primary size-4 shrink-0"
                    {checked}
                    onchange={() => toggle(product.id)}
                  />
                  {#if product.images?.[0]?.url}
                    <img
                      src={product.images[0].url}
                      alt=""
                      loading="lazy"
                      class="bg-muted size-12 shrink-0 rounded-md object-cover"
                    />
                  {/if}
                  <div class="flex min-w-0 flex-col gap-0.5">
                    <span class="truncate text-sm font-medium">{label(product)}</span>
                    {#if product.brand?.name || product.category}
                      <span class="flex flex-wrap items-center gap-1.5 text-xs">
                        {#if product.brand?.name}
                          <span class="text-foreground font-medium">{product.brand.name}</span>
                        {/if}
                        {#if product.category}
                          <span class="bg-muted text-muted-foreground rounded-full px-1.5 py-0.5">
                            {product.category}
                          </span>
                        {/if}
                      </span>
                    {/if}
                    <span class="text-muted-foreground flex flex-wrap gap-x-2 text-xs">
                      <span class="font-mono">#{product.id}</span>
                      {#if product.reference_code}
                        <span class="font-mono">{product.reference_code}</span>
                      {/if}
                      <span>
                        {product.variants?.length ?? 0} variante{(product.variants?.length ?? 0) > 1 ? "s" : ""}
                      </span>
                    </span>
                  </div>
                </label>
              </li>
            {/each}
          </ul>

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
      </main>

      <!-- Sticky selection/action bar -->
      {#if selected.size > 0}
        <div class="border-border bg-card fixed inset-x-0 bottom-0 border-t p-3">
          <div class="mx-auto flex max-w-2xl items-center gap-3">
            <label class="text-muted-foreground flex items-center gap-1.5 text-xs">
              <input type="checkbox" bind:checked={translate} class="accent-primary size-3.5" />
              Traduire
            </label>
            <Button class="flex-1" disabled={submitting} onclick={createJob}>
              Créer un job ({selected.size})
            </Button>
          </div>
        </div>
      {/if}
    </div>
  {/snippet}
</RequireAuth>
