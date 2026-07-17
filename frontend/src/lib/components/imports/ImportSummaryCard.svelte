<script lang="ts">
  // Synthèse d'un import : faits du document, profil d'import (sélection +
  // création/édition inline), fichiers sources (aperçu/téléchargement).
  // Le magasin de destination se choisit au dépôt puis dans l'encart de
  // transfert (le doublon affiché ici a été retiré — demande Marc
  // 2026-07-17).
  import Download from "@lucide/svelte/icons/download"
  import Eye from "@lucide/svelte/icons/eye"
  import EyeOff from "@lucide/svelte/icons/eye-off"
  import LoaderCircle from "@lucide/svelte/icons/loader-circle"
  import Pencil from "@lucide/svelte/icons/pencil"
  import Plus from "@lucide/svelte/icons/plus"
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert"
  import { toast } from "svelte-sonner"

  import {
    getImportFile,
    listImportProfiles,
    previewImportFile,
    setImportProfile,
    type ImportFilePreview,
    type ImportJobPublic,
    type ImportProfilePublic,
  } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Label } from "@/lib/components/ui/label"
  import { Select } from "@/lib/components/ui/select"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import FilePreviewTable from "@/lib/components/app/FilePreviewTable.svelte"
  import ImportProfileForm from "@/lib/components/app/ImportProfileForm.svelte"
  import { formatDuration } from "@/lib/format"

  let {
    importId,
    job = $bindable(),
    profiles = $bindable(),
    selectedProfileId = $bindable(),
    onRenderConfigChanged,
  }: {
    importId: number
    job: ImportJobPublic
    profiles: ImportProfilePublic[] | null
    selectedProfileId: number | null
    /** Le rendu CSV dépend du profil : invalide l'aperçu côté export. */
    onRenderConfigChanged: () => void
  } = $props()

  const running = $derived(job.status === "pending" || job.status === "processing")

  // Durée effective ou « En cours depuis » live (tick chaque seconde).
  let now = $state(Date.now())
  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 1000)
    return () => clearInterval(t)
  })

  const timing = $derived.by(() => {
    if (job.duration_seconds != null) {
      return { label: "Durée", value: formatDuration(job.duration_seconds) }
    }
    if (job.started_at) {
      const elapsed = (now - new Date(job.started_at).getTime()) / 1000
      return { label: "En cours depuis", value: formatDuration(Math.max(0, elapsed)) }
    }
    return null
  })

  function formatPrice(raw: string | null): string {
    if (raw == null) return "—"
    const value = Number.parseFloat(raw)
    if (Number.isNaN(value)) return raw
    return value.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })
  }

  // --- Profil d'import associé au job ---
  let settingProfile = $state(false)

  const selectedProfile = $derived(
    (profiles ?? []).find((p) => p.id === selectedProfileId) ?? null,
  )

  // Saison imposée par le profil : elle REMPLACE la saison extraite du
  // document au rendu CSV / transfert.
  const profileSeason = $derived((selectedProfile?.config.season_label ?? "").trim())

  async function changeProfile(event: Event) {
    const raw = (event.currentTarget as HTMLSelectElement).value
    const next = raw === "" ? null : Number(raw)
    const previous = selectedProfileId
    selectedProfileId = next
    settingProfile = true
    const { data, error } = await setImportProfile(importId, next)
    settingProfile = false
    if (error || !data) {
      selectedProfileId = previous
      toast.error("Impossible d'associer le profil.")
      return
    }
    job = data
    onRenderConfigChanged()
    toast.success(next === null ? "Profil retiré" : "Profil appliqué")
  }

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
      const { data: updated, error } = await setImportProfile(importId, saved.id)
      if (error || !updated) {
        toast.error("Profil créé, mais impossible de l'associer au job.")
      } else {
        job = updated
        selectedProfileId = saved.id
      }
    }
    onRenderConfigChanged()
  }

  // --- Fichier(s) source : sélection dans le lot, aperçu, téléchargement ---
  const fileNames = $derived(
    job.file_names?.length ? job.file_names : [job.file_name],
  )
  let selectedFileIndex = $state(0)
  const currentFileName = $derived(fileNames[selectedFileIndex] ?? job.file_name)
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
      const { data, error } = await getImportFile(importId, selectedFileIndex)
      if (error || !data) previewError = "Le fichier source n'est plus disponible."
      else filePdfUrl = URL.createObjectURL(data)
    } else {
      const { data, error } = await previewImportFile(importId, selectedFileIndex)
      if (error || !data) previewError = "Le fichier source n'est plus disponible."
      else filePreview = data
    }
    previewLoading = false
  }

  async function downloadFile() {
    if (downloading) return
    downloading = true
    const { data, error } = await getImportFile(importId, selectedFileIndex)
    downloading = false
    if (error || !data) {
      previewError = "Le fichier source n'est plus disponible."
      previewOpen = true
      return
    }
    const url = URL.createObjectURL(data)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = currentFileName || `import-${importId}`
    anchor.click()
    URL.revokeObjectURL(url)
  }
</script>

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
            <Select
              id="import-profile"
              class="sm:max-w-80"
              disabled={settingProfile}
              value={selectedProfileId == null ? "" : String(selectedProfileId)}
              onchange={changeProfile}
            >
              <option value="">Aucun profil</option>
              {#each profiles as profile (profile.id)}
                <option value={String(profile.id)}>{profile.name}</option>
              {/each}
            </Select>
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
