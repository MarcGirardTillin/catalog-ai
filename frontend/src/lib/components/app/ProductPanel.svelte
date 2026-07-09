<script lang="ts">
  // Panneau latéral produit : fiche Tillin (complétude, images, infos) ouverte
  // depuis les listes de produits. Pas de composant sheet/drawer dans ui/ —
  // overlay + <aside> fixe à droite, sobre et autonome.
  import Check from "@lucide/svelte/icons/check"
  import ImageIcon from "@lucide/svelte/icons/image"
  import Sparkles from "@lucide/svelte/icons/sparkles"
  import X from "@lucide/svelte/icons/x"
  import { fade, fly } from "svelte/transition"

  import { settingsReadAccountSettings } from "@/client"
  import { getProduct, type ProductDetail } from "@/lib/api/products"
  import { Button } from "@/lib/components/ui/button"
  import { Skeleton } from "@/lib/components/ui/skeleton"

  type Fallback = {
    title: string | null
    supplier_ref: string
    brand: string | null
    image_url: string | null
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
    onEnrich?: (productId: number) => void
  } = $props()

  let product = $state<ProductDetail | null>(null)
  let loading = $state(false)
  let errorMessage = $state<string | null>(null)

  // Modèle de titre du compte, chargé paresseusement pour l'indicateur
  // « Titre harmonisé » (null tant que non chargé ou en cas d'échec).
  let titleTemplate = $state<string | null>(null)
  let templateLoaded = $state(false)

  $effect(() => {
    const id = productId
    product = null
    errorMessage = null
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
    if (raw == null || raw.trim() === "") return "inconnu"
    const value = Number.parseFloat(raw)
    if (Number.isNaN(value)) return raw
    return value.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })
  }

  const infos = $derived.by(() => {
    const p = product
    if (!p) return []
    return [
      { label: "Catégorie", value: hasText(p.category) ? p.category : "—" },
      { label: "Saison", value: hasText(p.season) ? p.season : "—" },
      { label: "Rayon", value: hasText(p.department) ? p.department : "—" },
      { label: "Variantes", value: String((p.variants ?? []).length) },
      { label: "Prix", value: formatPrice(p.price) },
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
    class="border-border bg-background absolute inset-y-0 right-0 flex h-full w-full flex-col overflow-y-auto border-l sm:w-[28rem]"
    transition:fly={{ x: 448, duration: 200, opacity: 1 }}
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
      <button
        type="button"
        class="text-muted-foreground hover:text-foreground shrink-0 cursor-pointer rounded-md p-1 transition-colors"
        aria-label="Fermer"
        onclick={onClose}
      >
        <X size={18} aria-hidden="true" />
      </button>
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
        <Skeleton class="h-20 w-full" />
        <Skeleton class="h-40 w-full" />
        <Skeleton class="h-24 w-full" />
      {:else}
        <!-- Complétude -->
        <div class="flex flex-col gap-4">
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

        <!-- Galerie -->
        <div class="flex flex-col gap-2">
          <h3 class="text-sm font-medium">
            Images ({(product.images ?? []).length})
          </h3>
          {#if (product.images ?? []).length > 0}
            <div class="grid grid-cols-3 gap-2">
              {#each product.images ?? [] as image (image.url)}
                <img
                  src={image.url}
                  alt=""
                  loading="lazy"
                  class="bg-muted aspect-4/5 w-full rounded-md object-cover"
                />
              {/each}
            </div>
          {:else}
            <p class="text-muted-foreground flex items-center gap-1.5 text-xs italic">
              <ImageIcon size={14} aria-hidden="true" />
              Aucune image
            </p>
          {/if}
        </div>

        <!-- Infos -->
        <dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
          {#each infos as info (info.label)}
            <div>
              <dt class="text-muted-foreground">{info.label}</dt>
              <dd class="font-medium">{info.value}</dd>
            </div>
          {/each}
        </dl>

        <!-- Actions -->
        {#if onEnrich && productId != null}
          <Button class="w-full" onclick={() => onEnrich?.(productId)}>
            <Sparkles size={14} aria-hidden="true" />
            Enrichir ce produit
          </Button>
        {/if}

        <!-- À venir : traitements d'images via Photoroom (aucune action). -->
        <div class="bg-muted/50 flex flex-col gap-1.5 rounded-md p-3">
          <p class="text-muted-foreground text-xs font-medium">
            Images (Photoroom) — bientôt
          </p>
          <ul class="text-muted-foreground list-inside list-disc text-xs">
            <li>Détourage automatique</li>
            <li>Reformatage des visuels</li>
            <li>Génération mannequin / à plat</li>
          </ul>
        </div>
      {/if}
    </div>
  </div>
</div>
