<script lang="ts">
  // Studio images d'un produit : traitements à la carte (défauts du compte
  // pré-remplis), lancement en parallèle sur la sélection, avant/après avec
  // poids, repositionnement manuel, renommage et enregistrement vers Tillin.
  // Le panneau produit garde l'action rapide ; tout le réglage fin vit ici.
  import ArrowLeft from "@lucide/svelte/icons/arrow-left"
  import Images from "@lucide/svelte/icons/images"
  import { createQuery, useQueryClient } from "@tanstack/svelte-query"
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import { settingsReadAccountSettings, type ProductImage } from "@/client"
  import {
    discardAsset,
    fetchAssetPreviews,
    generateModelImage,
    listAssets,
    normalizeImage,
    saveAsset,
    waitForAsset,
    type ImageAssetPublic,
  } from "@/lib/api/imaging"
  import { insufficientCreditsMessage } from "@/lib/api/credits"
  import { getProduct } from "@/lib/api/products"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { Select } from "@/lib/components/ui/select"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import { TabBar } from "@/lib/components/ui/tabs"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import AssetResult, { type Work } from "@/lib/components/imaging/AssetResult.svelte"
  import GenerationOptions, {
    type GenerationConfig,
  } from "@/lib/components/imaging/GenerationOptions.svelte"
  import ImageGrid, { type WorkStatus } from "@/lib/components/imaging/ImageGrid.svelte"
  import ProcessingOptions, {
    type StudioOptions,
  } from "@/lib/components/imaging/ProcessingOptions.svelte"

  let { appName, id }: { appName: string; id: string } = $props()

  const productId = $derived(Number(id))

  // --- Produit + images sources (cache TanStack ; l'id est dans la clé) ---
  const queryClient = useQueryClient()
  const productQuery = createQuery(() => ({
    queryKey: ["product", productId],
    queryFn: async () => {
      const { data, error } = await getProduct(productId)
      if (error || !data) throw new Error("product_load_failed")
      return data
    },
  }))
  const product = $derived(productQuery.data ?? null)
  const loadFailed = $derived(productQuery.isError)

  const images = $derived(product?.images ?? [])
  // Les titres Tillin peuvent être vides : même repli que la liste produits.
  const productLabel = $derived(
    product
      ? product.title?.trim() || product.reference_code || `Produit #${id}`
      : `Produit #${id}`,
  )

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
  // Config de génération (porté mannequin), pré-remplie des réglages.
  let genConfig = $state<GenerationConfig>({
    framing: "full_body",
    scene: "studio",
    instructions: "",
  })
  let genCount = $state(1)

  // Un seul encart à la fois (traiter OU générer) : afficher les deux prête
  // à confusion au moment de lancer une tâche.
  const MODE_TABS = [
    { key: "process", label: "Traitements" },
    { key: "generate", label: "Porté mannequin" },
  ] as const
  let mode = $state<(typeof MODE_TABS)[number]["key"]>("process")

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
      genConfig = {
        framing: data.imaging_generation_framing ?? "full_body",
        scene: data.imaging_generation_scene ?? "studio",
        instructions: data.imaging_generation_instructions ?? "",
      }
    })
  })

  // --- Travaux par image source (clé = URL) ---
  let works = $state<Record<string, Work>>({})
  let selected = $state<string[]>([])

  // Clé de travail : URL source pour la normalisation, suffixe ::gen pour la
  // génération (les deux peuvent coexister sur la même image).
  const GEN_SUFFIX = "::gen"

  // --- Réhydratation : les résultats non enregistrés survivent côté serveur
  // (asset + staging), on les réinstalle au retour dans le studio. ---
  const pendingAssetsQuery = createQuery(() => ({
    queryKey: ["imaging", "assets", productId, "pending"],
    queryFn: async () => {
      const { data, error } = await listAssets({
        product_id: productId,
        pending: true,
      })
      if (error || !data) throw new Error("assets_load_failed")
      return data
    },
  }))
  // Ids déjà installés (ou écartés localement) : un asset n'est réhydraté
  // qu'une fois, et jamais par-dessus un travail local en cours.
  const seenAssetIds = new Set<number>()

  function workKey(asset: ImageAssetPublic): string | null {
    if (!asset.source_image) return null
    return asset.verb === "generate_model"
      ? asset.source_image + GEN_SUFFIX
      : asset.source_image
  }

  async function hydrate(asset: ImageAssetPublic) {
    seenAssetIds.add(asset.id)
    const key = workKey(asset)
    if (key === null || works[key]) return
    const previewUrls = await fetchAssetPreviews(asset)
    if (works[key]) {
      // Un travail local a démarré entre-temps : il a priorité.
      for (const url of previewUrls) URL.revokeObjectURL(url)
      return
    }
    works[key] = {
      status: "done",
      asset,
      previewUrls,
      error: null,
      filename: "",
      replace: false,
      offsetX: asset.render_offset_x ?? 0,
      offsetY: asset.render_offset_y ?? 0,
      scale: asset.render_scale ?? 1,
      rendering: false,
      saving: false,
    }
  }

  $effect(() => {
    const assets = pendingAssetsQuery.data
    if (!assets) return
    // Tri décroissant côté serveur : le premier asset d'une clé est le plus
    // récent, les suivants (relances passées) sont seulement marqués vus.
    const hydratedKeys = new Set<string>()
    for (const asset of assets) {
      const key = workKey(asset)
      if (seenAssetIds.has(asset.id)) continue
      if (key !== null && hydratedKeys.has(key)) {
        seenAssetIds.add(asset.id)
        continue
      }
      if (key !== null) hydratedKeys.add(key)
      void hydrate(asset)
    }
  })

  function invalidatePendingAssets() {
    void queryClient.invalidateQueries({ queryKey: ["imaging", "assets"] })
    void queryClient.invalidateQueries({ queryKey: ["imaging", "pending-products"] })
  }

  async function discardOne(key: string) {
    const work = works[key]
    const asset = work?.asset
    if (!work || !asset || work.saving || work.rendering) return
    const { error } = await discardAsset(asset.id)
    if (error) {
      toast.error("Impossible d'écarter ce résultat.")
      return
    }
    for (const url of work.previewUrls) URL.revokeObjectURL(url)
    seenAssetIds.add(asset.id)
    delete works[key]
    toast.success("Résultat écarté")
    invalidatePendingAssets()
  }

  const statuses = $derived(
    Object.fromEntries(
      images.map((image) => [image.url, works[image.url]?.status ?? "idle"]),
    ) as Record<string, WorkStatus>,
  )
  const runningCount = $derived(
    Object.values(works).filter((w) => w.status === "running").length,
  )
  const results = $derived.by(() => {
    const pairs = images.flatMap((image) => {
      const found: { key: string; image: ProductImage; work: Work }[] = []
      for (const key of [image.url, image.url + GEN_SUFFIX]) {
        const work = works[key]
        if (work && work.status !== "idle") found.push({ key, image, work })
      }
      return found
    })
    // Résultats réhydratés dont la source ne fait plus partie des images du
    // produit : affichés quand même (sinon impossibles à vérifier/écarter).
    const knownKeys = new Set(pairs.map((pair) => pair.key))
    for (const [key, work] of Object.entries(works)) {
      if (knownKeys.has(key) || work.status === "idle") continue
      pairs.push({
        key,
        image: {
          url: key.endsWith(GEN_SUFFIX) ? key.slice(0, -GEN_SUFFIX.length) : key,
          id: work.asset?.source_product_image_id ?? null,
        } as ProductImage,
        work,
      })
    }
    return pairs
  })

  function toggleSelected(url: string) {
    selected = selected.includes(url)
      ? selected.filter((u) => u !== url)
      : [...selected, url]
  }

  function selectAll() {
    selected = selected.length === images.length ? [] : images.map((i) => i.url)
  }

  function freshWork(previous?: Work): Work {
    for (const url of previous?.previewUrls ?? []) URL.revokeObjectURL(url)
    return {
      status: "running",
      asset: null,
      previewUrls: [],
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

  /** Lance une opération 202 + polling et installe le résultat dans works. */
  async function runWork(
    key: string,
    launch: () => ReturnType<typeof normalizeImage>,
    failMessage: string,
  ) {
    if (works[key]?.status === "running") return
    works[key] = freshWork(works[key])
    const { data, error } = await launch()
    if (error || !data) {
      works[key].status = "failed"
      works[key].error = insufficientCreditsMessage(error) ?? failMessage
      return
    }
    const final = await waitForAsset(data.id, { intervalMs: 1500 })
    if (!final || final.status !== "completed") {
      works[key].status = "failed"
      works[key].error = final?.error ?? "Le traitement n'a pas abouti."
      return
    }
    works[key].asset = final
    works[key].previewUrls = await fetchAssetPreviews(final)
    works[key].status = "done"
  }

  function runOne(image: ProductImage) {
    return runWork(
      image.url,
      () => normalizeImage(productId, image.url, image.id ?? null, { ...options }),
      "Lancement impossible (service d'imagerie indisponible ?).",
    )
  }

  function runGenerate(image: ProductImage) {
    return runWork(
      image.url + GEN_SUFFIX,
      () =>
        generateModelImage(productId, image.url, image.id ?? null, {
          framing: genConfig.framing,
          scene: genConfig.scene,
          instructions: genConfig.instructions,
          num_images: genCount,
        }),
      "Lancement impossible (service de visuels indisponible ?).",
    )
  }

  async function runSelected() {
    const targets = images.filter((image) => selected.includes(image.url))
    if (targets.length === 0) return
    selected = []
    await Promise.all(targets.map((image) => runOne(image)))
  }

  async function runGenerateSelected() {
    const targets = images.filter((image) => selected.includes(image.url))
    if (targets.length === 0) return
    selected = []
    await Promise.all(targets.map((image) => runGenerate(image)))
  }

  async function saveOne(key: string) {
    const work = works[key]
    const asset = work?.asset
    if (!work || !asset || work.saving) return
    work.saving = true
    const replace = work.replace && asset.source_product_image_id != null
    const filenames =
      work.previewUrls.length <= 1 ? [work.filename.trim() || null] : undefined
    const { data, error } = await saveAsset(asset.id, replace, filenames)
    work.saving = false
    if (error || !data) {
      toast.error("Échec de l'enregistrement dans Tillin.")
      return
    }
    work.status = "saved"
    work.asset = { ...asset, can_render: false }
    toast.success(
      `${data.created} image${data.created > 1 ? "s" : ""} enregistrée${data.created > 1 ? "s" : ""}${data.deactivated > 0 ? ", originale remplacée" : ""}`,
    )
    // La galerie Tillin a changé : rafraîchit le cache produit + les vues
    // « à vérifier » (pastille catalogue, réhydratation).
    invalidatePendingAssets()
    await queryClient.invalidateQueries({ queryKey: ["product", productId] })
  }

  // Révoque les aperçus blob au démontage.
  $effect(() => {
    return () => {
      for (const work of Object.values(works)) {
        for (const url of work.previewUrls) URL.revokeObjectURL(url)
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
        { label: `Studio images — ${productLabel}` },
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
              title={productLabel}
            >
              Studio images — {productLabel}
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
          <!-- Un encart à la fois : traitement déterministe OU génération -->
          <TabBar tabs={MODE_TABS} bind:value={mode} label="Type d'opération" />

          {#if mode === "process"}
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
          {:else}
            <Card size="sm">
              <CardHeader>
                <CardTitle class="font-title text-sm">
                  Porté mannequin (génération)
                </CardTitle>
                <CardDescription class="text-muted-foreground text-xs">
                  Génère un visuel porté à partir de l'image produit. Instruction
                  pré-remplie avec vos réglages ; chaque visuel consomme des
                  crédits de génération.
                </CardDescription>
              </CardHeader>
              <CardContent class="flex flex-col gap-3">
                <GenerationOptions
                  bind:config={genConfig}
                  disabled={runningCount > 0}
                  idPrefix="studio-gen"
                />
                <div class="flex items-center gap-2">
                  <label class="text-muted-foreground text-xs" for="gen-count">
                    Visuels par image
                  </label>
                  <Select
                    id="gen-count"
                    class="h-8 w-auto px-2"
                    disabled={runningCount > 0}
                    bind:value={genCount}
                  >
                    {#each [1, 2, 3, 4] as n (n)}
                      <option value={n}>{n}</option>
                    {/each}
                  </Select>
                </div>
              </CardContent>
            </Card>
          {/if}

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
              <!-- Un seul bouton de lancement, aligné sur l'encart affiché. -->
              <Button
                size="sm"
                disabled={selected.length === 0 || runningCount > 0}
                onclick={mode === "generate" ? runGenerateSelected : runSelected}
              >
                {runningCount > 0
                  ? `Traitement… (${runningCount})`
                  : mode === "generate"
                    ? `Générer porté mannequin (${selected.length})`
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
            {#each results as pair (pair.key)}
              {@const isGeneration = pair.key.endsWith(GEN_SUFFIX)}
              {#if pair.work.status === "running"}
                <Card size="sm">
                  <CardContent class="text-muted-foreground py-6 text-center text-sm">
                    {isGeneration
                      ? "Génération du visuel en cours (10 s à 1 min)…"
                      : "Traitement en cours…"}
                  </CardContent>
                </Card>
              {:else if pair.work.status === "failed"}
                <Card size="sm">
                  <CardContent class="flex items-center justify-between gap-3 py-4">
                    <p class="text-destructive text-sm" role="alert">
                      {pair.work.error ?? "Traitement échoué."}
                    </p>
                    <Button
                      variant="outline"
                      size="sm"
                      onclick={() =>
                        isGeneration ? runGenerate(pair.image) : runOne(pair.image)}
                    >
                      Réessayer
                    </Button>
                  </CardContent>
                </Card>
              {:else}
                <AssetResult
                  image={pair.image}
                  work={pair.work}
                  filenamePlaceholder={hasImageTemplate
                    ? "selon le modèle de titre d'image"
                    : ""}
                  onSave={() => saveOne(pair.key)}
                  onDiscard={() => discardOne(pair.key)}
                />
              {/if}
            {/each}
          {/if}
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
