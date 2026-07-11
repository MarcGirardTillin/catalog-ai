<script lang="ts">
  import FileUp from "@lucide/svelte/icons/file-up"
  import FileText from "@lucide/svelte/icons/file-text"
  import LoaderCircle from "@lucide/svelte/icons/loader-circle"
  import X from "@lucide/svelte/icons/x"
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import { onMount } from "svelte"

  import {
    createImport,
    listImportProfiles,
    listLocations,
    type ImportProfilePublic,
    type LocationPublic,
  } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
  import { Label } from "@/lib/components/ui/label"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import FilePreviewTable from "@/lib/components/app/FilePreviewTable.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import { parseCsvPreview, readTextWithFallback } from "@/lib/csv-preview"
  import { formatFileSize } from "@/lib/format"

  let { appName }: { appName: string } = $props()

  const ACCEPTED_EXTENSIONS = [".pdf", ".xlsx", ".csv"]
  const MAX_SIZE_BYTES = 20 * 1000 * 1000 // 20 Mo, aligné sur la limite serveur.

  // Plusieurs fichiers d'un même bon de commande : leurs infos sont croisées
  // en une seule analyse (une réf peut avoir son EAN dans un fichier et son
  // prix dans un autre). Chaque fichier porte son propre aperçu.
  type StagedFile = { id: string; file: File; pdfUrl: string | null; csvRows: string[][] | null }
  let files = $state<StagedFile[]>([])
  let errorMessage = $state<string | null>(null)
  let dragging = $state(false)
  let submitting = $state(false)
  let fileInput = $state<HTMLInputElement | null>(null)

  // Magasin de destination : optionnel au dépôt (modifiable ensuite sur la
  // page de l'import). Pré-sélectionné s'il n'y a qu'un seul magasin.
  let locations = $state<LocationPublic[] | null>(null)
  let selectedLocationId = $state("")

  // Profil d'import (règles d'export Tillin), choisi dès le dépôt. Vide =
  // « Automatique » : le backend l'auto-suggère après extraction (fournisseur).
  let profiles = $state<ImportProfilePublic[]>([])
  let selectedProfileId = $state("")

  onMount(() => {
    listLocations().then(({ data }) => {
      locations = data ?? []
      if (data && data.length === 1) selectedLocationId = String(data[0].id)
    })
    listImportProfiles().then(({ data }) => {
      profiles = data ?? []
    })
  })

  function resetPreviews() {
    for (const f of files) if (f.pdfUrl) URL.revokeObjectURL(f.pdfUrl)
  }

  $effect(() => () => resetPreviews())

  function validate(candidate: File): string | null {
    const name = candidate.name.toLowerCase()
    if (!ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
      return `${candidate.name} : format non pris en charge (.pdf, .xlsx ou .csv).`
    }
    if (candidate.size > MAX_SIZE_BYTES) {
      return `${candidate.name} : trop volumineux (${formatFileSize(candidate.size)}) — maximum 20 Mo.`
    }
    return null
  }

  async function buildPreview(entry: StagedFile) {
    const name = entry.file.name.toLowerCase()
    if (name.endsWith(".pdf")) {
      entry.pdfUrl = URL.createObjectURL(entry.file)
    } else if (name.endsWith(".csv")) {
      const text = await readTextWithFallback(entry.file)
      // L'entrée a pu être retirée pendant la lecture asynchrone.
      if (files.some((f) => f.id === entry.id)) {
        entry.csvRows = parseCsvPreview(text, 50)
      }
    }
  }

  function addFiles(candidates: FileList | File[] | undefined) {
    if (!candidates) return
    for (const candidate of Array.from(candidates)) {
      const problem = validate(candidate)
      if (problem) {
        errorMessage = problem
        continue
      }
      errorMessage = null
      const entry: StagedFile = {
        id: crypto.randomUUID(),
        file: candidate,
        pdfUrl: null,
        csvRows: null,
      }
      files.push(entry)
      void buildPreview(entry)
    }
  }

  function onInputChange(event: Event) {
    const input = event.currentTarget as HTMLInputElement
    addFiles(input.files ?? undefined)
    // Autorise la re-sélection des mêmes fichiers après un retrait.
    input.value = ""
  }

  function onDrop(event: DragEvent) {
    event.preventDefault()
    dragging = false
    addFiles(event.dataTransfer?.files ?? undefined)
  }

  function removeFile(id: string) {
    const index = files.findIndex((f) => f.id === id)
    if (index < 0) return
    const [removed] = files.splice(index, 1)
    if (removed.pdfUrl) URL.revokeObjectURL(removed.pdfUrl)
  }

  async function onSubmit() {
    if (files.length === 0 || submitting) return
    submitting = true
    const { data, error } = await createImport(
      files.map((f) => f.file),
      selectedLocationId === "" ? undefined : Number(selectedLocationId),
      selectedProfileId === "" ? undefined : Number(selectedProfileId),
    )
    submitting = false
    if (error || !data) {
      toast.error("Import impossible. Vérifiez les fichiers et réessayez.")
      return
    }
    const count = data.file_names?.length ?? 1
    toast.success(
      count > 1
        ? `Import de ${count} fichiers lancé — analyse en cours`
        : `Import de « ${data.file_name} » lancé — analyse en cours`,
    )
    navigate(`/imports/${data.id}`)
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell
      {appName}
      {user}
      breadcrumbs={[{ label: "Imports", href: "/imports" }, { label: "Nouvel import" }]}
    >
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <h1 class="font-title text-lg font-bold">Nouvel import</h1>
        <Card>
          <CardHeader>
            <CardTitle class="font-title text-sm">Importer un fichier fournisseur</CardTitle>
            <CardDescription>
              Les fichiers sont analysés par IA pour en extraire les produits (référence,
              coloris, tailles, EAN, prix) — vous vérifierez le résultat avant tout envoi
              vers Tillin. Déposez plusieurs fichiers d'un même bon de commande pour croiser
              leurs informations.
            </CardDescription>
          </CardHeader>
          <CardContent class="flex flex-col gap-4">
            <!-- Dropzone : clic ou glisser-déposer, input file caché. -->
            <div
              role="button"
              tabindex="0"
              aria-label="Choisir un fichier à importer (PDF, Excel ou CSV)"
              class="bg-card flex cursor-pointer flex-col items-center gap-2 rounded-md border-2 border-dashed px-4 py-10 text-center transition-colors {dragging
                ? 'border-primary bg-muted/50'
                : 'border-border hover:border-muted-foreground/50'}"
              onclick={() => fileInput?.click()}
              onkeydown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  fileInput?.click()
                }
              }}
              ondragover={(e) => {
                e.preventDefault()
                dragging = true
              }}
              ondragleave={() => (dragging = false)}
              ondrop={onDrop}
            >
              <span
                class="bg-muted text-muted-foreground flex size-10 items-center justify-center rounded-full"
                aria-hidden="true"
              >
                <FileUp size={18} />
              </span>
              <p class="text-sm font-medium">
                Glissez-déposez vos fichiers ici, ou cliquez pour parcourir
              </p>
              <p class="text-muted-foreground text-xs">
                PDF, Excel (.xlsx) ou CSV — 20 Mo maximum par fichier
              </p>
            </div>
            <input
              bind:this={fileInput}
              type="file"
              accept=".pdf,.xlsx,.csv"
              multiple
              class="hidden"
              onchange={onInputChange}
            />

            {#if errorMessage}
              <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
            {/if}

            {#each files as entry (entry.id)}
              <div class="flex flex-col gap-2">
                <div class="border-border bg-card flex items-center gap-3 rounded-md border px-3 py-2.5">
                  <FileText size={18} class="text-muted-foreground shrink-0" aria-hidden="true" />
                  <div class="flex min-w-0 flex-1 flex-col">
                    <span class="truncate text-sm font-medium" title={entry.file.name}>
                      {entry.file.name}
                    </span>
                    <span class="text-muted-foreground text-xs">
                      {formatFileSize(entry.file.size)}
                    </span>
                  </div>
                  <button
                    type="button"
                    class="text-muted-foreground hover:text-foreground shrink-0 cursor-pointer p-1 transition-colors"
                    aria-label="Retirer {entry.file.name}"
                    disabled={submitting}
                    onclick={() => removeFile(entry.id)}
                  >
                    <X size={16} />
                  </button>
                </div>

                {#if entry.pdfUrl}
                  <iframe
                    src={entry.pdfUrl}
                    title="Aperçu de {entry.file.name}"
                    class="border-border h-96 w-full rounded-md border"
                  ></iframe>
                {:else if entry.csvRows}
                  {#if entry.csvRows.length === 0}
                    <p class="text-muted-foreground text-xs">
                      {entry.file.name} semble vide — vérifiez son contenu.
                    </p>
                  {:else}
                    <FilePreviewTable sheets={[{ rows: entry.csvRows }]} />
                    <p class="text-muted-foreground text-xs">Aperçu des 50 premières lignes.</p>
                  {/if}
                {:else if entry.file.name.toLowerCase().endsWith(".xlsx")}
                  <p class="text-muted-foreground text-xs">
                    Aperçu indisponible pour Excel avant l'analyse — consultable sur la
                    page de l'import.
                  </p>
                {/if}
              </div>
            {/each}

            {#if files.length > 1}
              <p class="text-muted-foreground text-xs">
                {files.length} fichiers seront analysés ensemble et leurs informations croisées.
              </p>
            {/if}

            {#if profiles.length > 0}
              <div class="flex flex-col gap-1.5 sm:max-w-80">
                <Label for="import-profile">Profil d'import</Label>
                <select
                  id="import-profile"
                  class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                  disabled={submitting}
                  bind:value={selectedProfileId}
                >
                  <option value="">Automatique (selon le fournisseur)</option>
                  {#each profiles as profile (profile.id)}
                    <option value={String(profile.id)}>{profile.name}</option>
                  {/each}
                </select>
                <p class="text-muted-foreground text-xs">
                  Règles d'export vers Tillin (prix, marque, code-barres). Modifiable
                  ensuite sur la page de l'import.
                </p>
              </div>
            {/if}

            {#if locations !== null && locations.length > 0}
              <div class="flex flex-col gap-1.5 sm:max-w-80">
                <Label for="import-location">Magasin de destination</Label>
                <select
                  id="import-location"
                  class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                  disabled={submitting}
                  bind:value={selectedLocationId}
                >
                  <option value="">À choisir plus tard</option>
                  {#each locations as location (location.id)}
                    <option value={String(location.id)}>{location.title}</option>
                  {/each}
                </select>
                <p class="text-muted-foreground text-xs">
                  Modifiable ensuite sur la page de l'import, avant le transfert
                  vers Tillin.
                </p>
              </div>
            {/if}

            <Button
              size="lg"
              class="h-10 w-full text-sm"
              disabled={files.length === 0 || submitting}
              onclick={onSubmit}
            >
              {#if submitting}
                <LoaderCircle size={16} class="animate-spin" aria-hidden="true" />
                {files.length > 1 ? "Envoi des fichiers…" : "Envoi du fichier…"}
              {:else}
                Lancer l'analyse
              {/if}
            </Button>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
