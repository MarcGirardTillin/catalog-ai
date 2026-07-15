<script lang="ts">
  // Panneau latéral produit : fiche Tillin (images, infos, variantes,
  // complétude) ouverte depuis les listes de produits. Pas de composant
  // sheet/drawer dans ui/ — overlay + <aside> fixe à droite, sobre et autonome.
  import Camera from "@lucide/svelte/icons/camera"
  import Check from "@lucide/svelte/icons/check"
  import ImageIcon from "@lucide/svelte/icons/image"
  import Images from "@lucide/svelte/icons/images"
  import LoaderCircle from "@lucide/svelte/icons/loader-circle"
  import PersonStanding from "@lucide/svelte/icons/person-standing"
  import Scissors from "@lucide/svelte/icons/scissors"
  import Upload from "@lucide/svelte/icons/upload"
  import X from "@lucide/svelte/icons/x"
  import { untrack } from "svelte"
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"
  import { fade, fly } from "svelte/transition"

  import { type ProductImage, settingsReadAccountSettings } from "@/client"
  import {
    fetchAssetPreviews,
    generateModelImage,
    type ImageAssetPublic,
    normalizeImage,
    saveAsset,
    waitForAsset,
  } from "@/lib/api/imaging"
  import {
    getProduct,
    uploadProductImages,
    type ProductDetail,
  } from "@/lib/api/products"
  import EnrichChooser from "@/lib/components/app/EnrichChooser.svelte"
  import { Button } from "@/lib/components/ui/button"
  import { Skeleton } from "@/lib/components/ui/skeleton"

  type Fallback = {
    title: string | null
    supplier_ref: string
    brand: string | null
    image_url: string | null
  }

  // Transformations à lancer (contrat config_json.transforms du backend).
  type EnrichTransforms = {
    copy: boolean
    title: boolean
    weights: boolean
    images: boolean
  }

  let {
    productId,
    importLabel = null,
    fallback = null,
    onClose,
    onEnrich,
  }: {
    productId: number | null
    importLabel?: string | null
    fallback?: Fallback | null
    onClose: () => void
    onEnrich?: (
      productId: number,
      transforms: EnrichTransforms,
      instructionId: number | null,
    ) => void
  } = $props()

  let product = $state<ProductDetail | null>(null)
  let loading = $state(false)
  let errorMessage = $state<string | null>(null)

  // Modèle de titre du compte, chargé paresseusement pour l'indicateur
  // « Titre harmonisé » (null tant que non chargé ou en cas d'échec).
  let titleTemplate = $state<string | null>(null)
  let templateLoaded = $state(false)

  // Images ajoutées localement (upload disque ou capture photo). Elles sont
  // seulement mises en attente et prévisualisées ici : la persistance vers
  // Tillin sera branchée avec la phase imagerie/Photoroom.
  type StagedImage = { id: string; url: string; name: string; file: File }
  let stagedImages = $state<StagedImage[]>([])
  let savingImages = $state(false)
  let fileInput: HTMLInputElement | undefined = $state()
  let cameraInput: HTMLInputElement | undefined = $state()

  function clearStaged() {
    for (const image of stagedImages) URL.revokeObjectURL(image.url)
    stagedImages = []
  }

  // Traitement d'images à la carte (sprint imagerie, Phase A) : une opération
  // à la fois — image source choisie, verbe lancé, preview avant/après, puis
  // enregistrement vers Tillin (avec remplacement optionnel de l'originale).
  let imgSel = $state<{ url: string; id: number | null } | null>(null)
  let imagingAsset = $state<ImageAssetPublic | null>(null)
  let imagingPreviews = $state<string[]>([])
  let imagingBusy = $state(false)
  let imagingVerb = $state<"normalize" | "generate_model" | null>(null)
  let replaceOriginal = $state(false)
  let savingAsset = $state(false)
  // Interrompt le polling du génératif quand le panneau change de produit.
  let pollAborter: AbortController | null = null

  function disposeImagingResult() {
    for (const url of imagingPreviews) URL.revokeObjectURL(url)
    imagingPreviews = []
    imagingAsset = null
    replaceOriginal = false
  }

  function clearImaging() {
    pollAborter?.abort()
    pollAborter = null
    disposeImagingResult()
    imgSel = null
    imagingBusy = false
    imagingVerb = null
  }

  function selectImagingSource(image: ProductImage) {
    if (imagingBusy || savingAsset) return
    // Re-cliquer l'image sélectionnée la désélectionne.
    imgSel =
      imgSel?.url === image.url
        ? null
        : { url: image.url, id: image.id ?? null }
  }

  async function runNormalize() {
    const id = productId
    const sel = imgSel
    if (id == null || !sel || imagingBusy) return
    imagingBusy = true
    imagingVerb = "normalize"
    disposeImagingResult()
    const { data, error } = await normalizeImage(id, sel.url, sel.id)
    if (error || !data) {
      imagingBusy = false
      toast.error(
        "Échec du traitement de l'image (service d'imagerie indisponible ?).",
      )
      return
    }
    // 202 : le pipeline (détourage + composition) tourne côté serveur —
    // même mécanique de polling que la génération.
    pollAborter = new AbortController()
    const signal = pollAborter.signal
    const final = await waitForAsset(data.id, { signal, intervalMs: 1500 })
    if (signal.aborted) return // le panneau a changé de produit entre-temps
    imagingBusy = false
    if (!final) {
      toast.error("Le traitement n'a pas abouti dans le temps imparti.")
      return
    }
    if (final.status !== "completed") {
      toast.error(final.error ?? "Traitement échoué.")
      return
    }
    imagingAsset = final
    imagingPreviews = await fetchAssetPreviews(final)
  }

  async function runGenerateModel() {
    const id = productId
    const sel = imgSel
    if (id == null || !sel || imagingBusy) return
    imagingBusy = true
    imagingVerb = "generate_model"
    disposeImagingResult()
    const { data, error } = await generateModelImage(id, sel.url, sel.id)
    if (error || !data) {
      imagingBusy = false
      toast.error(
        "Échec du lancement de la génération (service de visuels indisponible ?).",
      )
      return
    }
    // 202 : la génération tourne côté serveur (10 s à ~1 min) — polling léger.
    pollAborter = new AbortController()
    const signal = pollAborter.signal
    const final = await waitForAsset(data.id, { signal })
    if (signal.aborted) return // le panneau a changé de produit entre-temps
    imagingBusy = false
    if (!final) {
      toast.error("La génération n'a pas abouti dans le temps imparti.")
      return
    }
    if (final.status !== "completed") {
      toast.error(final.error ?? "Génération échouée.")
      return
    }
    imagingAsset = final
    imagingPreviews = await fetchAssetPreviews(final)
  }

  async function saveImagingResult() {
    const asset = imagingAsset
    if (!asset || savingAsset) return
    savingAsset = true
    const replace = replaceOriginal && asset.source_product_image_id != null
    const { data, error } = await saveAsset(asset.id, replace)
    savingAsset = false
    if (error || !data) {
      toast.error("Échec de l'enregistrement dans Tillin.")
      return
    }
    toast.success(
      `${data.created} image(s) enregistrée(s)` +
        (data.deactivated > 0 ? ", originale désactivée" : ""),
    )
    clearImaging()
    const id = productId
    if (id != null) {
      const reload = await getProduct(id)
      if (reload.data) product = reload.data
    }
  }

  // Réagit au changement de produit uniquement (productId). Le reste écrit —
  // et `clearStaged` LIT `stagedImages` en le remettant à zéro — donc on
  // l'exécute hors suivi (untrack) pour ne pas boucler l'effet.
  $effect(() => {
    const id = productId
    untrack(() => {
      product = null
      errorMessage = null
      clearStaged()
      clearImaging()
      if (id == null) return
      loading = true
      getProduct(id).then(({ data, error }) => {
        loading = false
        if (error || !data) {
          errorMessage = "Impossible de charger le produit."
          return
        }
        product = data
        if (!templateLoaded) {
          templateLoaded = true
          settingsReadAccountSettings().then(({ data: settings }) => {
            titleTemplate = settings?.title_template ?? null
          })
        }
      })
    })
  })

  // Libère les object-URLs restantes quand le panneau est démonté.
  $effect(() => () => {
    clearStaged()
    clearImaging()
  })

  function onFilesPicked(event: Event) {
    const input = event.currentTarget as HTMLInputElement
    for (const file of Array.from(input.files ?? [])) {
      stagedImages.push({
        id: crypto.randomUUID(),
        url: URL.createObjectURL(file),
        name: file.name,
        file,
      })
    }
    input.value = "" // autorise re-sélectionner le même fichier
  }

  function removeStaged(id: string) {
    const index = stagedImages.findIndex((image) => image.id === id)
    if (index >= 0) {
      URL.revokeObjectURL(stagedImages[index].url)
      stagedImages.splice(index, 1)
    }
  }

  // Envoie les images en attente à Tillin (import dans le stockage Xano), puis
  // recharge la fiche pour afficher les visuels fraîchement hébergés.
  async function saveImages() {
    const id = productId
    if (id == null || stagedImages.length === 0) return
    savingImages = true
    const { data, error } = await uploadProductImages(
      id,
      stagedImages.map((image) => image.file),
    )
    savingImages = false
    if (error || !data) {
      toast.error("Échec de l'enregistrement des images.")
      return
    }
    if (data.created === 0) {
      // Le backend a répondu mais Tillin n'a créé aucune image : on garde les
      // images en attente pour ne pas perdre la sélection de l'utilisateur.
      toast.error("Aucune image enregistrée par Tillin — réessayez.")
      return
    }
    toast.success(`${data.created} image(s) enregistrée(s)`)
    clearStaged()
    const reload = await getProduct(id)
    if (reload.data) product = reload.data
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation()
      onClose()
    }
  }

  const hasText = (value: string | null | undefined): boolean =>
    (value ?? "").trim() !== ""

  type Criterion = { label: string; ok: boolean }

  // « Prêt boutique » : le minimum pour vendre en caisse.
  const shopCriteria = $derived.by<Criterion[]>(() => {
    const p = product
    if (!p) return []
    return [
      { label: "Titre renseigné", ok: hasText(p.title) },
      { label: "Référence renseignée", ok: hasText(p.reference_code) },
      { label: "Au moins une variante", ok: (p.variants ?? []).length > 0 },
      { label: "Prix de vente", ok: p.price != null },
      { label: "Catégorie renseignée", ok: hasText(p.category) },
      { label: "Marque renseignée", ok: hasText(p.brand?.name) },
    ]
  })

  // « Prêt e-commerce » : le contenu nécessaire pour publier en ligne.
  const ecomCriteria = $derived.by<Criterion[]>(() => {
    const p = product
    if (!p) return []
    return [
      { label: "Au moins une image", ok: (p.images ?? []).length > 0 },
      { label: "Description", ok: hasText(p.description) },
      { label: "Meta description", ok: hasText(p.meta_description) },
      {
        label: "Poids renseigné",
        ok: (p.variants ?? []).some((v) => v.weight != null),
      },
    ]
  })

  function percent(criteria: Criterion[]): number {
    if (criteria.length === 0) return 0
    return Math.round((criteria.filter((c) => c.ok).length / criteria.length) * 100)
  }

  // Indicateur bonus (informatif, hors %) : approximation simple — si le
  // modèle de titre du compte contient {brand}, on vérifie que la marque
  // apparaît bien dans le titre du produit.
  const harmonized = $derived.by<boolean | null>(() => {
    const p = product
    if (!p || !titleTemplate) return null
    if (!titleTemplate.includes("{brand}")) return null
    const brand = (p.brand?.name ?? "").trim()
    const title = (p.title ?? "").trim()
    if (brand === "" || title === "") return false
    return title.toLowerCase().includes(brand.toLowerCase())
  })

  function formatPrice(raw: string | null | undefined): string {
    if (raw == null || String(raw).trim() === "") return "—"
    const value = Number.parseFloat(String(raw))
    if (Number.isNaN(value)) return String(raw)
    return value.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })
  }

  // Infos de classification (catégorie, saison, rayon, composition, pays).
  const infos = $derived.by(() => {
    const p = product
    if (!p) return []
    return [
      { label: "Catégorie", value: hasText(p.category) ? p.category : "—" },
      { label: "Saison", value: hasText(p.season) ? p.season : "—" },
      { label: "Rayon", value: hasText(p.department) ? p.department : "—" },
      {
        label: "Composition",
        value: hasText(p.composition) ? p.composition : "—",
      },
      {
        label: "Pays de fabrication",
        value: hasText(p.manufacturing_country) ? p.manufacturing_country : "—",
      },
    ]
  })
</script>

{#snippet completenessBlock(title: string, criteria: Criterion[])}
  {@const pct = percent(criteria)}
  <div class="flex flex-col gap-2">
    <div class="flex items-center justify-between">
      <span class="text-sm font-medium">{title}</span>
      <span class="text-muted-foreground font-mono text-xs">{pct}%</span>
    </div>
    <div class="bg-muted h-1.5 w-full overflow-hidden rounded-full">
      <div class="bg-primary h-full rounded-full transition-all" style={`width: ${pct}%`}></div>
    </div>
    <ul class="flex flex-col gap-1">
      {#each criteria as criterion (criterion.label)}
        <li class="text-muted-foreground flex items-center gap-1.5 text-xs">
          {#if criterion.ok}
            <Check size={13} class="text-success-dot shrink-0" aria-hidden="true" />
          {:else}
            <X size={13} class="text-destructive shrink-0" aria-hidden="true" />
          {/if}
          {criterion.label}
        </li>
      {/each}
    </ul>
  </div>
{/snippet}

<svelte:window onkeydown={onKeydown} />

<div class="fixed inset-0 z-50">
  <button
    type="button"
    class="absolute inset-0 bg-black/50"
    aria-label="Fermer le panneau"
    transition:fade={{ duration: 150 }}
    onclick={onClose}
  ></button>

  <!-- div (et non aside) : la règle a11y interdit role="dialog" sur un
       élément sectionnant non interactif. -->
  <div
    role="dialog"
    aria-modal="true"
    aria-label="Détail du produit"
    class="border-border bg-background absolute inset-y-0 right-0 flex h-full w-full max-w-full flex-col overflow-x-hidden overflow-y-auto border-l sm:w-[36rem]"
    transition:fly={{ x: "100%", duration: 200, opacity: 1 }}
  >
    <div
      class="border-border bg-background sticky top-0 z-10 flex items-start justify-between gap-2 border-b p-4"
    >
      <div class="flex min-w-0 flex-col gap-1">
        {#if product}
          <h2 class="font-title text-base leading-snug font-bold">
            {product.title?.trim() || product.reference_code || `Produit #${product.id}`}
          </h2>
          <div class="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
            {#if product.reference_code}
              <span class="font-mono">réf. {product.reference_code}</span>
            {/if}
            {#if product.brand?.name}
              <span>{product.brand.name}</span>
            {/if}
          </div>
        {:else if fallback && productId == null}
          <h2 class="font-title text-base leading-snug font-bold">
            {fallback.title?.trim() || fallback.supplier_ref}
          </h2>
          <div class="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
            <span class="font-mono">réf. {fallback.supplier_ref}</span>
            {#if fallback.brand}
              <span>{fallback.brand}</span>
            {/if}
          </div>
        {:else}
          <h2 class="font-title text-base font-bold">Produit</h2>
        {/if}
        {#if importLabel}
          <span
            class="bg-muted text-muted-foreground w-fit rounded-full px-2 py-0.5 text-[11px]"
          >
            Issu de l'import {importLabel}
          </span>
        {/if}
      </div>
      <div class="flex shrink-0 items-center gap-1.5">
        {#if onEnrich && productId != null && product}
          <EnrichChooser
            align="right"
            onLaunch={(transforms, instructionId) =>
              onEnrich?.(productId, transforms, instructionId)}
          />
        {/if}
        <button
          type="button"
          class="text-muted-foreground hover:text-foreground shrink-0 cursor-pointer rounded-md p-1 transition-colors"
          aria-label="Fermer"
          onclick={onClose}
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>
    </div>

    <div class="flex flex-1 flex-col gap-5 p-4">
      {#if productId == null && fallback}
        <!-- Item d'import non relié : données du fichier fournisseur. -->
        {#if fallback.image_url}
          <img
            src={fallback.image_url}
            alt=""
            loading="lazy"
            class="bg-muted aspect-4/5 w-40 rounded-md object-cover"
          />
        {/if}
        <p class="text-muted-foreground text-sm">
          Produit pas encore relié à Tillin — lancez « Relier aux produits
          Tillin ».
        </p>
      {:else if errorMessage}
        <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
      {:else if loading || product === null}
        <Skeleton class="h-40 w-full" />
        <Skeleton class="h-24 w-full" />
        <Skeleton class="h-20 w-full" />
      {:else}
        <!-- Galerie + ajout d'images (upload / capture) -->
        <div class="flex flex-col gap-2">
          <h3 class="text-sm font-medium">
            Images ({(product.images ?? []).length + stagedImages.length})
          </h3>
          {#if (product.images ?? []).length > 0 || stagedImages.length > 0}
            <p class="text-muted-foreground text-xs">
              Cliquez une image pour la sélectionner et lui appliquer un
              traitement.
            </p>
            <div class="grid grid-cols-3 gap-2">
              {#each product.images ?? [] as image (image.url)}
                <button
                  type="button"
                  class={`overflow-hidden rounded-md transition-shadow ${
                    imgSel?.url === image.url
                      ? "ring-primary ring-2"
                      : "hover:ring-border hover:ring-1"
                  }`}
                  aria-label="Sélectionner cette image pour traitement"
                  aria-pressed={imgSel?.url === image.url}
                  onclick={() => selectImagingSource(image)}
                >
                  <img
                    src={image.url}
                    alt=""
                    loading="lazy"
                    class="bg-muted aspect-4/5 w-full object-cover"
                  />
                </button>
              {/each}
              {#each stagedImages as image (image.id)}
                <div class="relative">
                  <img
                    src={image.url}
                    alt={image.name}
                    class="bg-muted ring-primary/40 aspect-4/5 w-full rounded-md object-cover ring-2"
                  />
                  <span
                    class="bg-primary/90 text-primary-foreground absolute bottom-1 left-1 rounded px-1 text-[10px]"
                  >
                    à enregistrer
                  </span>
                  <button
                    type="button"
                    class="bg-background/90 text-foreground hover:bg-background absolute top-1 right-1 rounded-full p-0.5 shadow-sm"
                    aria-label="Retirer l'image"
                    onclick={() => removeStaged(image.id)}
                  >
                    <X size={12} aria-hidden="true" />
                  </button>
                </div>
              {/each}
            </div>
          {:else}
            <p class="text-muted-foreground flex items-center gap-1.5 text-xs italic">
              <ImageIcon size={14} aria-hidden="true" />
              Aucune image
            </p>
          {/if}

          <!-- Deux entrées : disque (multiple) et appareil photo (capture). -->
          <input
            bind:this={fileInput}
            type="file"
            accept="image/*"
            multiple
            class="hidden"
            onchange={onFilesPicked}
          />
          <input
            bind:this={cameraInput}
            type="file"
            accept="image/*"
            capture="environment"
            class="hidden"
            onchange={onFilesPicked}
          />
          <div class="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={savingImages}
              onclick={() => fileInput?.click()}
            >
              <Upload size={14} aria-hidden="true" />
              Ajouter des images
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={savingImages}
              onclick={() => cameraInput?.click()}
            >
              <Camera size={14} aria-hidden="true" />
              Prendre une photo
            </Button>
            {#if stagedImages.length > 0}
              <Button size="sm" disabled={savingImages} onclick={saveImages}>
                {savingImages
                  ? "Enregistrement…"
                  : `Enregistrer ${stagedImages.length} image${stagedImages.length > 1 ? "s" : ""}`}
              </Button>
            {/if}
          </div>
          {#if stagedImages.length > 0}
            <p class="text-muted-foreground text-xs">
              Ces images sont en attente ; « Enregistrer » les importe dans Tillin
              (stockage Xano) et les attache au produit.
            </p>
          {/if}

          <!-- Traitements sur l'image sélectionnée (défauts du compte) ;
               le réglage fin (options, position, noms) vit au studio. -->
          {#if (product.images ?? []).length > 0}
            <div class="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!imgSel || imagingBusy || savingAsset}
                onclick={runNormalize}
              >
                <Scissors size={14} aria-hidden="true" />
                Normaliser (réglages par défaut)
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!imgSel || imagingBusy || savingAsset}
                onclick={runGenerateModel}
              >
                <PersonStanding size={14} aria-hidden="true" />
                Porté mannequin
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onclick={() => {
                  const id = productId
                  if (id != null) navigate(`/products/${id}/images`)
                }}
              >
                <Images size={14} aria-hidden="true" />
                Ouvrir le studio
              </Button>
            </div>
            {#if imagingBusy}
              <p class="text-muted-foreground flex items-center gap-1.5 text-xs">
                <LoaderCircle
                  size={14}
                  class="shrink-0 animate-spin"
                  aria-hidden="true"
                />
                {imagingVerb === "generate_model"
                  ? "Génération en cours (10 s à 1 min)…"
                  : "Traitement en cours…"}
              </p>
            {/if}
            {#if imagingAsset && imagingPreviews.length > 0}
              <div class="grid grid-cols-2 gap-2">
                <div class="flex flex-col gap-1">
                  <img
                    src={imagingAsset.source_image ?? imgSel?.url}
                    alt="Avant traitement"
                    class="bg-muted aspect-4/5 w-full rounded-md object-cover"
                  />
                  <span class="text-muted-foreground text-center text-[11px]">
                    Avant
                  </span>
                </div>
                {#each imagingPreviews as preview (preview)}
                  <div class="flex flex-col gap-1">
                    <img
                      src={preview}
                      alt="Résultat du traitement"
                      class="bg-muted ring-primary/40 aspect-4/5 w-full rounded-md object-cover ring-2"
                    />
                    <span class="text-muted-foreground text-center text-[11px]">
                      Après
                    </span>
                  </div>
                {/each}
              </div>
              {#if imagingAsset.source_product_image_id != null}
                <label class="flex items-center gap-1.5 text-xs">
                  <input type="checkbox" bind:checked={replaceOriginal} />
                  Remplacer l'image originale
                </label>
              {/if}
              <div class="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  disabled={savingAsset}
                  onclick={saveImagingResult}
                >
                  {savingAsset ? "Enregistrement…" : "Enregistrer dans Tillin"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={savingAsset}
                  onclick={disposeImagingResult}
                >
                  Annuler
                </Button>
              </div>
            {/if}
          {/if}
        </div>

        <!-- Description -->
        <div class="flex flex-col gap-1.5">
          <h3 class="text-sm font-medium">Description</h3>
          {#if hasText(product.description)}
            <p class="text-muted-foreground text-xs whitespace-pre-line">
              {product.description}
            </p>
          {:else}
            <p class="text-muted-foreground text-xs italic">Aucune description</p>
          {/if}
        </div>

        <!-- Meta description -->
        <div class="flex flex-col gap-1.5">
          <h3 class="text-sm font-medium">Meta description</h3>
          {#if hasText(product.meta_description)}
            <p class="text-muted-foreground text-xs whitespace-pre-line">
              {product.meta_description}
            </p>
          {:else}
            <p class="text-muted-foreground text-xs italic">
              Aucune meta description
            </p>
          {/if}
        </div>

        <!-- Infos de classification -->
        <dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
          {#each infos as info (info.label)}
            <div>
              <dt class="text-muted-foreground">{info.label}</dt>
              <dd class="font-medium">{info.value}</dd>
            </div>
          {/each}
        </dl>

        <!-- Tags -->
        {#if (product.tags ?? []).length > 0}
          <div class="flex flex-col gap-1.5">
            <h3 class="text-sm font-medium">Tags</h3>
            <div class="flex flex-wrap gap-1.5">
              {#each product.tags ?? [] as tag (tag)}
                <span
                  class="bg-muted text-muted-foreground rounded-full px-2 py-0.5 text-[11px]"
                >
                  {tag}
                </span>
              {/each}
            </div>
          </div>
        {/if}

        <!-- Variantes -->
        <div class="flex flex-col gap-2">
          <h3 class="text-sm font-medium">
            Variantes ({(product.variants ?? []).length})
          </h3>
          {#if (product.variants ?? []).length > 0}
            <div class="overflow-x-auto">
              <table class="w-full text-xs">
                <thead>
                  <tr class="text-muted-foreground border-border border-b text-left">
                    <th class="py-1.5 pr-2 font-medium">Taille</th>
                    <th class="py-1.5 pr-2 font-medium">Couleur</th>
                    <th class="py-1.5 pr-2 font-medium">EAN</th>
                    <th class="py-1.5 pr-2 font-medium">SKU</th>
                    <th class="py-1.5 pr-2 text-right font-medium">Achat</th>
                    <th class="py-1.5 text-right font-medium">Vente</th>
                  </tr>
                </thead>
                <tbody>
                  {#each product.variants ?? [] as variant, index (variant.id ?? index)}
                    <tr class="border-border/60 border-b last:border-0">
                      <td class="py-1.5 pr-2">{variant.size ?? "—"}</td>
                      <td class="py-1.5 pr-2">{variant.color ?? "—"}</td>
                      <td class="py-1.5 pr-2 font-mono">{variant.barcode ?? "—"}</td>
                      <td class="py-1.5 pr-2 font-mono">{variant.sku ?? "—"}</td>
                      <td class="py-1.5 pr-2 text-right whitespace-nowrap">
                        {formatPrice(variant.wholesale_price)}
                      </td>
                      <td class="py-1.5 text-right whitespace-nowrap">
                        {formatPrice(variant.price)}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {:else}
            <p class="text-muted-foreground text-xs italic">Aucune variante</p>
          {/if}
        </div>


        <!-- Complétude (en bas de panneau) -->
        <div class="border-border mt-1 flex flex-col gap-4 border-t pt-4">
          {@render completenessBlock("Prêt boutique", shopCriteria)}
          {@render completenessBlock("Prêt e-commerce", ecomCriteria)}
          <div class="text-muted-foreground flex items-center gap-1.5 text-xs">
            {#if harmonized === true}
              <Check size={13} class="text-success-dot shrink-0" aria-hidden="true" />
              Titre harmonisé (modèle du compte)
            {:else if harmonized === false}
              <X size={13} class="shrink-0" aria-hidden="true" />
              Titre non harmonisé avec le modèle du compte
            {:else}
              <span aria-hidden="true">—</span>
              Titre harmonisé : non évalué
            {/if}
          </div>
        </div>
      {/if}
    </div>
  </div>
</div>
