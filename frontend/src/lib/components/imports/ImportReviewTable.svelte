<script lang="ts">
  // Grille de review des produits extraits : sélection positive (à transférer
  // / écarté, unitaire et en masse), lignes dépliables avec édition du payload
  // et aperçu du prix profil. Extrait d'ImportDetailPage (scission P5.2).
  import ChevronDown from "@lucide/svelte/icons/chevron-down"
  import ChevronRight from "@lucide/svelte/icons/chevron-right"
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert"
  import { toast } from "svelte-sonner"

  import {
    optionTitles,
    type CatalogFiltersData,
  } from "@/lib/api/catalogFilters"
  import {
    bulkUpdateImportItems,
    patchImportItem,
    type ImportItemPublic,
    type ImportedProduct,
    type ImportedVariant,
  } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Select } from "@/lib/components/ui/select"
  import ReferenceSelect from "@/lib/components/app/ReferenceSelect.svelte"
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"
  import { prefs } from "@/lib/preferences.svelte"

  type CoefficientConfig = { coefficient: number; step: number } | null

  let {
    importId,
    items = $bindable(),
    page = $bindable(),
    totalPages,
    completed,
    profileSeason,
    coefficientConfig,
    catalogFilters,
    onChanged,
  }: {
    importId: number
    items: ImportItemPublic[]
    page: number
    totalPages: number
    /** Analyse terminée : édition et sélection actives. */
    completed: boolean
    /** Saison imposée par le profil ("" si aucune) — valeur effective du CSV. */
    profileSeason: string
    /** Config coefficient du profil (aperçu du prix de vente calculé). */
    coefficientConfig: CoefficientConfig
    /** Référentiel de classification (datalists), null si indisponible. */
    catalogFilters: CatalogFiltersData | null
    /** Items/statuts modifiés : la page rafraîchit le job + l'aperçu CSV. */
    onChanged: () => void
  } = $props()

  const cellPad = $derived(prefs.density === "compact" ? "py-1" : "py-2.5")

  let expanded = $state<Set<number>>(new Set())

  // --- Review : brouillons d'édition par item (buffer local, Enregistrer
  // envoie le payload complet en PATCH) ---
  type VariantDraft = {
    color: string
    size: string
    ean: string
    quantity: string
    wholesale_price: string
    retail_price: string
  }
  type ProductDraft = {
    title: string
    brand: string
    category: string
    season: string
    gender: string
    composition: string
    hs_code: string
    manufacturing_country: string
    variants: VariantDraft[]
  }
  type DraftTextField = Exclude<keyof ProductDraft, "variants">

  let drafts = $state<Record<number, ProductDraft>>({})
  let savingItemId = $state<number | null>(null)
  let statusItemId = $state<number | null>(null)

  function makeDraft(product: ImportedProduct): ProductDraft {
    return {
      title: product.title ?? "",
      brand: product.brand ?? "",
      category: product.category ?? "",
      season: product.season ?? "",
      gender: product.gender ?? "",
      composition: product.composition ?? "",
      hs_code: product.hs_code ?? "",
      manufacturing_country: product.manufacturing_country ?? "",
      variants: product.variants.map((v) => ({
        color: v.color ?? "",
        size: v.size ?? "",
        ean: v.ean ?? "",
        quantity: v.quantity == null ? "" : String(v.quantity),
        wholesale_price: v.wholesale_price ?? "",
        retail_price: v.retail_price ?? "",
      })),
    }
  }

  /** Reconstruit un ImportedProduct complet (champs vides → null), en
   * conservant supplier_ref, images, SKU et scores de confiance. */
  function draftToPayload(original: ImportedProduct, draft: ProductDraft): ImportedProduct {
    const clean = (value: string): string | null => {
      const trimmed = value.trim()
      return trimmed === "" ? null : trimmed
    }
    return {
      ...original,
      title: clean(draft.title),
      brand: clean(draft.brand),
      category: clean(draft.category),
      season: clean(draft.season),
      gender: clean(draft.gender),
      composition: clean(draft.composition),
      hs_code: clean(draft.hs_code),
      manufacturing_country: clean(draft.manufacturing_country),
      variants: original.variants.map((variant, index): ImportedVariant => {
        const v = draft.variants[index]
        if (!v) return variant
        const quantity = v.quantity.trim()
        return {
          ...variant,
          color: clean(v.color),
          size: clean(v.size),
          ean: clean(v.ean),
          quantity: quantity === "" ? null : Number(quantity),
          wholesale_price: clean(v.wholesale_price),
          retail_price: clean(v.retail_price),
        }
      }),
    }
  }

  /** Item éditable : job terminé et item pas encore transféré vers Tillin. */
  function isEditable(item: ImportItemPublic): boolean {
    return completed && item.status !== "applied"
  }

  async function saveItem(item: ImportItemPublic) {
    const draft = drafts[item.id]
    if (!draft || savingItemId !== null) return
    for (const v of draft.variants) {
      const quantity = v.quantity.trim()
      if (quantity !== "" && !Number.isFinite(Number(quantity))) {
        toast.error("Quantité invalide : entrez un nombre.")
        return
      }
    }
    savingItemId = item.id
    const { data, error } = await patchImportItem(importId, item.id, {
      payload: draftToPayload(item.payload, draft),
    })
    savingItemId = null
    if (error || !data) {
      toast.error("Enregistrement impossible.")
      return
    }
    items = items.map((i) => (i.id === data.id ? data : i))
    drafts[item.id] = makeDraft(data.payload)
    toast.success("Produit enregistré")
    onChanged()
  }

  function cancelItem(item: ImportItemPublic) {
    drafts[item.id] = makeDraft(item.payload)
  }

  async function setItemStatus(item: ImportItemPublic, status: "ready_for_review" | "rejected") {
    if (statusItemId !== null) return
    statusItemId = item.id
    const { data, error } = await patchImportItem(importId, item.id, { status })
    statusItemId = null
    if (error || !data) {
      toast.error("Mise à jour du statut impossible.")
      return
    }
    items = items.map((i) => (i.id === data.id ? data : i))
    toast.success(status === "rejected" ? "Produit écarté de l'export" : "Produit réintégré")
    onChanged()
  }

  // Sélection positive du transfert : cocher = « à transférer »
  // (ready_for_review), décocher = « écarté » (rejected). Les produits déjà
  // transférés (applied) ou en échec (failed) ne sont plus sélectionnables.
  const selectableItems = $derived(
    items.filter((i) => i.status === "ready_for_review" || i.status === "rejected"),
  )
  const allSelected = $derived(
    selectableItems.length > 0 &&
      selectableItems.every((i) => i.status === "ready_for_review"),
  )
  let bulkUpdating = $state(false)

  function setItemIncluded(item: ImportItemPublic, include: boolean) {
    void setItemStatus(item, include ? "ready_for_review" : "rejected")
  }

  async function setAllIncluded(include: boolean) {
    if (bulkUpdating) return
    const target = include ? "ready_for_review" : "rejected"
    const toChange = selectableItems.filter((i) => i.status !== target)
    if (toChange.length === 0) return
    bulkUpdating = true
    // Un seul PATCH atomique (l'ancienne version envoyait N requêtes).
    const { data, error } = await bulkUpdateImportItems(
      importId,
      toChange.map((i) => i.id),
      target,
    )
    bulkUpdating = false
    if (error || !data) {
      toast.error("Mise à jour de la sélection impossible.")
      return
    }
    const changed = new Set(toChange.map((i) => i.id))
    items = items.map((i) => (changed.has(i.id) ? { ...i, status: target } : i))
    toast.success(
      include
        ? "Tous les produits seront transférés"
        : "Tous les produits écartés du transfert",
    )
    onChanged()
  }

  function toggleExpanded(item: ImportItemPublic) {
    const next = new Set(expanded)
    if (next.has(item.id)) {
      next.delete(item.id)
    } else {
      next.add(item.id)
      // Prépare le brouillon d'édition au premier dépliage.
      if (isEditable(item) && !drafts[item.id]) {
        drafts[item.id] = makeDraft(item.payload)
      }
    }
    expanded = next
  }

  // Champs produit éditables dans la ligne dépliée (mode review).
  // `referential` : select harmonisé sur le référentiel Tillin — la valeur
  // extraite est injectée en option si elle n'y figure pas (jamais perdue).
  type ReviewReferential = "brands" | "categories" | "seasons" | "compositions"
  const EDIT_FIELDS: {
    key: DraftTextField
    label: string
    referential?: ReviewReferential
    kind?: "gender"
  }[] = [
    { key: "title", label: "Titre" },
    { key: "brand", label: "Marque", referential: "brands" },
    { key: "category", label: "Catégorie", referential: "categories" },
    { key: "season", label: "Saison", referential: "seasons" },
    { key: "gender", label: "Genre", kind: "gender" },
    { key: "composition", label: "Composition", referential: "compositions" },
    { key: "hs_code", label: "Code SH" },
    { key: "manufacturing_country", label: "Pays de fabrication" },
  ]

  const GENDER_OPTIONS = ["Homme", "Femme", "Unisexe"]

  /** Titres du référentiel pour un champ ([] = repli en champ texte). */
  function referentialTitles(list: ReviewReferential | undefined): string[] {
    if (!list || !catalogFilters) return []
    return optionTitles(catalogFilters[list])
  }

  /** Prix de gros × coefficient, arrondi au multiple supérieur de round_up_to. */
  function profilePrice(wholesale: string | null): string {
    if (!coefficientConfig || wholesale == null) return "—"
    const w = Number(wholesale.trim().replace(",", "."))
    if (!Number.isFinite(w) || wholesale.trim() === "") return "—"
    const raw = w * coefficientConfig.coefficient
    const value =
      coefficientConfig.step > 0
        ? Math.ceil(raw / coefficientConfig.step) * coefficientConfig.step
        : raw
    return value.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })
  }

  /** Confiance basse (< 0,7) sur un champ extrait → mise en évidence ambre. */
  function lowConfidence(confidence: Record<string, number>, field: string): boolean {
    const value = confidence?.[field]
    return value !== undefined && value < 0.7
  }

  /** Tailles agrégées : liste courte, ou « min–max » quand il y en a beaucoup. */
  function sizeSummary(variants: ImportedVariant[]): string {
    const sizes = [...new Set(variants.map((v) => v.size).filter((s): s is string => !!s))]
    if (sizes.length === 0) return "—"
    if (sizes.length <= 3) return sizes.join(", ")
    return `${sizes[0]}–${sizes[sizes.length - 1]}`
  }

  function formatPrice(raw: string | null): string {
    if (raw == null) return "—"
    const value = Number.parseFloat(raw)
    if (Number.isNaN(value)) return raw
    return value.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })
  }

  /** Fourchette de prix de gros sur les variantes (ex. « 12,50 € – 18,00 € »). */
  function wholesaleRange(variants: ImportedVariant[]): string {
    const prices = variants
      .map((v) => (v.wholesale_price == null ? NaN : Number.parseFloat(v.wholesale_price)))
      .filter((p) => !Number.isNaN(p))
    if (prices.length === 0) return "—"
    const min = Math.min(...prices)
    const max = Math.max(...prices)
    const fmt = (p: number) => p.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })
    return min === max ? fmt(min) : `${fmt(min)} – ${fmt(max)}`
  }

  function missingEanCount(variants: ImportedVariant[]): number {
    return variants.filter((v) => !v.ean).length
  }

  // Champs produit secondaires affichés dans la ligne dépliée.
  const PRODUCT_FIELDS: { key: "category" | "season" | "gender" | "composition" | "hs_code" | "manufacturing_country"; label: string }[] = [
    { key: "category", label: "Catégorie" },
    { key: "season", label: "Saison" },
    { key: "gender", label: "Genre" },
    { key: "composition", label: "Composition" },
    { key: "hs_code", label: "Code SH" },
    { key: "manufacturing_country", label: "Pays de fabrication" },
  ]
</script>

<Card class="py-0">
  <CardContent class="overflow-x-auto px-0">
    <table class="w-full min-w-2xl text-sm">
      <thead>
        <tr class="border-border border-b">
          <th class="w-9 px-2 py-2.5">
            <!-- Portée = page affichée uniquement (le job peut
                 avoir plusieurs pages) ; le compteur du transfert,
                 lui, couvre tout le job via job.counts. -->
            <input
              type="checkbox"
              class="cursor-pointer"
              checked={allSelected}
              disabled={selectableItems.length === 0 || bulkUpdating}
              aria-label={totalPages > 1
                ? "Tout transférer / tout écarter (page affichée)"
                : "Tout transférer / tout écarter"}
              title={totalPages > 1
                ? "Tout transférer / tout écarter (page affichée)"
                : "Tout transférer / tout écarter"}
              onchange={(e) => setAllIncluded(e.currentTarget.checked)}
            />
          </th>
          <th class="w-8 px-2 py-2.5"><span class="sr-only">Détail</span></th>
          <th class="text-muted-foreground px-3 py-2.5 text-left text-xs font-medium">Référence</th>
          <th class="text-muted-foreground px-3 py-2.5 text-left text-xs font-medium">Titre</th>
          <th class="text-muted-foreground px-3 py-2.5 text-left text-xs font-medium">Marque</th>
          <th class="text-muted-foreground px-3 py-2.5 text-right text-xs font-medium">Variantes</th>
          <th class="text-muted-foreground px-3 py-2.5 text-left text-xs font-medium">Tailles</th>
          <th class="text-muted-foreground px-3 py-2.5 text-right text-xs font-medium">Prix de gros</th>
          <th class="text-muted-foreground px-3 py-2.5 text-left text-xs font-medium"><span class="sr-only">Alertes</span></th>
        </tr>
      </thead>
      <tbody>
        {#each items as item (item.id)}
          {@const product = item.payload}
          {@const isOpen = expanded.has(item.id)}
          {@const noEan = missingEanCount(product.variants)}
          {@const isRejected = item.status === "rejected"}
          {@const isApplied = item.status === "applied"}
          <tr
            class="border-border hover:bg-muted/50 cursor-pointer border-b transition-colors {isRejected
              ? 'opacity-50'
              : ''}"
            onclick={() => toggleExpanded(item)}
          >
            <td class="px-2 {cellPad}">
              <!-- Sélection positive : coché = à transférer. Les
                   produits transférés/échoués ne sont plus modifiables. -->
              <input
                type="checkbox"
                class="cursor-pointer disabled:cursor-default"
                checked={item.status === "ready_for_review" || isApplied}
                disabled={isApplied ||
                  item.status === "failed" ||
                  statusItemId === item.id ||
                  bulkUpdating}
                aria-label={isApplied
                  ? `${product.supplier_ref} déjà transféré`
                  : `Transférer ${product.supplier_ref}`}
                title={isApplied ? "Déjà transféré" : "À transférer"}
                onclick={(e) => e.stopPropagation()}
                onchange={(e) => setItemIncluded(item, e.currentTarget.checked)}
              />
            </td>
            <td class="px-2 {cellPad}">
              <button
                type="button"
                class="text-muted-foreground hover:text-foreground flex cursor-pointer items-center p-0.5 transition-colors"
                aria-expanded={isOpen}
                aria-label={isOpen
                  ? `Replier ${product.supplier_ref}`
                  : `Déplier ${product.supplier_ref}`}
                onclick={(e) => {
                  e.stopPropagation()
                  toggleExpanded(item)
                }}
              >
                {#if isOpen}
                  <ChevronDown size={14} aria-hidden="true" />
                {:else}
                  <ChevronRight size={14} aria-hidden="true" />
                {/if}
              </button>
            </td>
            <td
              class="px-3 {cellPad} font-mono text-xs whitespace-nowrap {lowConfidence(product.confidence, 'supplier_ref')
                ? 'text-warning-foreground'
                : ''}"
            >
              {product.supplier_ref}
            </td>
            <td
              class="max-w-52 truncate px-3 {cellPad} {lowConfidence(product.confidence, 'title')
                ? 'text-warning-foreground'
                : ''}"
              title={product.title ?? undefined}
            >
              {product.title ?? "—"}
            </td>
            <td
              class="px-3 {cellPad} whitespace-nowrap {lowConfidence(product.confidence, 'brand')
                ? 'text-warning-foreground'
                : ''}"
            >
              {product.brand ?? "—"}
            </td>
            <td class="px-3 {cellPad} text-right whitespace-nowrap tabular-nums">
              {product.variants.length}
            </td>
            <td class="px-3 {cellPad} whitespace-nowrap">
              {sizeSummary(product.variants)}
            </td>
            <td class="px-3 {cellPad} text-right whitespace-nowrap tabular-nums">
              {wholesaleRange(product.variants)}
            </td>
            <td class="px-3 {cellPad}">
              <div class="flex items-center gap-1.5 whitespace-nowrap">
                {#if isRejected || isApplied}
                  <!-- Même rendu de statut que partout ailleurs
                       (« Transféré » côté imports via context). -->
                  <StatusBadge status={item.status} context="import" />
                {/if}
                {#if noEan > 0}
                  <span
                    class="text-muted-foreground bg-muted rounded-full px-2 py-0.5 text-[11px]"
                  >
                    {noEan} sans EAN
                  </span>
                {/if}
                {#if item.warnings.length > 0}
                  <span
                    class="text-warning-foreground flex items-center gap-1 text-[11px]"
                    title={item.warnings.join(" · ")}
                  >
                    <TriangleAlert size={12} aria-hidden="true" />
                    {item.warnings.length}
                  </span>
                {/if}
              </div>
            </td>
          </tr>
          {#if isOpen}
            <tr class="border-border bg-muted/30 border-b">
              <td colspan="9" class="px-4 py-3">
                <div class="flex flex-col gap-3">
                  {#if item.warnings.length > 0}
                    <ul class="flex flex-col gap-0.5">
                      {#each item.warnings as warning, i (i)}
                        <li class="text-warning-foreground flex items-start gap-1.5 text-xs">
                          <TriangleAlert size={12} class="mt-0.5 shrink-0" aria-hidden="true" />
                          {warning}
                        </li>
                      {/each}
                    </ul>
                  {/if}
                  {#if item.error}
                    <p class="text-destructive text-xs">{item.error}</p>
                  {/if}

                  {#if isEditable(item) && drafts[item.id]}
                    <!-- Mode review : édition locale (buffer), Enregistrer envoie le payload complet. -->
                    <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
                      {#each EDIT_FIELDS as field (field.key)}
                        <div class="flex flex-col gap-1">
                          <Label for="item-{item.id}-{field.key}" class="text-xs">
                            {field.label}
                          </Label>
                          {#if field.kind === "gender"}
                            <Select
                              id="item-{item.id}-{field.key}"
                              class="h-8 text-xs"
                              bind:value={drafts[item.id][field.key]}
                            >
                              <option value="">—</option>
                              {#if drafts[item.id][field.key] !== "" && !GENDER_OPTIONS.includes(drafts[item.id][field.key])}
                                <option value={drafts[item.id][field.key]}>
                                  {drafts[item.id][field.key]} (extrait)
                                </option>
                              {/if}
                              {#each GENDER_OPTIONS as gender (gender)}
                                <option value={gender}>{gender}</option>
                              {/each}
                            </Select>
                          {:else if field.referential}
                            <ReferenceSelect
                              id="item-{item.id}-{field.key}"
                              compact
                              options={referentialTitles(field.referential)}
                              bind:value={drafts[item.id][field.key]}
                            />
                          {:else}
                            <Input
                              id="item-{item.id}-{field.key}"
                              class="h-8 text-xs"
                              bind:value={drafts[item.id][field.key]}
                            />
                          {/if}
                        </div>
                      {/each}
                    </div>

                    <div class="overflow-x-auto">
                      <table class="w-full min-w-2xl text-xs">
                        <thead>
                          <tr class="border-border border-b">
                            <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">Couleur</th>
                            <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">Taille</th>
                            <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">EAN</th>
                            <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">Qté</th>
                            <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">Prix de gros</th>
                            <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">Prix conseillé</th>
                            {#if coefficientConfig}
                              <th class="text-muted-foreground px-2 py-1.5 text-right font-medium italic">
                                Prix vente (profil)
                              </th>
                            {/if}
                          </tr>
                        </thead>
                        <tbody>
                          {#each drafts[item.id].variants as _draftVariant, vIndex (vIndex)}
                            <tr class="border-border/50 border-b last:border-b-0">
                              <td class="px-1 py-1">
                                <Input
                                  class="h-8 min-w-24 text-xs"
                                  aria-label="Couleur de la variante {vIndex + 1}"
                                  bind:value={drafts[item.id].variants[vIndex].color}
                                />
                              </td>
                              <td class="px-1 py-1">
                                <Input
                                  class="h-8 min-w-16 text-xs"
                                  aria-label="Taille de la variante {vIndex + 1}"
                                  bind:value={drafts[item.id].variants[vIndex].size}
                                />
                              </td>
                              <td class="px-1 py-1">
                                <Input
                                  class="h-8 min-w-36 font-mono text-xs"
                                  aria-label="EAN de la variante {vIndex + 1}"
                                  bind:value={drafts[item.id].variants[vIndex].ean}
                                />
                              </td>
                              <td class="px-1 py-1">
                                <Input
                                  class="h-8 min-w-14 text-xs"
                                  inputmode="numeric"
                                  aria-label="Quantité de la variante {vIndex + 1}"
                                  bind:value={drafts[item.id].variants[vIndex].quantity}
                                />
                              </td>
                              <td class="px-1 py-1">
                                <Input
                                  class="h-8 min-w-20 text-xs"
                                  inputmode="decimal"
                                  aria-label="Prix de gros de la variante {vIndex + 1}"
                                  bind:value={drafts[item.id].variants[vIndex].wholesale_price}
                                />
                              </td>
                              <td class="px-1 py-1">
                                <Input
                                  class="h-8 min-w-20 text-xs"
                                  inputmode="decimal"
                                  aria-label="Prix conseillé de la variante {vIndex + 1}"
                                  bind:value={drafts[item.id].variants[vIndex].retail_price}
                                />
                              </td>
                              {#if coefficientConfig}
                                <td class="text-muted-foreground px-2 py-1 text-right whitespace-nowrap italic tabular-nums">
                                  {profilePrice(drafts[item.id].variants[vIndex].wholesale_price)}
                                </td>
                              {/if}
                            </tr>
                          {/each}
                        </tbody>
                      </table>
                    </div>

                    {#if coefficientConfig}
                      <p class="text-muted-foreground text-xs">
                        Prix vente (profil) : calculé par le profil —
                        appliqué dans le CSV / transfert, les données
                        extraites ne sont pas modifiées.
                      </p>
                    {/if}

                    <div class="flex flex-wrap items-center justify-between gap-2">
                      {#if isRejected}
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={statusItemId === item.id}
                          onclick={() => setItemStatus(item, "ready_for_review")}
                        >
                          {statusItemId === item.id ? "…" : "Réintégrer"}
                        </Button>
                      {:else}
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={statusItemId === item.id}
                          onclick={() => setItemStatus(item, "rejected")}
                        >
                          {statusItemId === item.id ? "…" : "Écarter"}
                        </Button>
                      {/if}
                      <div class="flex items-center gap-2">
                        <Button variant="ghost" size="sm" onclick={() => cancelItem(item)}>
                          Annuler
                        </Button>
                        <Button
                          size="sm"
                          disabled={savingItemId === item.id}
                          onclick={() => saveItem(item)}
                        >
                          {savingItemId === item.id ? "Enregistrement…" : "Enregistrer"}
                        </Button>
                      </div>
                    </div>
                  {:else}
                    {#if PRODUCT_FIELDS.some(({ key }) => product[key]) || profileSeason}
                      <dl class="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs sm:grid-cols-3">
                        {#each PRODUCT_FIELDS as { key, label } (key)}
                          {#if key === "season" && profileSeason}
                            <!-- Le profil impose la saison : on montre
                                 la valeur effective (celle du CSV). -->
                            <div>
                              <dt class="text-muted-foreground">{label}</dt>
                              <dd>
                                {profileSeason}
                                <span class="text-muted-foreground">(profil)</span>
                              </dd>
                            </div>
                          {:else if product[key]}
                            <div>
                              <dt class="text-muted-foreground">{label}</dt>
                              <dd
                                class={lowConfidence(product.confidence, key)
                                  ? "text-warning-foreground"
                                  : ""}
                              >
                                {product[key]}
                              </dd>
                            </div>
                          {/if}
                        {/each}
                      </dl>
                    {/if}

                    <div class="overflow-x-auto">
                      <table class="w-full min-w-lg text-xs">
                        <thead>
                          <tr class="border-border border-b">
                            <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">Couleur</th>
                            <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">Taille</th>
                            <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">EAN</th>
                            <th class="text-muted-foreground px-2 py-1.5 text-right font-medium">Qté</th>
                            <th class="text-muted-foreground px-2 py-1.5 text-right font-medium">Prix de gros</th>
                            <th class="text-muted-foreground px-2 py-1.5 text-right font-medium">Prix conseillé</th>
                            {#if coefficientConfig}
                              <th class="text-muted-foreground px-2 py-1.5 text-right font-medium italic">
                                Prix vente (profil)
                              </th>
                            {/if}
                          </tr>
                        </thead>
                        <tbody>
                          {#each product.variants as variant, index (index)}
                            <tr class="border-border/50 border-b last:border-b-0">
                              <td
                                class="px-2 py-1.5 {lowConfidence(variant.confidence, 'color')
                                  ? 'text-warning-foreground'
                                  : ''}"
                              >
                                {variant.color ?? "—"}
                              </td>
                              <td
                                class="px-2 py-1.5 {lowConfidence(variant.confidence, 'size')
                                  ? 'text-warning-foreground'
                                  : ''}"
                              >
                                {variant.size ?? "—"}
                              </td>
                              <td
                                class="px-2 py-1.5 font-mono {lowConfidence(variant.confidence, 'ean')
                                  ? 'text-warning-foreground'
                                  : ''}"
                              >
                                {variant.ean ?? "—"}
                              </td>
                              <td class="px-2 py-1.5 text-right tabular-nums">
                                {variant.quantity ?? "—"}
                              </td>
                              <td
                                class="px-2 py-1.5 text-right tabular-nums {lowConfidence(variant.confidence, 'wholesale_price')
                                  ? 'text-warning-foreground'
                                  : ''}"
                              >
                                {formatPrice(variant.wholesale_price)}
                              </td>
                              <td
                                class="px-2 py-1.5 text-right tabular-nums {lowConfidence(variant.confidence, 'retail_price')
                                  ? 'text-warning-foreground'
                                  : ''}"
                              >
                                {formatPrice(variant.retail_price)}
                              </td>
                              {#if coefficientConfig}
                                <td class="text-muted-foreground px-2 py-1.5 text-right italic tabular-nums">
                                  {profilePrice(variant.wholesale_price)}
                                </td>
                              {/if}
                            </tr>
                          {/each}
                        </tbody>
                      </table>
                    </div>

                    {#if coefficientConfig}
                      <p class="text-muted-foreground text-xs">
                        Prix vente (profil) : calculé par le profil —
                        appliqué dans le CSV / transfert, les données
                        extraites ne sont pas modifiées.
                      </p>
                    {/if}

                    {#if isApplied}
                      <p class="text-muted-foreground text-xs">
                        Produit transféré vers Tillin — lecture seule.
                      </p>
                    {:else if !completed}
                      <p class="text-muted-foreground text-xs">
                        Lecture seule — l'édition sera disponible une fois
                        l'analyse terminée.
                      </p>
                    {/if}
                  {/if}
                </div>
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
  </CardContent>
</Card>

<div class="flex items-center justify-between gap-2">
  <p class="text-muted-foreground text-xs">
    <span class="text-warning-foreground">Texte ambre</span> : champ extrait avec une
    confiance faible — à vérifier.
  </p>
  {#if totalPages > 1}
    <div class="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        disabled={page <= 1}
        onclick={() => (page = page - 1)}
      >
        Précédent
      </Button>
      <span class="text-muted-foreground text-xs whitespace-nowrap tabular-nums">
        Page {page} / {totalPages}
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={page >= totalPages}
        onclick={() => (page = page + 1)}
      >
        Suivant
      </Button>
    </div>
  {/if}
</div>
