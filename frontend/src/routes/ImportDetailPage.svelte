<script lang="ts">
  import ChevronDown from "@lucide/svelte/icons/chevron-down"
  import ChevronRight from "@lucide/svelte/icons/chevron-right"
  import Download from "@lucide/svelte/icons/download"
  import Eye from "@lucide/svelte/icons/eye"
  import EyeOff from "@lucide/svelte/icons/eye-off"
  import LoaderCircle from "@lucide/svelte/icons/loader-circle"
  import Pencil from "@lucide/svelte/icons/pencil"
  import Plus from "@lucide/svelte/icons/plus"
  import Send from "@lucide/svelte/icons/send"
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert"
  import { navigate } from "svelte5-router"
  import { toast } from "svelte-sonner"

  import {
    loadCatalogFilters,
    optionTitles,
    type CatalogFiltersData,
  } from "@/lib/api/catalogFilters"
  import { jobsCreateEnrichmentJob } from "@/client"
  import {
    bulkUpdateImportItems,
    getImportCsv,
    getImportFile,
    getImportProducts,
    getImportRows,
    linkImportProducts,
    listImportItems,
    listImportProfiles,
    listLocations,
    patchImportItem,
    previewImportFile,
    readImport,
    setImportLocation,
    setImportProfile,
    transferImport,
    type ImportFilePreview,
    type ImportItemPublic,
    type ImportJobPublic,
    type ImportProfilePublic,
    type ImportRowsPreview,
    type ImportedProduct,
    type ImportedVariant,
    type LocationPublic,
  } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import { prefs } from "@/lib/preferences.svelte"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import EnrichChooser from "@/lib/components/app/EnrichChooser.svelte"
  import FilePreviewTable from "@/lib/components/app/FilePreviewTable.svelte"
  import ReferenceSelect from "@/lib/components/app/ReferenceSelect.svelte"
  import ImportProfileForm from "@/lib/components/app/ImportProfileForm.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"
  import { formatDuration } from "@/lib/format"

  let { appName, id }: { appName: string; id: string } = $props()

  const PAGE_SIZE = 100
  const cellPad = $derived(prefs.density === "compact" ? "py-1" : "py-2.5")

  let job = $state<ImportJobPublic | null>(null)
  let items = $state<ImportItemPublic[] | null>(null)
  let page = $state(1)
  let totalPages = $state(1)
  let errorMessage = $state<string | null>(null)
  let expanded = $state<Set<number>>(new Set())

  async function load() {
    const jobId = Number(id)
    const [jobResult, itemsResult] = await Promise.all([
      readImport(jobId),
      listImportItems(jobId, { page, page_size: PAGE_SIZE }),
    ])
    if (jobResult.error || !jobResult.data) {
      errorMessage = "Import introuvable."
      return
    }
    job = jobResult.data
    if (itemsResult.data) {
      items = itemsResult.data.items
      totalPages = itemsResult.data.total_pages
    } else {
      items = items ?? []
    }
  }

  // Chargement initial + polling toutes les 2,5 s tant que l'analyse tourne
  // (même pattern que le suivi des jobs d'enrichissement).
  $effect(() => {
    // `page` est lu ici pour recharger quand la pagination change.
    void page
    load()
    const timer = setInterval(() => {
      if (job && (job.status === "pending" || job.status === "processing")) {
        load()
      }
    }, 2500)
    return () => clearInterval(timer)
  })

  // Durée effective ou « En cours depuis » live (tick chaque seconde).
  let now = $state(Date.now())
  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 1000)
    return () => clearInterval(t)
  })

  const timing = $derived.by(() => {
    if (!job) return null
    if (job.duration_seconds != null) {
      return { label: "Durée", value: formatDuration(job.duration_seconds) }
    }
    if (job.started_at) {
      const elapsed = (now - new Date(job.started_at).getTime()) / 1000
      return { label: "En cours depuis", value: formatDuration(Math.max(0, elapsed)) }
    }
    return null
  })

  const running = $derived(job?.status === "pending" || job?.status === "processing")
  const completed = $derived(job?.status === "completed")

  // --- Profil d'import associé au job ---
  const selectClass =
    "border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"

  let profiles = $state<ImportProfilePublic[] | null>(null)
  let selectedProfileId = $state<number | null>(null)
  let settingProfile = $state(false)
  // Pré-sélection faite une seule fois (job.profile_id, sinon correspondance
  // fournisseur ≈ supplier_match en minuscules).
  let profileInitDone = false

  $effect(() => {
    listImportProfiles().then(({ data }) => {
      profiles = data ?? []
    })
  })

  $effect(() => {
    if (profileInitDone || !job || profiles === null) return
    profileInitDone = true
    if (job.profile_id != null) {
      selectedProfileId = job.profile_id
      return
    }
    const supplier = (job.supplier ?? "").trim().toLowerCase()
    if (supplier === "") return
    const match = profiles.find((p) => {
      const needle = p.supplier_match.trim().toLowerCase()
      return needle !== "" && (supplier.includes(needle) || needle.includes(supplier))
    })
    if (match) selectedProfileId = match.id
  })

  async function changeProfile(event: Event) {
    const raw = (event.currentTarget as HTMLSelectElement).value
    const next = raw === "" ? null : Number(raw)
    const previous = selectedProfileId
    selectedProfileId = next
    settingProfile = true
    const { data, error } = await setImportProfile(Number(id), next)
    settingProfile = false
    if (error || !data) {
      selectedProfileId = previous
      toast.error("Impossible d'associer le profil.")
      return
    }
    job = data
    // L'aperçu CSV dépend du profil : on l'invalide.
    rowsPreview = null
    rowsOpen = false
    toast.success(next === null ? "Profil retiré" : "Profil appliqué")
  }

  const selectedProfile = $derived(
    (profiles ?? []).find((p) => p.id === selectedProfileId) ?? null,
  )

  // Saison imposée par le profil : elle REMPLACE la saison extraite du document
  // au rendu CSV / transfert (comme le prix en mode coefficient). Affichée comme
  // valeur effective dans la grille pour éviter toute ambiguïté.
  const profileSeason = $derived((selectedProfile?.config.season_label ?? "").trim())

  // Combien de produits partiront (non écartés) vs écartés vs déjà transférés :
  // le transfert n'envoie que les produits gardés. Dérivé des counts SERVEUR
  // (job.counts) et non de la page d'items : le transfert backend couvre tout
  // le job, pas seulement la page affichée (imports > 100 produits).
  const transferSummary = $derived.by(() => {
    const c = job?.counts
    return {
      kept: c?.ready_for_review ?? 0,
      excluded: c?.rejected ?? 0,
      applied: c?.applied ?? 0,
    }
  })

  // --- Création/édition de profil sans quitter la review (panneau inline) ---
  let profileFormMode = $state<null | "edit" | "new">(null)

  async function onProfileSaved(saved: ImportProfilePublic, isNew: boolean) {
    profileFormMode = null
    // Recharge la liste des profils (source de vérité serveur).
    const { data } = await listImportProfiles()
    if (data) {
      profiles = data
    } else if (isNew) {
      profiles = [...(profiles ?? []), saved]
    } else {
      profiles = (profiles ?? []).map((p) => (p.id === saved.id ? saved : p))
    }
    if (isNew) {
      // Sélection automatique du profil créé pour ce job (il reste bien sûr
      // disponible pour les prochains imports du même fournisseur).
      const { data: updated, error } = await setImportProfile(Number(id), saved.id)
      if (error || !updated) {
        toast.error("Profil créé, mais impossible de l'associer au job.")
      } else {
        job = updated
        selectedProfileId = saved.id
      }
    }
    // L'aperçu CSV dépend du profil : on l'invalide.
    rowsPreview = null
    rowsOpen = false
  }

  // --- Référentiel de classification (datalists de la grille de review).
  // Échec silencieux : les champs restent de simples champs texte. ---
  let catalogFilters = $state<CatalogFiltersData | null>(null)
  $effect(() => {
    loadCatalogFilters().then((data) => {
      catalogFilters = data
    })
  })

  // --- Magasin (location) du job : affiché et modifiable dans la synthèse,
  // pré-sélectionné dans le panneau de transfert. ---
  let settingLocation = $state(false)

  async function changeLocation(event: Event) {
    const raw = (event.currentTarget as HTMLSelectElement).value
    const next = raw === "" ? null : Number(raw)
    settingLocation = true
    const { data, error } = await setImportLocation(Number(id), next)
    settingLocation = false
    if (error || !data) {
      toast.error("Impossible de changer le magasin.")
      return
    }
    job = data
    toast.success(next === null ? "Magasin retiré" : "Magasin mis à jour")
  }

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
      variants: original.variants.map((variant, index) => {
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

  async function refreshJob() {
    const { data } = await readImport(Number(id))
    if (data) job = data
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
    const { data, error } = await patchImportItem(Number(id), item.id, {
      payload: draftToPayload(item.payload, draft),
    })
    savingItemId = null
    if (error || !data) {
      toast.error("Enregistrement impossible.")
      return
    }
    items = (items ?? []).map((i) => (i.id === data.id ? data : i))
    drafts[item.id] = makeDraft(data.payload)
    rowsPreview = null
    rowsOpen = false
    toast.success("Produit enregistré")
    refreshJob()
  }

  function cancelItem(item: ImportItemPublic) {
    drafts[item.id] = makeDraft(item.payload)
  }

  async function setItemStatus(item: ImportItemPublic, status: "ready_for_review" | "rejected") {
    if (statusItemId !== null) return
    statusItemId = item.id
    const { data, error } = await patchImportItem(Number(id), item.id, { status })
    statusItemId = null
    if (error || !data) {
      toast.error("Mise à jour du statut impossible.")
      return
    }
    items = (items ?? []).map((i) => (i.id === data.id ? data : i))
    rowsPreview = null
    rowsOpen = false
    toast.success(status === "rejected" ? "Produit écarté de l'export" : "Produit réintégré")
    refreshJob()
  }

  // Sélection positive du transfert : cocher = « à transférer »
  // (ready_for_review), décocher = « écarté » (rejected). Les produits déjà
  // transférés (applied) ou en échec (failed) ne sont plus sélectionnables.
  const selectableItems = $derived(
    (items ?? []).filter(
      (i) => i.status === "ready_for_review" || i.status === "rejected",
    ),
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
      Number(id),
      toChange.map((i) => i.id),
      target,
    )
    bulkUpdating = false
    if (error || !data) {
      toast.error("Mise à jour de la sélection impossible.")
      return
    }
    const changed = new Set(toChange.map((i) => i.id))
    items = (items ?? []).map((i) =>
      changed.has(i.id) ? { ...i, status: target } : i,
    )
    rowsPreview = null
    rowsOpen = false
    toast.success(
      include
        ? "Tous les produits seront transférés"
        : "Tous les produits écartés du transfert",
    )
    refreshJob()
  }

  // --- Export Tillin (aperçu des lignes, CSV, transfert) ---
  let rowsOpen = $state(false)
  let rowsLoading = $state(false)
  let rowsError = $state<string | null>(null)
  let rowsPreview = $state<ImportRowsPreview | null>(null)
  let csvDownloading = $state(false)

  let transferOpen = $state(false)
  let locations = $state<LocationPublic[] | null>(null)
  let locationsLoading = $state(false)
  let locationsError = $state<string | null>(null)
  let selectedLocationId = $state("")
  let transferring = $state(false)
  let transferred = $state(false)

  async function toggleCsvPreview() {
    if (rowsOpen) {
      rowsOpen = false
      return
    }
    rowsOpen = true
    if (rowsPreview || rowsLoading) return
    rowsLoading = true
    rowsError = null
    const { data, error } = await getImportRows(Number(id), selectedProfileId ?? undefined)
    rowsLoading = false
    if (error || !data) {
      rowsError = "Impossible de générer l'aperçu CSV."
      return
    }
    rowsPreview = data
  }

  async function downloadCsv() {
    if (csvDownloading) return
    csvDownloading = true
    const result = await getImportCsv(Number(id), selectedProfileId ?? undefined)
    csvDownloading = false
    if (result.error || !result.data) {
      toast.error("Téléchargement du CSV impossible.")
      return
    }
    // Nom depuis Content-Disposition si le header est accessible.
    let fileName = `import_${id}.csv`
    const headers = (result as { response?: { headers?: Record<string, unknown> } })
      .response?.headers
    const disposition = headers?.["content-disposition"]
    if (typeof disposition === "string") {
      const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)
      if (match?.[1]) fileName = decodeURIComponent(match[1])
    }
    const url = URL.createObjectURL(result.data)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = fileName
    anchor.click()
    URL.revokeObjectURL(url)
  }

  // Chargées au montage : le magasin du job est affiché dans la synthèse.
  $effect(() => {
    loadLocations()
  })

  function toggleTransfer() {
    transferOpen = !transferOpen
    if (transferOpen) {
      if (locations === null && !locationsLoading) loadLocations()
      // Pré-sélectionne le magasin du job (modifiable avant confirmation).
      if (job?.location_id != null) selectedLocationId = String(job.location_id)
    }
  }

  async function loadLocations() {
    locationsLoading = true
    locationsError = null
    const { data, error } = await listLocations()
    locationsLoading = false
    if (error || !data) {
      locationsError = "Impossible de charger les magasins."
      return
    }
    locations = data
    if (data.length > 0 && selectedLocationId === "") {
      selectedLocationId = String(data[0].id)
    }
  }

  async function confirmTransfer() {
    if (selectedLocationId === "" || transferring) return
    transferring = true
    const { data, error } = await transferImport(Number(id), {
      location_id: Number(selectedLocationId),
      ...(selectedProfileId != null ? { profile_id: selectedProfileId } : {}),
    })
    transferring = false
    if (error || !data || !data.ok) {
      toast.error("Transfert vers Tillin impossible.")
      return
    }
    transferOpen = false
    transferred = true
    toast.success(
      `${data.row_count} ligne${data.row_count > 1 ? "s" : ""} transférée${data.row_count > 1 ? "s" : ""} vers Tillin`,
    )
    // Recharge job + items : les items passent au statut « applied ».
    await load()
  }

  // --- Pont import → enrichissement : une fois le transfert fait, on peut
  // voir les produits créés dans Tillin ou lancer directement un job
  // d'enrichissement sur eux (liaison à la volée si nécessaire). ---
  let enriching = $state(false)

  // Des items déjà transférés (counts serveur), ou transfert fait à l'instant.
  const hasTransferred = $derived(
    transferred || (job?.counts.applied ?? 0) > 0,
  )

  async function enrichCreatedProducts(
    transforms: { copy: boolean; title: boolean; weights: boolean; images: boolean },
    instructionId: number | null,
  ) {
    if (enriching) return
    enriching = true
    let { data, error } = await getImportProducts(Number(id))
    if (error || !data) {
      enriching = false
      toast.error("Impossible de lire les produits de l'import.")
      return
    }
    if (data.unlinked_count > 0) {
      const linkResult = await linkImportProducts(Number(id))
      if (linkResult.error || !linkResult.data) {
        enriching = false
        const code = (linkResult.error as { code?: string } | null)?.code
        toast.error(
          code === "not_transferred"
            ? "Cet import n'a pas encore été transféré vers Tillin."
            : "Liaison aux produits Tillin impossible.",
        )
        return
      }
      const refreshed = await getImportProducts(Number(id))
      if (refreshed.data) data = refreshed.data
    }
    const ids = data.items
      .map((i) => i.tillin_product_id)
      .filter((v): v is number => v != null)
    if (ids.length === 0) {
      enriching = false
      toast.error(
        "Aucun produit Tillin relié à cet import — impossible de lancer l'enrichissement.",
      )
      return
    }
    const { data: jobData, error: jobError } = await jobsCreateEnrichmentJob({
      body: {
        selection: { ids },
        config: {
          transforms,
          ...(instructionId != null ? { instruction_id: instructionId } : {}),
        },
      },
    })
    enriching = false
    if (jobError || !jobData) {
      toast.error("Création de l'enrichissement impossible.")
      return
    }
    toast.success(
      `Enrichissement #${jobData.id} créé (${ids.length} produit${ids.length > 1 ? "s" : ""})`,
    )
    navigate(`/jobs/${jobData.id}`)
  }

  // Fichier(s) source : un lot peut contenir plusieurs fichiers d'un même bon
  // de commande. On prévisualise/télécharge celui sélectionné (index dans le
  // lot). Rétro-compat : `file_names` absent → un seul fichier (file_name).
  const fileNames = $derived(
    (job?.file_names?.length ? job.file_names : job ? [job.file_name] : []),
  )
  let selectedFileIndex = $state(0)
  const currentFileName = $derived(fileNames[selectedFileIndex] ?? job?.file_name ?? "")
  const isPdf = $derived(currentFileName.toLowerCase().endsWith(".pdf"))
  let previewOpen = $state(false)
  let previewLoading = $state(false)
  let previewError = $state<string | null>(null)
  let filePreview = $state<ImportFilePreview | null>(null)
  let filePdfUrl = $state<string | null>(null)
  let downloading = $state(false)

  $effect(() => () => {
    if (filePdfUrl) URL.revokeObjectURL(filePdfUrl)
  })

  function resetFilePreview() {
    if (filePdfUrl) URL.revokeObjectURL(filePdfUrl)
    filePdfUrl = null
    filePreview = null
    previewError = null
  }

  function selectFileIndex(index: number) {
    if (index === selectedFileIndex) return
    selectedFileIndex = index
    resetFilePreview()
    if (previewOpen) void togglePreview(true)
  }

  async function togglePreview(forceOpen = false) {
    if (previewOpen && !forceOpen) {
      previewOpen = false
      return
    }
    previewOpen = true
    if (filePreview || filePdfUrl || previewLoading) return
    previewLoading = true
    previewError = null
    if (isPdf) {
      const { data, error } = await getImportFile(Number(id), selectedFileIndex)
      if (error || !data) previewError = "Le fichier source n'est plus disponible."
      else filePdfUrl = URL.createObjectURL(data)
    } else {
      const { data, error } = await previewImportFile(Number(id), selectedFileIndex)
      if (error || !data) previewError = "Le fichier source n'est plus disponible."
      else filePreview = data
    }
    previewLoading = false
  }

  async function downloadFile() {
    if (!job || downloading) return
    downloading = true
    const { data, error } = await getImportFile(Number(id), selectedFileIndex)
    downloading = false
    if (error || !data) {
      previewError = "Le fichier source n'est plus disponible."
      previewOpen = true
      return
    }
    const url = URL.createObjectURL(data)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = currentFileName || `import-${id}`
    anchor.click()
    URL.revokeObjectURL(url)
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

  // --- Prix de vente calculé par le profil (mode coefficient uniquement).
  // Aperçu local : le calcul est appliqué dans le CSV / transfert, les
  // données extraites ne sont pas modifiées. ---
  const coefficientConfig = $derived.by(() => {
    const config = selectedProfile?.config
    if (!config || config.price_mode !== "coefficient") return null
    const coefficient = Number(config.coefficient)
    if (!Number.isFinite(coefficient) || coefficient <= 0) return null
    const step = Number(config.round_up_to)
    return {
      coefficient,
      step: Number.isFinite(step) && step > 0 ? step : 0,
    }
  })

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

<RequireAuth>
  {#snippet children(user)}
    <AppShell
      {appName}
      {user}
      breadcrumbs={[
        { label: "Imports", href: "/imports" },
        { label: job?.file_name ?? `Import #${id}` },
      ]}
    >
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        {#if errorMessage}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
          <Button variant="secondary" class="w-full sm:w-auto" onclick={() => navigate("/imports")}>
            Retour aux imports
          </Button>
        {:else if job === null}
          <Skeleton class="h-24 w-full" />
          <Skeleton class="h-16 w-full" />
        {:else}
          <div class="flex items-center justify-between gap-2">
            <h1 class="font-title min-w-0 truncate text-lg font-bold" title={job.file_name}>
              {job.file_name}
            </h1>
            <StatusBadge status={job.status} />
          </div>

          <Card>
            <CardContent class="flex flex-col gap-3">
              <dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-xs sm:grid-cols-4">
                {#if job.po_number}
                  <div>
                    <dt class="text-muted-foreground">N° de commande (PO)</dt>
                    <dd class="font-mono font-medium">{job.po_number}</dd>
                  </div>
                {/if}
                {#if job.supplier}
                  <div>
                    <dt class="text-muted-foreground">Fournisseur</dt>
                    <dd class="font-medium">{job.supplier}</dd>
                  </div>
                {/if}
                <div>
                  <dt class="text-muted-foreground">Produits extraits</dt>
                  <dd class="font-mono font-medium">{job.counts.total}</dd>
                </div>
                <div>
                  <dt class="text-muted-foreground">À vérifier</dt>
                  <dd class="font-mono font-medium">{job.counts.ready_for_review}</dd>
                </div>
                {#if job.counts.failed > 0}
                  <div>
                    <dt class="text-muted-foreground">Échecs</dt>
                    <dd class="text-destructive font-mono font-medium">{job.counts.failed}</dd>
                  </div>
                {/if}
                {#if timing}
                  <div>
                    <dt class="text-muted-foreground">{timing.label}</dt>
                    <dd class="font-mono font-medium">{timing.value}</dd>
                  </div>
                {/if}
                {#if job.totals.quantity > 0}
                  <div>
                    <dt class="text-muted-foreground">Quantité totale</dt>
                    <dd class="font-mono font-medium">{job.totals.quantity}</dd>
                  </div>
                {/if}
                {#if job.totals.wholesale_amount != null}
                  <div>
                    <dt class="text-muted-foreground">Total prix de gros</dt>
                    <dd class="font-mono font-medium">
                      {formatPrice(job.totals.wholesale_amount)}
                    </dd>
                  </div>
                {/if}
                {#if job.totals.retail_amount != null}
                  <div>
                    <dt class="text-muted-foreground">Total prix conseillé</dt>
                    <dd class="font-mono font-medium">
                      {formatPrice(job.totals.retail_amount)}
                    </dd>
                  </div>
                {/if}
              </dl>

              {#if running}
                <p class="text-muted-foreground text-xs">
                  Analyse du fichier en cours — la page se met à jour automatiquement.
                </p>
              {/if}

              {#if job.warnings.length > 0}
                <ul class="flex flex-col gap-0.5">
                  {#each job.warnings as warning, i (i)}
                    <li class="text-warning-foreground flex items-start gap-1.5 text-xs">
                      <TriangleAlert size={12} class="mt-0.5 shrink-0" aria-hidden="true" />
                      {warning}
                    </li>
                  {/each}
                </ul>
              {/if}

              {#if job.error}
                <p class="text-destructive text-xs" role="alert">{job.error}</p>
              {/if}

              <!-- Profil d'import : règles d'export Tillin appliquées au job.
                   Modifiable/créable directement pendant la review. -->
              {#if profiles !== null}
                <div class="border-border flex flex-col gap-1.5 border-t pt-3">
                  <Label for="import-profile">Profil d'import</Label>
                  {#if profiles.length === 0}
                    <p class="text-muted-foreground text-xs">
                      Aucun profil d'import — créez-en un pour générer l'export
                      Tillin. Il sera réutilisé pour les prochains imports de ce
                      fournisseur.
                    </p>
                  {:else}
                    <div class="flex flex-wrap items-center gap-2">
                      <select
                        id="import-profile"
                        class="{selectClass} sm:max-w-80"
                        disabled={settingProfile}
                        value={selectedProfileId == null ? "" : String(selectedProfileId)}
                        onchange={changeProfile}
                      >
                        <option value="">Aucun profil</option>
                        {#each profiles as profile (profile.id)}
                          <option value={String(profile.id)}>{profile.name}</option>
                        {/each}
                      </select>
                      {#if selectedProfile !== null}
                        <Button
                          variant="outline"
                          size="sm"
                          aria-expanded={profileFormMode === "edit"}
                          onclick={() =>
                            (profileFormMode = profileFormMode === "edit" ? null : "edit")}
                        >
                          <Pencil size={14} aria-hidden="true" />
                          Modifier le profil
                        </Button>
                      {/if}
                      <Button
                        variant="outline"
                        size="sm"
                        aria-expanded={profileFormMode === "new"}
                        onclick={() =>
                          (profileFormMode = profileFormMode === "new" ? null : "new")}
                      >
                        <Plus size={14} aria-hidden="true" />
                        Nouveau profil
                      </Button>
                    </div>
                    <p class="text-muted-foreground text-xs">
                      Le profil définit les règles de transformation (prix,
                      codes-barres, marque…) de l'export Tillin.
                    </p>
                    {#if profileSeason}
                      <p class="text-muted-foreground text-xs">
                        Saison imposée par le profil : «&nbsp;<span
                          class="text-foreground font-medium">{profileSeason}</span
                        >&nbsp;» — elle remplace la saison extraite du document dans
                        l'export.
                      </p>
                    {/if}
                  {/if}
                  {#if profiles.length === 0 && profileFormMode !== "new"}
                    <div>
                      <Button
                        variant="outline"
                        size="sm"
                        onclick={() => (profileFormMode = "new")}
                      >
                        <Plus size={14} aria-hidden="true" />
                        Nouveau profil
                      </Button>
                    </div>
                  {/if}

                  {#if profileFormMode !== null}
                    <div class="border-border mt-1.5 flex flex-col gap-3 rounded-md border p-3">
                      <p class="text-sm font-medium">
                        {profileFormMode === "new"
                          ? "Nouveau profil"
                          : `Modifier « ${selectedProfile?.name ?? ""} »`}
                      </p>
                      {#key `${profileFormMode}-${selectedProfileId}`}
                        <ImportProfileForm
                          profile={profileFormMode === "edit" ? selectedProfile : null}
                          prefill={profileFormMode === "new" && job.supplier
                            ? { supplier_match: job.supplier, supplier_label: job.supplier }
                            : undefined}
                          onSaved={onProfileSaved}
                          onCancel={() => (profileFormMode = null)}
                        />
                      {/key}
                    </div>
                  {/if}
                </div>
              {/if}

              <!-- Magasin de destination : corrigeable après l'extraction,
                   utilisé par défaut pour le transfert vers Tillin. -->
              {#if locations !== null && locations.length > 0}
                <div class="border-border flex flex-col gap-1.5 border-t pt-3">
                  <Label for="job-location">Magasin de destination</Label>
                  <select
                    id="job-location"
                    class="{selectClass} sm:max-w-80"
                    disabled={settingLocation}
                    value={job.location_id == null ? "" : String(job.location_id)}
                    onchange={changeLocation}
                  >
                    <option value="">À choisir plus tard</option>
                    {#each locations as location (location.id)}
                      <option value={String(location.id)}>{location.title}</option>
                    {/each}
                  </select>
                  <p class="text-muted-foreground text-xs">
                    Pré-sélectionné lors du transfert vers Tillin — corrigez ici
                    en cas d'erreur au dépôt.
                  </p>
                </div>
              {/if}

              <!-- Fichier(s) source : sélection dans le lot, aperçu à la
                   demande + re-téléchargement. -->
              <div class="border-border flex flex-col gap-3 border-t pt-3">
                {#if fileNames.length > 1}
                  <div class="flex flex-wrap gap-1.5">
                    {#each fileNames as name, index (index)}
                      <button
                        type="button"
                        class={`max-w-56 truncate rounded-full border px-2.5 py-1 text-xs transition-colors ${
                          index === selectedFileIndex
                            ? "border-primary bg-primary/10 text-foreground"
                            : "border-border text-muted-foreground hover:text-foreground"
                        }`}
                        title={name}
                        onclick={() => selectFileIndex(index)}
                      >
                        {name}
                      </button>
                    {/each}
                  </div>
                {/if}
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <p class="text-muted-foreground text-xs">
                    {fileNames.length > 1 ? "Fichier sélectionné" : "Fichier source"} :
                    <span class="text-foreground font-medium">{currentFileName}</span>
                  </p>
                  <div class="flex items-center gap-2">
                    <Button variant="outline" size="sm" onclick={() => togglePreview()}>
                      {#if previewLoading}
                        <LoaderCircle size={14} class="animate-spin" aria-hidden="true" />
                      {:else if previewOpen}
                        <EyeOff size={14} aria-hidden="true" />
                      {:else}
                        <Eye size={14} aria-hidden="true" />
                      {/if}
                      {previewOpen ? "Masquer l'aperçu" : "Prévisualiser"}
                    </Button>
                    <Button variant="outline" size="sm" disabled={downloading} onclick={downloadFile}>
                      {#if downloading}
                        <LoaderCircle size={14} class="animate-spin" aria-hidden="true" />
                      {:else}
                        <Download size={14} aria-hidden="true" />
                      {/if}
                      Télécharger
                    </Button>
                  </div>
                </div>

                {#if previewOpen}
                  {#if previewError}
                    <p class="text-destructive text-xs" role="alert">{previewError}</p>
                  {:else if previewLoading}
                    <Skeleton class="h-40 w-full" />
                  {:else if filePdfUrl}
                    <iframe
                      src={filePdfUrl}
                      title="Aperçu de {currentFileName}"
                      class="border-border h-128 w-full rounded-md border"
                    ></iframe>
                  {:else if filePreview}
                    <FilePreviewTable sheets={filePreview.sheets} />
                  {/if}
                {/if}
              </div>
            </CardContent>
          </Card>

          <h2 class="font-title mt-1 text-sm font-bold">Produits extraits</h2>
          {#if items === null}
            <Skeleton class="h-16 w-full" />
          {:else if items.length === 0}
            <Card>
              <CardContent class="text-muted-foreground py-6 text-center text-sm">
                {running
                  ? "Les produits apparaîtront ici au fil de l'analyse."
                  : "Aucun produit n'a été extrait de ce fichier."}
              </CardContent>
            </Card>
          {:else}
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
                                        <select
                                          id="item-{item.id}-{field.key}"
                                          class="{selectClass} h-8 text-xs"
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
                                        </select>
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
          {/if}

          <!-- Export Tillin : aperçu des lignes générées, CSV et transfert.
               Toujours visible quand l'analyse est terminée : sans profil, les
               actions sont désactivées avec l'explication (pas de section
               fantôme introuvable). -->
          {#if completed}
            <h2 class="font-title mt-1 text-sm font-bold">Export Tillin</h2>
            <Card>
              <CardContent class="flex flex-col gap-3">
                {#if selectedProfileId == null}
                  <p class="text-muted-foreground text-xs">
                    Sélectionnez un profil d'import (section « Profil d'import »
                    ci-dessus) pour générer l'aperçu, le CSV et le transfert
                    vers Tillin.
                  </p>
                {/if}
                <div class="flex flex-wrap items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={selectedProfileId == null}
                    onclick={toggleCsvPreview}
                  >
                    {#if rowsLoading}
                      <LoaderCircle size={14} class="animate-spin" aria-hidden="true" />
                    {:else if rowsOpen}
                      <EyeOff size={14} aria-hidden="true" />
                    {:else}
                      <Eye size={14} aria-hidden="true" />
                    {/if}
                    {rowsOpen ? "Masquer l'aperçu" : "Aperçu CSV"}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={csvDownloading || selectedProfileId == null}
                    onclick={downloadCsv}
                  >
                    {#if csvDownloading}
                      <LoaderCircle size={14} class="animate-spin" aria-hidden="true" />
                    {:else}
                      <Download size={14} aria-hidden="true" />
                    {/if}
                    Télécharger le CSV
                  </Button>
                  <Button
                    size="sm"
                    disabled={transferSummary.kept === 0 || selectedProfileId == null}
                    title={selectedProfileId == null
                      ? "Sélectionnez d'abord un profil d'import"
                      : transferSummary.kept === 0
                        ? "Aucun produit à transférer"
                        : undefined}
                    onclick={toggleTransfer}
                  >
                    <Send size={14} aria-hidden="true" />
                    Transférer {transferSummary.kept} produit{transferSummary.kept > 1
                      ? "s"
                      : ""} vers Tillin
                  </Button>
                  {#if transferSummary.applied > 0}
                    <span
                      class="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] text-emerald-600 dark:text-emerald-400"
                    >
                      {transferSummary.applied} déjà transféré{transferSummary.applied > 1
                        ? "s"
                        : ""}
                    </span>
                  {/if}
                </div>

                {#if hasTransferred}
                  <!-- Pont vers la suite du pipeline : produits créés dans Tillin. -->
                  <div class="border-border flex flex-col gap-2 border-t pt-3">
                    <p class="text-muted-foreground text-xs">
                      Les produits de cet import ont été créés dans Tillin —
                      poursuivez le pipeline.
                    </p>
                    <div class="flex flex-wrap items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onclick={() => navigate(`/products?import=${id}`)}
                      >
                        Voir les produits créés
                      </Button>
                      <EnrichChooser
                        label="Enrichir les produits créés"
                        busy={enriching}
                        onLaunch={enrichCreatedProducts}
                      />
                    </div>
                  </div>
                {/if}

                {#if rowsOpen}
                  {#if rowsError}
                    <p class="text-destructive text-xs" role="alert">{rowsError}</p>
                  {:else if rowsLoading}
                    <Skeleton class="h-40 w-full" />
                  {:else if rowsPreview}
                    {#if rowsPreview.warnings.length > 0}
                      <ul class="flex flex-col gap-0.5">
                        {#each rowsPreview.warnings as warning, i (i)}
                          <li class="text-warning-foreground flex items-start gap-1.5 text-xs">
                            <TriangleAlert size={12} class="mt-0.5 shrink-0" aria-hidden="true" />
                            {warning}
                          </li>
                        {/each}
                      </ul>
                    {/if}
                    <FilePreviewTable
                      sheets={[{ rows: [rowsPreview.columns, ...rowsPreview.rows] }]}
                    />
                    <p class="text-muted-foreground text-xs">
                      {rowsPreview.row_count}
                      ligne{rowsPreview.row_count > 1 ? "s" : ""} dans le CSV généré.
                    </p>
                  {/if}
                {/if}

                {#if transferOpen}
                  <div class="border-border flex flex-col gap-3 rounded-md border p-3">
                    <p class="text-sm font-medium">Transférer vers Tillin</p>
                    {#if locationsError}
                      <div class="flex flex-col items-start gap-2">
                        <p class="text-destructive text-xs" role="alert">{locationsError}</p>
                        <Button variant="secondary" size="sm" onclick={loadLocations}>
                          Réessayer
                        </Button>
                      </div>
                    {:else if locations === null}
                      <Skeleton class="h-9 w-full sm:max-w-80" />
                    {:else if locations.length === 0}
                      <p class="text-muted-foreground text-xs">
                        Aucun magasin disponible dans Tillin.
                      </p>
                    {:else}
                      <div class="flex flex-col gap-1.5 sm:max-w-80">
                        <Label for="transfer-location">Magasin</Label>
                        <select
                          id="transfer-location"
                          class={selectClass}
                          bind:value={selectedLocationId}
                        >
                          {#each locations as location (location.id)}
                            <option value={String(location.id)}>{location.title}</option>
                          {/each}
                        </select>
                      </div>
                      <p class="text-muted-foreground text-xs">
                        <span class="text-foreground font-medium"
                          >{transferSummary.kept} produit{transferSummary.kept > 1
                            ? "s"
                            : ""}</span
                        >
                        {transferSummary.kept > 1 ? "seront créés" : "sera créé"} dans
                        Tillin sur ce magasin{#if transferSummary.excluded > 0}, {transferSummary.excluded}
                          écarté{transferSummary.excluded > 1 ? "s" : ""} ne
                          {transferSummary.excluded > 1 ? "seront" : "sera"} pas transféré{transferSummary.excluded >
                          1
                            ? "s"
                            : ""}{/if}. Cochez ou décochez les produits dans la liste
                        pour choisir ceux à transférer.
                      </p>
                    {/if}
                    <div class="flex items-center justify-end gap-2">
                      <Button variant="ghost" size="sm" onclick={() => (transferOpen = false)}>
                        Annuler
                      </Button>
                      <Button
                        size="sm"
                        disabled={transferring ||
                          selectedLocationId === "" ||
                          transferSummary.kept === 0}
                        onclick={confirmTransfer}
                      >
                        {#if transferring}
                          <LoaderCircle size={14} class="animate-spin" aria-hidden="true" />
                        {/if}
                        {transferring
                          ? "Transfert…"
                          : `Confirmer (${transferSummary.kept})`}
                      </Button>
                    </div>
                  </div>
                {/if}
              </CardContent>
            </Card>
          {/if}
        {/if}

      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
