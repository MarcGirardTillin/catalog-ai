<script lang="ts">
  // Sites web de référence par marque : consultation + édition inline.
  // Monté paresseusement à la première ouverture de l'onglet Marques
  // (liste potentiellement longue).
  import { onMount } from "svelte"
  import { toast } from "svelte-sonner"

  import { listBrands, updateBrandWebsiteUrls } from "@/lib/api/brands"
  import type { BrandPublic } from "@/lib/api/brands"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Separator } from "@/lib/components/ui/separator"
  import { Skeleton } from "@/lib/components/ui/skeleton"

  let brands = $state<BrandPublic[] | null>(null)
  let loadFailed = $state(false)
  let query = $state("")

  // Édition inline : une seule marque dépliée à la fois.
  let editingId = $state<number | null>(null)
  let urlsRaw = $state("")
  let saving = $state(false)

  async function load() {
    brands = null
    loadFailed = false
    const { data, error } = await listBrands()
    if (error || data === undefined) {
      loadFailed = true
      brands = []
      return
    }
    brands = data
  }

  onMount(load)

  // Filtre client-side sur le nom (l'ordre du serveur est conservé).
  const filtered = $derived.by(() => {
    const needle = query.trim().toLowerCase()
    const all = brands ?? []
    if (needle === "") return all
    return all.filter((b) => (b.name ?? "").toLowerCase().includes(needle))
  })

  function toggleEdit(brand: BrandPublic) {
    if (editingId === brand.id) {
      editingId = null
      return
    }
    editingId = brand.id
    urlsRaw = brand.website_urls.join("\n")
  }

  async function saveUrls(brand: BrandPublic) {
    const urls = urlsRaw
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line !== "")
    saving = true
    const { data, error } = await updateBrandWebsiteUrls(brand.id, urls)
    saving = false
    if (error || data === undefined) {
      toast.error("Enregistrement impossible.")
      return
    }
    // Fusion, pas remplacement : la réponse du PUT ne porte pas le nom (le
    // backend ne le relit pas) — l'écraser rendait la marque « Sans nom »,
    // que le filtre de recherche actif faisait alors disparaître de la liste.
    brands = (brands ?? []).map((b) =>
      b.id === data.id ? { ...b, website_urls: data.website_urls } : b,
    )
    editingId = null
    toast.success("Sites enregistrés")
  }
</script>

<Card size="sm">
  <CardHeader>
    <CardTitle class="font-title text-sm">Sites web des marques</CardTitle>
    <CardDescription class="text-muted-foreground text-xs">
      Ces sites sont utilisés pour retrouver la page produit officielle lors de
      l'enrichissement.
    </CardDescription>
  </CardHeader>
  <CardContent class="flex flex-col gap-3">
    {#if brands === null}
      <Skeleton class="h-9 w-full" />
      <Skeleton class="h-12 w-full" />
      <Skeleton class="h-12 w-full" />
    {:else if loadFailed}
      <div class="flex flex-col items-start gap-2">
        <p class="text-destructive text-xs" role="alert">
          Impossible de charger les marques.
        </p>
        <Button variant="secondary" size="sm" onclick={load}>Réessayer</Button>
      </div>
    {:else if brands.length === 0}
      <p class="text-muted-foreground text-sm">Aucune marque pour l'instant.</p>
    {:else}
      <div class="flex flex-col gap-1.5 sm:max-w-80">
        <Label for="brand-search">Rechercher une marque</Label>
        <Input id="brand-search" placeholder="Ex. Petit Bateau" bind:value={query} />
      </div>

      {#if filtered.length === 0}
        <p class="text-muted-foreground text-sm">Aucune marque ne correspond.</p>
      {:else}
        <ul class="flex flex-col">
          {#each filtered as brand, index (brand.id)}
            {#if index > 0}
              <Separator />
            {/if}
            <li class="flex flex-col py-2.5">
              <button
                type="button"
                class="flex cursor-pointer items-start justify-between gap-3 text-left"
                aria-expanded={editingId === brand.id}
                onclick={() => toggleEdit(brand)}
              >
                <div class="flex min-w-0 flex-col gap-1">
                  <span class="text-sm font-medium">
                    {#if brand.name}
                      {brand.name}
                    {:else}
                      <span class="text-muted-foreground italic">Sans nom</span>
                    {/if}
                  </span>
                  {#if brand.website_urls.length > 0}
                    <div class="flex flex-wrap items-center gap-1">
                      {#each brand.website_urls as url (url)}
                        <span
                          class="bg-muted text-muted-foreground max-w-72 truncate rounded-full px-1.5 py-0.5 font-mono text-xs"
                        >
                          {url}
                        </span>
                      {/each}
                    </div>
                  {:else}
                    <span class="text-muted-foreground text-xs italic">Aucun site</span>
                  {/if}
                </div>
                <span class="text-muted-foreground shrink-0 text-xs whitespace-nowrap">
                  {brand.website_urls.length}
                  site{brand.website_urls.length > 1 ? "s" : ""}
                </span>
              </button>

              {#if editingId === brand.id}
                <div class="flex flex-col gap-2 pt-2">
                  <textarea
                    rows="3"
                    aria-label={`Sites web de ${brand.name ?? "la marque"}`}
                    class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content max-h-60 min-h-20 w-full resize-none rounded-md border p-2.5 font-mono text-xs transition-colors outline-none focus-visible:ring-1"
                    placeholder={"Une URL par ligne, ex.\nhttps://www.marque.com"}
                    bind:value={urlsRaw}
                  ></textarea>
                  <div class="flex items-center justify-end gap-2">
                    <Button variant="ghost" size="sm" onclick={() => (editingId = null)}>
                      Annuler
                    </Button>
                    <Button size="sm" disabled={saving} onclick={() => saveUrls(brand)}>
                      {saving ? "Enregistrement…" : "Enregistrer"}
                    </Button>
                  </div>
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    {/if}
  </CardContent>
</Card>
