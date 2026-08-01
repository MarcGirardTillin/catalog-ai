<script lang="ts">
  // Grille de review des produits extraits : sélection positive (à transférer
  // / écarté, unitaire et en masse), lignes dépliables avec édition du payload
  // et aperçu du prix profil. Extrait d'ImportDetailPage (scission P5.2).
  //
  // Layout en lignes grid (pas de <table> englobant) : le détail déplié —
  // formulaire + tableaux de variantes — vit dans un bloc pleine largeur avec
  // son propre défilement horizontal, sans élargir la liste ni couper les
  // colonnes de droite.
  import { untrack } from "svelte"

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
    resetImportItem,
    type ImportItemPublic,
    type ImportedProduct,
    type ImportedVariant,
  } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
  import { ConfirmButton } from "@/lib/components/ui/confirm-button"
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
    renderedByRef = null,
    optionAxes = null,
    profileDefaults = null,
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
    /** Rendu Tillin par référence (titre/saison après profil), null = pas
     *  de profil sélectionné. Aperçu en lecture seule sous le titre extrait. */
    renderedByRef?: Record<string, { title: string; season: string }> | null
    /** Axes d'options du profil sélectionné (ordre + libellés Tillin),
     *  null = pas de profil → colonnes par défaut Couleur puis Taille. */
    optionAxes?: { source: "color" | "size" | "extra"; label: string }[] | null
    /** Valeurs effectives imposées/repliées par le profil au transfert
     *  (affichées « (profil) » dans les infos produit). */
    profileDefaults?: {
      gender: string | null
      brand: string | null
      supplier: string | null
    } | null
    /** Items/statuts modifiés : la page rafraîchit le job + l'aperçu CSV. */
    onChanged: () => void
  } = $props()

  // Colonnes de variantes : l'ordre et les libellés suivent le profil ; la
  // colonne « extra » apparaît aussi sans profil dès qu'une valeur existe.
  type AxisSource = "color" | "size" | "extra"
  const DEFAULT_AXES: { source: AxisSource; label: string }[] = [
    { source: "color", label: "Couleur" },
    { source: "size", label: "Taille" },
  ]
  const variantColumns = $derived.by(() => {
    const axes = optionAxes?.length ? optionAxes : DEFAULT_AXES
    const hasExtraValues = items.some((item) =>
      item.payload.variants?.some((v) => v.extra),
    )
    if (!axes.some((a) => a.source === "extra") && hasExtraValues) {
      return [...axes, { source: "extra" as AxisSource, label: "Option 3" }]
    }
    return axes
  })

  const cellPad = $derived(prefs.density === "compact" ? "py-1" : "py-2.5")

  let expanded = $state<Set<number>>(new Set())

  // --- Review : brouillons d'édition par item (buffer local, Enregistrer
  // envoie le payload complet en PATCH) ---
  type VariantDraft = {
    color: string
    size: string
    extra: string
    ean: string
    quantity: string
    wholesale_price: string
    retail_price: string
    wholesale_discount: string
  }
  type ProductDraft = {
    supplier_ref: string
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
      supplier_ref: product.supplier_ref ?? "",
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
        extra: v.extra ?? "",
        ean: v.ean ?? "",
        quantity: v.quantity == null ? "" : String(v.quantity),
        wholesale_price: v.wholesale_price ?? "",
        retail_price: v.retail_price ?? "",
        wholesale_discount: v.wholesale_discount ?? "",
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
      // La référence est OBLIGATOIRE (code-barres construit + lien
      // post-transfert) : une saisie vidée retombe sur la valeur extraite.
      supplier_ref: clean(draft.supplier_ref) ?? original.supplier_ref,
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
          extra: clean(v.extra),
          ean: clean(v.ean),
          quantity: quantity === "" ? null : Number(quantity),
          wholesale_price: clean(v.wholesale_price),
          retail_price: clean(v.retail_price),
          wholesale_discount: clean(v.wholesale_discount),
        }
      }),
    }
  }

  /** Item éditable : job terminé et item pas encore transféré vers Tillin. */
  function isEditable(item: ImportItemPublic): boolean {
    return completed && item.status !== "applied"
  }

  // --- Sauvegarde automatique (retour Marc 2026-07-30) : toute modification
  // d'un brouillon est enregistrée 1,5 s après la dernière frappe ; le
  // bouton Enregistrer reste (il referme aussi la ligne). Une saisie
  // invalide (quantité non numérique) attend simplement la frappe suivante.
  const AUTOSAVE_DELAY_MS = 1500
  const autosaveTimers = new Map<number, ReturnType<typeof setTimeout>>()
  // JSON du dernier brouillon ENREGISTRÉ par item : la différence déclenche.
  const savedSnapshots = new Map<number, string>()
  let autosaveState = $state<Record<number, "saving" | "saved" | "error">>({})

  $effect(() => {
    // Dépend de `drafts` en profondeur : chaque frappe re-exécute l'effet.
    for (const [idStr, draft] of Object.entries(drafts)) {
      const id = Number(idStr)
      const snapshot = JSON.stringify(draft)
      const saved = savedSnapshots.get(id)
      if (saved !== undefined && saved !== snapshot) {
        untrack(() => scheduleAutosave(id))
      }
    }
  })

  function scheduleAutosave(itemId: number) {
    clearTimeout(autosaveTimers.get(itemId))
    autosaveTimers.set(
      itemId,
      setTimeout(() => void autoSave(itemId), AUTOSAVE_DELAY_MS),
    )
  }

  async function autoSave(itemId: number) {
    const item = items.find((i) => i.id === itemId)
    const draft = drafts[itemId]
    if (!item || !draft || !isEditable(item)) return
    if (savingItemId !== null) {
      // Une sauvegarde est en cours : on repassera.
      scheduleAutosave(itemId)
      return
    }
    const snapshot = JSON.stringify(draft)
    if (savedSnapshots.get(itemId) === snapshot) return
    for (const v of draft.variants) {
      const quantity = v.quantity.trim()
      if (quantity !== "" && !Number.isFinite(Number(quantity))) return
    }
    autosaveState[itemId] = "saving"
    savingItemId = itemId
    const { data, error } = await patchImportItem(importId, itemId, {
      payload: draftToPayload(item.payload, draft),
    })
    savingItemId = null
    if (error || !data) {
      autosaveState[itemId] = "error"
      return
    }
    // Le brouillon reste la vérité (l'utilisateur peut être en train de
    // taper) : on mémorise seulement l'état envoyé.
    items = items.map((i) => (i.id === data.id ? data : i))
    savedSnapshots.set(itemId, snapshot)
    autosaveState[itemId] = "saved"
    onChanged()
  }

  /** Restaure le payload extrait (avant toute édition). */
  async function resetItem(item: ImportItemPublic) {
    clearTimeout(autosaveTimers.get(item.id))
    const { data, error } = await resetImportItem(importId, item.id)
    if (error || !data) {
      toast.error("Réinitialisation impossible.")
      return
    }
    items = items.map((i) => (i.id === data.id ? data : i))
    drafts[item.id] = makeDraft(data.payload)
    savedSnapshots.set(item.id, JSON.stringify(drafts[item.id]))
    delete autosaveState[item.id]
    toast.success("Produit réinitialisé (données extraites restaurées)")
    onChanged()
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
    clearTimeout(autosaveTimers.get(item.id))
    savedSnapshots.set(item.id, JSON.stringify(drafts[item.id]))
    delete autosaveState[item.id]
    // Enregistrer referme la ligne (demande Marc 2026-07-29) : le geste
    // clôt la relecture du produit, on passe au suivant.
    const next = new Set(expanded)
    next.delete(item.id)
    expanded = next
    toast.success("Produit enregistré")
    onChanged()
  }

  function cancelItem(item: ImportItemPublic) {
    clearTimeout(autosaveTimers.get(item.id))
    drafts[item.id] = makeDraft(item.payload)
    savedSnapshots.set(item.id, JSON.stringify(drafts[item.id]))
    delete autosaveState[item.id]
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
        savedSnapshots.set(item.id, JSON.stringify(drafts[item.id]))
      }
    }
    expanded = next
  }

  function onRowKeydown(event: KeyboardEvent, item: ImportItemPublic) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      toggleExpanded(item)
    }
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
    { key: "supplier_ref", label: "Référence" },
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

  /** Prix d'achat HT × coefficient, arrondi au multiple supérieur de round_up_to. */
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

  /** Quantité totale commandée (variante sans quantité = 1, comme le CSV). */
  function quantityTotal(variants: ImportedVariant[]): number {
    return variants.reduce((acc, v) => acc + (v.quantity ?? 1), 0)
  }

  /** Tailles agrégées : liste courte, ou « min–max » quand il y en a beaucoup. */
  function sizeSummary(variants: ImportedVariant[]): string {
    const sizes = [...new Set(variants.map((v) => v.size).filter((s): s is string => !!s))]
    if (sizes.length === 0) return "—"
    if (sizes.length <= 3) return sizes.join(", ")
    return `${sizes[0]}–${sizes[sizes.length - 1]}`
  }

  /** Copie la valeur d'une cellule sur toutes les variantes SUIVANTES
   * (geste tableur « étendre vers le bas », ex. renommer une couleur). */
  function fillDown(itemId: number, field: keyof VariantDraft, from: number) {
    const draft = drafts[itemId]
    if (!draft) return
    const value = draft.variants[from][field]
    for (let i = from + 1; i < draft.variants.length; i += 1) {
      draft.variants[i][field] = value
    }
  }

  function formatPrice(raw: string | null): string {
    if (raw == null) return "—"
    const value = Number.parseFloat(raw)
    if (Number.isNaN(value)) return raw
    return value.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })
  }

  /** Fourchette de prix d'achat HT sur les variantes (ex. « 12,50 € – 18,00 € »). */
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

  // Champs produit secondaires affichés dans la ligne dépliée.
  const PRODUCT_FIELDS: { key: "category" | "season" | "gender" | "composition" | "hs_code" | "manufacturing_country"; label: string }[] = [
    { key: "category", label: "Catégorie" },
    { key: "season", label: "Saison" },
    { key: "gender", label: "Genre" },
    { key: "composition", label: "Composition" },
    { key: "hs_code", label: "Code SH" },
    { key: "manufacturing_country", label: "Pays de fabrication" },
  ]

  // Colonnes de la ligne de synthèse : case, chevron, produit (titre rendu +
  // titre extrait + réf), puis variantes et prix d'achat sur écran large
  // (redesign Marc 2026-07-30 : la marque sort de la synthèse).
  const ROW_GRID =
    "grid grid-cols-[2.25rem_2rem_minmax(0,1fr)] sm:grid-cols-[2.25rem_2rem_minmax(0,1fr)_11rem_7.5rem]"
</script>

<Card class="py-0">
  <CardContent class="px-0">
    <!-- En-tête (sm+) : mêmes colonnes que les lignes. -->
    <div
      class="border-border hidden items-center border-b sm:grid sm:grid-cols-[2.25rem_2rem_minmax(0,1fr)_11rem_7.5rem]"
    >
      <div class="flex justify-center px-2 py-2.5">
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
      </div>
      <div></div>
      <div class="text-muted-foreground px-3 py-2.5 text-xs font-medium">Produit</div>
      <div class="text-muted-foreground px-3 py-2.5 text-xs font-medium">Variantes</div>
      <div class="text-muted-foreground px-3 py-2.5 text-right text-xs font-medium">
        Prix d'achat HT
      </div>
    </div>
    <!-- Sélection globale (mobile) -->
    <div class="border-border flex items-center gap-2 border-b px-3 py-2 sm:hidden">
      <input
        type="checkbox"
        class="cursor-pointer"
        id="review-select-all-mobile"
        checked={allSelected}
        disabled={selectableItems.length === 0 || bulkUpdating}
        onchange={(e) => setAllIncluded(e.currentTarget.checked)}
      />
      <label for="review-select-all-mobile" class="text-muted-foreground text-xs">
        Tout transférer / tout écarter{totalPages > 1 ? " (page affichée)" : ""}
      </label>
    </div>

    {#each items as item (item.id)}
      {@const product = item.payload}
      {@const isOpen = expanded.has(item.id)}
      {@const isRejected = item.status === "rejected"}
      {@const isApplied = item.status === "applied"}
      {@const rendered = renderedByRef?.[product.supplier_ref] ?? null}
      <div class="border-border border-b last:border-b-0">
        <div
          role="button"
          tabindex="0"
          aria-expanded={isOpen}
          aria-label="Détail de {product.supplier_ref}"
          class="{ROW_GRID} hover:bg-muted/50 cursor-pointer items-start outline-none transition-colors focus-visible:bg-muted/50 {isRejected
            ? 'opacity-50'
            : ''}"
          onclick={() => toggleExpanded(item)}
          onkeydown={(e) => onRowKeydown(e, item)}
        >
          <div class="flex justify-center px-2 pt-1 {cellPad}">
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
              onkeydown={(e) => e.stopPropagation()}
              onchange={(e) => setItemIncluded(item, e.currentTarget.checked)}
            />
          </div>
          <div class="pt-0.5 {cellPad}">
            <span
              class="text-muted-foreground flex items-center p-0.5"
              aria-hidden="true"
            >
              {#if isOpen}
                <ChevronDown size={14} />
              {:else}
                <ChevronRight size={14} />
              {/if}
            </span>
          </div>
          <div class="min-w-0 px-3 {cellPad}">
            <!-- Titre principal = celui qui sera ÉCRIT dans Tillin au
                 transfert (rendu par le profil quand il y en a un) ; le
                 titre extrait passe en dessous, petit et gris. -->
            <p
              class="truncate text-sm font-medium {!rendered?.title &&
              lowConfidence(product.confidence, 'title')
                ? 'text-warning-foreground'
                : ''}"
              title={rendered?.title || (product.title ?? undefined)}
            >
              {rendered?.title || (product.title ?? "—")}
            </p>
            {#if rendered?.title && rendered.title !== (product.title ?? "")}
              <p
                class="truncate text-[11px] {lowConfidence(product.confidence, 'title')
                  ? 'text-warning-foreground'
                  : 'text-muted-foreground'}"
                title={product.title ?? undefined}
              >
                {product.title ?? "—"}
              </p>
            {/if}
            <p
              class="font-mono text-xs {lowConfidence(product.confidence, 'supplier_ref')
                ? 'text-warning-foreground'
                : 'text-muted-foreground'}"
            >
              {product.supplier_ref}
            </p>
            <p class="text-muted-foreground text-xs sm:hidden">
              {product.variants.length} variante{product.variants.length > 1 ? "s" : ""}
              · {quantityTotal(product.variants)} pièce{quantityTotal(product.variants) > 1 ? "s" : ""}
              · {sizeSummary(product.variants)}
              · {wholesaleRange(product.variants)}
            </p>
            {#if isRejected || isApplied || item.warnings.length > 0}
              <div class="mt-1 flex flex-wrap items-center gap-1.5">
                {#if isRejected || isApplied}
                  <!-- Même rendu de statut que partout ailleurs
                       (« Transféré » côté imports via context). -->
                  <StatusBadge status={item.status} context="import" />
                {/if}
                {#if item.warnings.length > 0}
                  <span
                    class="text-warning-foreground flex items-center gap-1 text-[11px]"
                    title={item.warnings.join(" · ")}
                  >
                    <TriangleAlert size={12} aria-hidden="true" />
                    {item.warnings.length} avertissement{item.warnings.length > 1 ? "s" : ""}
                  </span>
                {/if}
              </div>
            {/if}
          </div>
          <div class="hidden min-w-0 px-3 text-sm sm:block {cellPad}">
            <span class="block whitespace-nowrap">
              {product.variants.length} variante{product.variants.length > 1 ? "s" : ""}
              <span class="text-muted-foreground">
                · {quantityTotal(product.variants)} pce{quantityTotal(product.variants) > 1 ? "s" : ""}
              </span>
            </span>
            <span class="text-muted-foreground block truncate text-xs">
              {sizeSummary(product.variants)}
            </span>
          </div>
          <div class="hidden px-3 text-right text-sm whitespace-nowrap tabular-nums sm:block {cellPad}">
            {wholesaleRange(product.variants)}
          </div>
        </div>

        {#if isOpen}
          <!-- Détail pleine largeur : les tableaux de variantes défilent dans
               leur propre cadre (overflow-x-auto), la liste reste à l'écran. -->
          <div class="border-border bg-muted/30 border-t px-3 py-3 sm:px-4">
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
                <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {#each EDIT_FIELDS as field (field.key)}
                    <div class="flex min-w-0 flex-col gap-1">
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
                        {#each variantColumns as column (column.source)}
                          <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">{column.label}</th>
                        {/each}
                        <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">EAN</th>
                        <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">Qté</th>
                        <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">Prix d'achat HT</th>
                        <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">Remise %</th>
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
                          {#each variantColumns as column (column.source)}
                            <td class="px-1 py-1">
                              <div class="flex items-center gap-0.5">
                                <Input
                                  class="h-8 min-w-16 text-xs"
                                  aria-label="{column.label} de la variante {vIndex + 1}"
                                  bind:value={drafts[item.id].variants[vIndex][column.source]}
                                />
                                <button
                                  type="button"
                                  class="text-muted-foreground hover:text-foreground shrink-0 cursor-pointer rounded px-0.5 text-xs opacity-50 hover:opacity-100"
                                  title="Appliquer cette valeur aux variantes suivantes"
                                  aria-label="Appliquer cette valeur aux variantes suivantes"
                                  onclick={() => fillDown(item.id, column.source, vIndex)}
                                >
                                  ↓
                                </button>
                              </div>
                            </td>
                          {/each}
                          <td class="px-1 py-1">
                            <div class="flex items-center gap-0.5">
                            <Input
                              class="h-8 min-w-36 font-mono text-xs"
                              aria-label="EAN de la variante {vIndex + 1}"
                              bind:value={drafts[item.id].variants[vIndex].ean}
                            />
                              <button
                                type="button"
                                class="text-muted-foreground hover:text-foreground shrink-0 cursor-pointer rounded px-0.5 text-xs opacity-50 hover:opacity-100"
                                title="Appliquer cette valeur aux variantes suivantes"
                                aria-label="Appliquer cette valeur aux variantes suivantes"
                                onclick={() => fillDown(item.id, "ean", vIndex)}
                              >
                                ↓
                              </button>
                            </div>
                          </td>
                          <td class="px-1 py-1">
                            <div class="flex items-center gap-0.5">
                            <Input
                              class="h-8 min-w-14 text-xs"
                              inputmode="numeric"
                              aria-label="Quantité de la variante {vIndex + 1}"
                              bind:value={drafts[item.id].variants[vIndex].quantity}
                            />
                              <button
                                type="button"
                                class="text-muted-foreground hover:text-foreground shrink-0 cursor-pointer rounded px-0.5 text-xs opacity-50 hover:opacity-100"
                                title="Appliquer cette valeur aux variantes suivantes"
                                aria-label="Appliquer cette valeur aux variantes suivantes"
                                onclick={() => fillDown(item.id, "quantity", vIndex)}
                              >
                                ↓
                              </button>
                            </div>
                          </td>
                          <td class="px-1 py-1">
                            <div class="flex items-center gap-0.5">
                            <Input
                              class="h-8 min-w-20 text-xs"
                              inputmode="decimal"
                              aria-label="Prix d'achat HT de la variante {vIndex + 1}"
                              bind:value={drafts[item.id].variants[vIndex].wholesale_price}
                            />
                              <button
                                type="button"
                                class="text-muted-foreground hover:text-foreground shrink-0 cursor-pointer rounded px-0.5 text-xs opacity-50 hover:opacity-100"
                                title="Appliquer cette valeur aux variantes suivantes"
                                aria-label="Appliquer cette valeur aux variantes suivantes"
                                onclick={() => fillDown(item.id, "wholesale_price", vIndex)}
                              >
                                ↓
                              </button>
                            </div>
                          </td>
                          <td class="px-1 py-1">
                            <div class="flex items-center gap-0.5">
                            <Input
                              class="h-8 min-w-14 text-xs"
                              inputmode="decimal"
                              aria-label="Remise fournisseur de la variante {vIndex + 1}"
                              bind:value={drafts[item.id].variants[vIndex].wholesale_discount}
                            />
                              <button
                                type="button"
                                class="text-muted-foreground hover:text-foreground shrink-0 cursor-pointer rounded px-0.5 text-xs opacity-50 hover:opacity-100"
                                title="Appliquer cette valeur aux variantes suivantes"
                                aria-label="Appliquer cette valeur aux variantes suivantes"
                                onclick={() => fillDown(item.id, "wholesale_discount", vIndex)}
                              >
                                ↓
                              </button>
                            </div>
                          </td>
                          <td class="px-1 py-1">
                            <div class="flex items-center gap-0.5">
                            <Input
                              class="h-8 min-w-20 text-xs"
                              inputmode="decimal"
                              aria-label="Prix conseillé de la variante {vIndex + 1}"
                              bind:value={drafts[item.id].variants[vIndex].retail_price}
                            />
                              <button
                                type="button"
                                class="text-muted-foreground hover:text-foreground shrink-0 cursor-pointer rounded px-0.5 text-xs opacity-50 hover:opacity-100"
                                title="Appliquer cette valeur aux variantes suivantes"
                                aria-label="Appliquer cette valeur aux variantes suivantes"
                                onclick={() => fillDown(item.id, "retail_price", vIndex)}
                              >
                                ↓
                              </button>
                            </div>
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
                  <div class="flex items-center gap-2">
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
                    {#if item.has_original}
                      <!-- Restaure les données EXTRAITES (avant édition). -->
                      <ConfirmButton
                        label="Réinitialiser"
                        confirmLabel="Restaurer l'extrait ?"
                        onconfirm={() => resetItem(item)}
                      />
                    {/if}
                  </div>
                  <div class="flex items-center gap-2">
                    {#if autosaveState[item.id] === "saving"}
                      <span class="text-muted-foreground text-xs">Enregistrement…</span>
                    {:else if autosaveState[item.id] === "saved"}
                      <span class="text-muted-foreground text-xs">Enregistré ✓</span>
                    {:else if autosaveState[item.id] === "error"}
                      <span class="text-destructive text-xs">
                        Enregistrement auto impossible
                      </span>
                    {/if}
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
                {#if PRODUCT_FIELDS.some(({ key }) => product[key]) || profileSeason || profileDefaults}
                  <!-- Valeurs EFFECTIVES du transfert : quand le profil impose
                       ou replie une valeur (saison, genre, marque fixe,
                       fournisseur), c'est elle qui est montrée, marquée
                       « (profil) » — pas la valeur extraite du fichier. -->
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
                      {:else if key === "gender" && !product.gender && profileDefaults?.gender}
                        <!-- Genre par défaut du profil : repli seulement. -->
                        <div>
                          <dt class="text-muted-foreground">{label}</dt>
                          <dd>
                            {profileDefaults.gender}
                            <span class="text-muted-foreground">(profil)</span>
                          </dd>
                        </div>
                      {:else if product[key]}
                        <div>
                          <dt class="text-muted-foreground">{label}</dt>
                          <dd
                            class="wrap-break-word {lowConfidence(product.confidence, key)
                              ? 'text-warning-foreground'
                              : ''}"
                          >
                            {product[key]}
                          </dd>
                        </div>
                      {/if}
                    {/each}
                    {#if profileDefaults?.brand}
                      <!-- Marque fixe du profil : elle remplace toujours la
                           marque extraite dans le CSV. -->
                      <div>
                        <dt class="text-muted-foreground">Marque</dt>
                        <dd>
                          {profileDefaults.brand}
                          <span class="text-muted-foreground">(profil)</span>
                        </dd>
                      </div>
                    {/if}
                    {#if profileDefaults?.supplier}
                      <div>
                        <dt class="text-muted-foreground">Fournisseur</dt>
                        <dd>
                          {profileDefaults.supplier}
                          <span class="text-muted-foreground">(profil)</span>
                        </dd>
                      </div>
                    {/if}
                  </dl>
                {/if}

                <div class="overflow-x-auto">
                  <table class="w-full min-w-lg text-xs">
                    <thead>
                      <tr class="border-border border-b">
                        {#each variantColumns as column (column.source)}
                          <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">{column.label}</th>
                        {/each}
                        <th class="text-muted-foreground px-2 py-1.5 text-left font-medium">EAN</th>
                        <th class="text-muted-foreground px-2 py-1.5 text-right font-medium">Qté</th>
                        <th class="text-muted-foreground px-2 py-1.5 text-right font-medium">Prix d'achat HT</th>
                        <th class="text-muted-foreground px-2 py-1.5 text-right font-medium">Remise %</th>
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
                          {#each variantColumns as column (column.source)}
                            <td
                              class="px-2 py-1.5 {lowConfidence(variant.confidence, column.source)
                                ? 'text-warning-foreground'
                                : ''}"
                            >
                              {variant[column.source] ?? "—"}
                            </td>
                          {/each}
                          <td
                            class="px-2 py-1.5 font-mono whitespace-nowrap {lowConfidence(variant.confidence, 'ean')
                              ? 'text-warning-foreground'
                              : ''}"
                          >
                            {variant.ean ?? "—"}
                          </td>
                          <td class="px-2 py-1.5 text-right tabular-nums">
                            {variant.quantity ?? "—"}
                          </td>
                          <td
                            class="px-2 py-1.5 text-right whitespace-nowrap tabular-nums {lowConfidence(variant.confidence, 'wholesale_price')
                              ? 'text-warning-foreground'
                              : ''}"
                          >
                            {formatPrice(variant.wholesale_price)}
                          </td>
                          <td
                            class="px-2 py-1.5 text-right whitespace-nowrap tabular-nums {lowConfidence(variant.confidence, 'wholesale_discount')
                              ? 'text-warning-foreground'
                              : ''}"
                          >
                            {variant.wholesale_discount ?? "—"}
                          </td>
                          <td
                            class="px-2 py-1.5 text-right whitespace-nowrap tabular-nums {lowConfidence(variant.confidence, 'retail_price')
                              ? 'text-warning-foreground'
                              : ''}"
                          >
                            {formatPrice(variant.retail_price)}
                          </td>
                          {#if coefficientConfig}
                            <td class="text-muted-foreground px-2 py-1.5 text-right whitespace-nowrap italic tabular-nums">
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
          </div>
        {/if}
      </div>
    {/each}
  </CardContent>
</Card>

<div class="flex flex-wrap items-center justify-between gap-2">
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
