<script lang="ts">
  // Studio images d'un produit : traitements à la carte (défauts du compte
  // pré-remplis), lancement en parallèle sur la sélection, avant/après avec
  // poids, repositionnement manuel, renommage et enregistrement vers Tillin.
  // Le panneau produit garde l'action rapide ; tout le réglage fin vit ici.
  import ArrowLeft from "@lucide/svelte/icons/arrow-left"
  import Images from "@lucide/svelte/icons/images"
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import { settingsReadAccountSettings, type ProductImage } from "@/client"
  import {
    fetchAssetPreviews,
    normalizeImage,
    saveAsset,
    waitForAsset,
  } from "@/lib/api/imaging"
  import { getProduct, type ProductDetail } from "@/lib/api/products"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import AssetResult, { type Work } from "@/lib/components/imaging/AssetResult.svelte"
  import ImageGrid, { type WorkStatus } from "@/lib/components/imaging/ImageGrid.svelte"
  import ProcessingOptions, {
    type StudioOptions,
  } from "@/lib/components/imaging/ProcessingOptions.svelte"

  let { appName, id }: { appName: string; id: string } = $props()

  const productId = $derived(Number(id))

  // --- Produit + images sources ---
  let product = $state<ProductDetail | null>(null)
  let loadFailed = $state(false)

  async function loadProduct() {
    const { data, error } = await getProduct(productId)
    if (error || !data) {
      loadFailed = true
      return
    }
    product = data
  }

  $effect(() => {
    void productId
    loadProduct()
  })

  const images = $derived(product?.images ?? [])

  // --- Options de traitement (défauts du compte, modifiables à la volée) ---
  let options = $state<StudioOptions>({
    remove_bg: true,
    bg_color: "FFFFFF",
    ratio: "4:5",
    center: true,
    format: "webp",
    quality: 80,
    max_kb: 300,
  })
  let hasImageTemplate = $state(false)

  $effect(() => {
    settingsReadAccountSettings().then(({ data }) => {
      if (!data) return
      options = {
        remove_bg: data.imaging_remove_bg ?? true,
        bg_color: data.imaging_bg_color ?? "FFFFFF",
        ratio: data.imaging_ratio ?? "4:5",
        center: data.imaging_center ?? true,
        format: data.imaging_format ?? "webp",
        quality: data.imaging_quality ?? 80,
        max_kb: data.imaging_max_kb ?? 300,
      }
      hasImageTemplate = Boolean(data.image_title_template)
    })
  })

  // --- Travaux par image source (clé = URL) ---
  let works = $state<Record<string, Work>>({})
  let selected = $state<string[]>([])

  const statuses = $derived(
    Object.fromEntries(
      Object.entries(works).map(([url, work]) => [url, work.status]),
    ) as Record<string, WorkStatus>,
  )
  const runningCount = $derived(
    Object.values(works).filter((w) => w.status === "running").length,
  )
  const results = $derived(
    images.filter((image) => {
      const status = works[image.url]?.status
      return status && status !== "idle"
    }),
  )

  function toggleSelected(url: string) {
    selected = selected.includes(url)
      ? selected.filter((u) => u !== url)
      : [...selected, url]
  }

  function selectAll() {
    selected = selected.length === images.length ? [] : images.map((i) => i.url)
  }

  function freshWork(previous?: Work): Work {
    if (previous?.previewUrl) URL.revokeObjectURL(previous.previewUrl)
    return {
      status: "running",
      asset: null,
      previewUrl: null,
      error: null,
      filename: previous?.filename ?? "",
      replace: previous?.replace ?? false,
      offsetX: 0,
      offsetY: 0,
      scale: 1,
      rendering: false,
      saving: false,
    }
  }

  async function runOne(image: ProductImage) {
    const key = image.url
    if (works[key]?.status === "running") return
    works[key] = freshWork(works[key])
    const { data, error } = await normalizeImage(
      productId,
      image.url,
      image.id ?? null,
      { ...options },
    )
    if (error || !data) {
      works[key].status = "failed"
      works[key].error =
        "Lancement impossible (service d'imagerie indisponible ?)."
      return
    }
    const final = await waitForAsset(data.id, { intervalMs: 1500 })
    if (!final || final.status !== "completed") {
      works[key].status = "failed"
      works[key].error = final?.error ?? "Le traitement n'a pas abouti."
      return
    }
    const previews = await fetchAssetPreviews(final)
    works[key].asset = final
    works[key].previewUrl = previews[0] ?? null
    works[key].status = "done"
  }

  async function runSelected() {
    const targets = images.filter((image) => selected.includes(image.url))
    if (targets.length === 0) return
    selected = []
    await Promise.all(targets.map((image) => runOne(image)))
  }

  async function saveOne(image: ProductImage) {
    const work = works[image.url]
    const asset = work?.asset
    if (!work || !asset || work.saving) return
    work.saving = true
    const replace = work.replace && asset.source_product_image_id != null
    const { data, error } = await saveAsset(asset.id, replace, [
      work.filename.trim() || null,
    ])
    work.saving = false
    if (error || !data) {
      toast.error("Échec de l'enregistrement dans Tillin.")
      return
    }
    work.status = "saved"
    work.asset = { ...asset, can_render: false }
    toast.success(
      `Image enregistrée${data.deactivated > 0 ? ", originale remplacée" : ""}`,
    )
    await loadProduct() // la galerie Tillin a changé
  }

  // Révoque les aperçus blob au démontage.
  $effect(() => {
    return () => {
      for (const work of Object.values(works)) {
        if (work.previewUrl) URL.revokeObjectURL(work.previewUrl)
      }
    }
  })
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell
      {appName}
      {user}
      breadcrumbs={[
        { label: "Produits", href: "/products" },
        { label: product?.title ?? `Produit #${id}` },
        { label: "Studio images" },
      ]}
    >
      <div class="mx-auto flex max-w-5xl flex-col gap-3 p-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex min-w-0 items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              aria-label="Retour aux produits"
              onclick={() => navigate("/products")}
            >
              <ArrowLeft size={16} aria-hidden="true" />
            </Button>
            <h1
              class="font-title min-w-0 truncate text-lg font-bold"
              title={product?.title}
            >
              Studio images{product ? ` — ${product.title}` : ""}
            </h1>
          </div>
        </div>

        {#if loadFailed}
          <p class="text-destructive text-xs" role="alert">
            Impossible de charger le produit.
          </p>
        {:else if product === null}
          <Skeleton class="h-24 w-full" />
          <Skeleton class="h-40 w-full" />
        {:else if images.length === 0}
          <Card>
            <CardContent class="flex flex-col items-center gap-3 py-10 text-center">
              <span
                class="bg-muted text-muted-foreground flex size-10 items-center justify-center rounded-full"
                aria-hidden="true"
              >
                <Images size={18} />
              </span>
              <p class="text-muted-foreground text-sm">
                Ce produit n'a pas encore d'image — ajoutez-en depuis la fiche
                produit.
              </p>
            </CardContent>
          </Card>
        {:else}
          <!-- Options de traitement -->
          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">Traitements</CardTitle>
              <CardDescription class="text-muted-foreground text-xs">
                Pré-remplis avec vos réglages ; seul le détourage consomme des
                images du service. Modifiables avant chaque lancement.
              </CardDescription>
            </CardHeader>
            <CardContent class="flex flex-col gap-3">
              <ProcessingOptions bind:options disabled={runningCount > 0} />
            </CardContent>
          </Card>

          <!-- Grille de sélection -->
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h2 class="font-title text-sm font-bold">
              Images du produit ({images.length})
            </h2>
            <div class="flex items-center gap-2">
              <Button variant="ghost" size="sm" onclick={selectAll}>
                {selected.length === images.length
                  ? "Tout désélectionner"
                  : "Tout sélectionner"}
              </Button>
              <Button
                size="sm"
                disabled={selected.length === 0 || runningCount > 0}
                onclick={runSelected}
              >
                {runningCount > 0
                  ? `Traitement… (${runningCount})`
                  : `Normaliser la sélection (${selected.length})`}
              </Button>
            </div>
          </div>
          <ImageGrid
            {images}
            {statuses}
            {selected}
            onToggle={toggleSelected}
            disabled={runningCount > 0}
          />

          <!-- Résultats -->
          {#if results.length > 0}
            <h2 class="font-title mt-1 text-sm font-bold">Résultats</h2>
            {#each results as image (image.url)}
              {@const work = works[image.url]}
              {#if work.status === "running"}
                <Card size="sm">
                  <CardContent class="text-muted-foreground py-6 text-center text-sm">
                    Traitement en cours…
                  </CardContent>
                </Card>
              {:else if work.status === "failed"}
                <Card size="sm">
                  <CardContent class="flex items-center justify-between gap-3 py-4">
                    <p class="text-destructive text-sm" role="alert">
                      {work.error ?? "Traitement échoué."}
                    </p>
                    <Button variant="outline" size="sm" onclick={() => runOne(image)}>
                      Réessayer
                    </Button>
                  </CardContent>
                </Card>
              {:else}
                <AssetResult
                  {image}
                  {work}
                  filenamePlaceholder={hasImageTemplate
                    ? "selon le modèle de titre d'image"
                    : ""}
                  onSave={() => saveOne(image)}
                />
              {/if}
            {/each}
          {/if}
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
