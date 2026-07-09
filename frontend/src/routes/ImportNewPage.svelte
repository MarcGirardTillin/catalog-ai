<script lang="ts">
  import FileUp from "@lucide/svelte/icons/file-up"
  import FileText from "@lucide/svelte/icons/file-text"
  import LoaderCircle from "@lucide/svelte/icons/loader-circle"
  import X from "@lucide/svelte/icons/x"
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import { createImport } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
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

  let file = $state<File | null>(null)
  let errorMessage = $state<string | null>(null)
  let dragging = $state(false)
  let submitting = $state(false)
  let fileInput = $state<HTMLInputElement | null>(null)

  // Aperçu avant envoi : PDF via le lecteur du navigateur, CSV parsé côté
  // client ; l'Excel n'est prévisualisable qu'après l'import (parse serveur).
  let pdfPreviewUrl = $state<string | null>(null)
  let csvPreviewRows = $state<string[][] | null>(null)

  function resetPreview() {
    if (pdfPreviewUrl) URL.revokeObjectURL(pdfPreviewUrl)
    pdfPreviewUrl = null
    csvPreviewRows = null
  }

  $effect(() => () => resetPreview())

  async function buildPreview(candidate: File) {
    resetPreview()
    const name = candidate.name.toLowerCase()
    if (name.endsWith(".pdf")) {
      pdfPreviewUrl = URL.createObjectURL(candidate)
    } else if (name.endsWith(".csv")) {
      const text = await readTextWithFallback(candidate)
      // Le fichier a pu être retiré pendant la lecture asynchrone.
      if (file === candidate) csvPreviewRows = parseCsvPreview(text, 50)
    }
  }

  function validate(candidate: File): string | null {
    const name = candidate.name.toLowerCase()
    if (!ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
      return "Format non pris en charge — choisissez un fichier .pdf, .xlsx ou .csv."
    }
    if (candidate.size > MAX_SIZE_BYTES) {
      return `Fichier trop volumineux (${formatFileSize(candidate.size)}) — maximum 20 Mo.`
    }
    return null
  }

  function selectFile(candidate: File | undefined) {
    if (!candidate) return
    const problem = validate(candidate)
    if (problem) {
      errorMessage = problem
      file = null
      resetPreview()
      return
    }
    errorMessage = null
    file = candidate
    void buildPreview(candidate)
  }

  function onInputChange(event: Event) {
    const input = event.currentTarget as HTMLInputElement
    selectFile(input.files?.[0])
    // Autorise la re-sélection du même fichier après un retrait.
    input.value = ""
  }

  function onDrop(event: DragEvent) {
    event.preventDefault()
    dragging = false
    selectFile(event.dataTransfer?.files?.[0])
  }

  function clearFile() {
    file = null
    errorMessage = null
    resetPreview()
  }

  async function onSubmit() {
    if (!file || submitting) return
    submitting = true
    const { data, error } = await createImport(file)
    submitting = false
    if (error || !data) {
      toast.error("Import impossible. Vérifiez le fichier et réessayez.")
      return
    }
    toast.success(`Import de « ${data.file_name} » lancé — analyse en cours`)
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
      <div class="mx-auto max-w-4xl p-4">
        <Card>
          <CardHeader>
            <CardTitle class="font-title text-lg">Importer un fichier fournisseur</CardTitle>
            <CardDescription>
              Le fichier est analysé par IA pour en extraire les produits (référence,
              coloris, tailles, EAN, prix) — vous vérifierez le résultat avant tout envoi
              vers Tillin.
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
                Glissez-déposez votre fichier ici, ou cliquez pour parcourir
              </p>
              <p class="text-muted-foreground text-xs">PDF, Excel (.xlsx) ou CSV — 20 Mo maximum</p>
            </div>
            <input
              bind:this={fileInput}
              type="file"
              accept=".pdf,.xlsx,.csv"
              class="hidden"
              onchange={onInputChange}
            />

            {#if errorMessage}
              <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
            {/if}

            {#if file}
              <div class="border-border bg-card flex items-center gap-3 rounded-md border px-3 py-2.5">
                <FileText size={18} class="text-muted-foreground shrink-0" aria-hidden="true" />
                <div class="flex min-w-0 flex-1 flex-col">
                  <span class="truncate text-sm font-medium" title={file.name}>{file.name}</span>
                  <span class="text-muted-foreground text-xs">{formatFileSize(file.size)}</span>
                </div>
                <button
                  type="button"
                  class="text-muted-foreground hover:text-foreground shrink-0 cursor-pointer p-1 transition-colors"
                  aria-label="Retirer le fichier"
                  disabled={submitting}
                  onclick={clearFile}
                >
                  <X size={16} />
                </button>
              </div>

              {#if pdfPreviewUrl}
                <iframe
                  src={pdfPreviewUrl}
                  title="Aperçu de {file.name}"
                  class="border-border h-96 w-full rounded-md border"
                ></iframe>
              {:else if csvPreviewRows}
                {#if csvPreviewRows.length === 0}
                  <p class="text-muted-foreground text-xs">
                    Le fichier semble vide — vérifiez son contenu avant de lancer l'analyse.
                  </p>
                {:else}
                  <FilePreviewTable sheets={[{ rows: csvPreviewRows }]} />
                  <p class="text-muted-foreground text-xs">
                    Aperçu des 50 premières lignes.
                  </p>
                {/if}
              {:else if file.name.toLowerCase().endsWith(".xlsx")}
                <p class="text-muted-foreground text-xs">
                  Aperçu indisponible pour Excel avant l'analyse — il sera consultable sur la
                  page de l'import.
                </p>
              {/if}
            {/if}

            <Button
              size="lg"
              class="h-10 w-full text-sm"
              disabled={!file || submitting}
              onclick={onSubmit}
            >
              {#if submitting}
                <LoaderCircle size={16} class="animate-spin" aria-hidden="true" />
                Envoi du fichier…
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
