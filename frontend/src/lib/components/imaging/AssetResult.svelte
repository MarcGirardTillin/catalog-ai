<script lang="ts" module>
  import type { CropBox, ImageAssetPublic } from "@/lib/api/imaging"

  // État de travail d'une image source dans le studio (possédé par la page,
  // muté ici pour le repositionnement).
  export type Work = {
    status: "idle" | "running" | "done" | "failed" | "saved"
    asset: ImageAssetPublic | null
    previewUrls: string[]
    error: string | null
    filename: string
    replace: boolean
    offsetX: number
    offsetY: number
    scale: number
    /** Recadrage appliqué (px canevas), null = image entière. */
    crop: CropBox | null
    rendering: boolean
    saving: boolean
    /** Nom déjà pré-rempli depuis le modèle de titre (ne pas re-remplir si
     *  l'utilisateur vide le champ ensuite). */
    filenamePrefilled?: boolean
  }
</script>

<script lang="ts">
  // Résultat d'un traitement : avant/après grand format avec poids et
  // dimensions, cadrage sous l'image (CropEditor — gratuit, conserve une
  // finalisation IA), finalisation IA optionnelle, zoom plein écran,
  // renommage, enregistrement vers Tillin ou rejet.
  import ChevronDown from "@lucide/svelte/icons/chevron-down"
  import Sparkles from "@lucide/svelte/icons/sparkles"
  import { toast } from "svelte-sonner"

  import type { ProductImage } from "@/client"
  import { insufficientCreditsMessage } from "@/lib/api/credits"
  import { fetchAssetPreviews, finalizeAsset } from "@/lib/api/imaging"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { ConfirmButton } from "@/lib/components/ui/confirm-button"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Select } from "@/lib/components/ui/select"
  import { formatFileSize } from "@/lib/format"

  import CropEditor from "./CropEditor.svelte"
  import Lightbox from "./Lightbox.svelte"

  let {
    image,
    work,
    filenamePlaceholder = "",
    onSave,
    onDiscard = null,
  }: {
    image: ProductImage
    work: Work
    filenamePlaceholder?: string
    onSave: () => void
    onDiscard?: (() => void) | null
  } = $props()

  const outputFile = $derived(work.asset?.files?.[0] ?? null)

  // Cadre « Après » au ratio RÉEL de la sortie : un cadre 4:5 figé autour
  // d'une sortie carrée montrait des bandes grises (bg-muted) que l'œil
  // prenait pour le fond de l'image (vécu : « fond e4e4e4 ? »). Repli 4:5
  // tant que les dimensions ne sont pas connues.
  const outputAspect = $derived(
    outputFile?.width && outputFile?.height
      ? `${outputFile.width} / ${outputFile.height}`
      : "4 / 5",
  )
  const multiOutput = $derived(work.previewUrls.length > 1)
  const saved = $derived(work.status === "saved")
  // Cadrage sous l'image (recadrage, zoom, rotation, miroir, taille) : toute
  // sortie unique non enregistrée — génération comprise — sans perdre une
  // finalisation IA. Il remplace l'ancien repositionnement du produit.
  const canEdit = $derived(
    work.asset?.can_edit === true && !work.saving && !multiOutput,
  )
  // La finalisation IA reste réservée aux normalisations (cutout disponible).
  const canFinalize = $derived(
    work.asset?.can_render === true && !work.saving && !multiOutput,
  )

  async function onEdited(asset: ImageAssetPublic) {
    work.asset = asset
    const previews = await fetchAssetPreviews(asset)
    for (const url of work.previewUrls) URL.revokeObjectURL(url)
    work.previewUrls = previews
  }

  // --- Zoom plein écran ---
  let lightboxSrc = $state<string | null>(null)

  // --- Finalisation IA (payante, « cuite » dans l'image) : ombre, décor IA,
  // défroissage, upscale, beautifier, recoloration — UN appel = UN débit.
  // Le cadrage la conserve (il est rejoué sur l'image finalisée).
  const finalized = $derived(work.asset?.finalized === true)
  let showFinalize = $state(false)
  let finalizing = $state(false)
  let fin = $state({
    shadowMode: "" as "" | "soft" | "hard" | "floating",
    backgroundKind: "keep" as "keep" | "prompt",
    backgroundPrompt: "",
    ironing: false,
    beautify: false,
    upscale: false,
    recolor: "",
  })
  const finHasOption = $derived(
    fin.shadowMode !== "" ||
      (fin.backgroundKind === "prompt" && fin.backgroundPrompt.trim() !== "") ||
      fin.ironing ||
      fin.beautify ||
      fin.upscale ||
      fin.recolor.trim() !== "",
  )

  async function runFinalize() {
    const asset = work.asset
    if (!asset || finalizing || work.rendering || work.saving) return
    finalizing = true
    const { data, error } = await finalizeAsset(asset.id, {
      shadow_mode: fin.shadowMode || null,
      background_prompt:
        fin.backgroundKind === "prompt" ? fin.backgroundPrompt.trim() || null : null,
      ironing: fin.ironing,
      beautify: fin.beautify,
      upscale: fin.upscale,
      recolor_prompt: fin.recolor.trim() || null,
    })
    finalizing = false
    if (error || !data) {
      toast.error(
        insufficientCreditsMessage(error) ??
          "Finalisation impossible (service d'imagerie indisponible ?).",
      )
      return
    }
    work.asset = data
    const previews = await fetchAssetPreviews(data)
    for (const url of work.previewUrls) URL.revokeObjectURL(url)
    work.previewUrls = previews
    showFinalize = false
    toast.success("Image finalisée")
  }
</script>

<Card size="sm">
  <CardContent class="flex flex-col gap-3">
    <div class="grid gap-3 sm:grid-cols-2">
      <!-- Avant (clic = zoom) -->
      <figure class="flex flex-col gap-1">
        <button
          type="button"
          class="cursor-zoom-in"
          aria-label="Agrandir l'image d'origine"
          onclick={() => (lightboxSrc = image.url)}
        >
          <img
            src={image.url}
            alt="Avant"
            class="bg-muted aspect-4/5 w-full rounded-md object-contain"
          />
        </button>
        <figcaption class="text-muted-foreground flex justify-between text-xs">
          <span>Avant</span>
          <span class="tabular-nums">
            {work.asset?.source_width
              ? `${work.asset.source_width}×${work.asset.source_height}`
              : ""}
            {work.asset?.source_size_bytes
              ? ` · ${formatFileSize(work.asset.source_size_bytes)}`
              : ""}
          </span>
        </figcaption>
      </figure>
      <!-- Après : éditeur de cadrage quand la sortie est éditable. -->
      <figure class="flex flex-col gap-1">
        {#if multiOutput}
          <div class="grid grid-cols-2 gap-2">
            {#each work.previewUrls as preview, index (preview)}
              <button
                type="button"
                class="cursor-zoom-in"
                aria-label={`Agrandir le visuel ${index + 1}`}
                onclick={() => (lightboxSrc = preview)}
              >
                <img
                  src={preview}
                  alt={`Visuel généré ${index + 1}`}
                  class="bg-muted w-full rounded-md object-contain"
                  style={`aspect-ratio: ${outputAspect}`}
                />
              </button>
            {/each}
          </div>
        {:else if canEdit && work.asset}
          {#key work.asset.id}
            <CropEditor asset={work.asset} onApplied={onEdited} />
          {/key}
        {:else if work.previewUrls[0]}
          <button
            type="button"
            class="cursor-zoom-in"
            aria-label="Agrandir le résultat"
            onclick={() => (lightboxSrc = work.previewUrls[0])}
          >
            <img
              src={work.previewUrls[0]}
              alt="Après"
              class="bg-muted w-full rounded-md object-contain"
              style={`aspect-ratio: ${outputAspect}`}
            />
          </button>
        {:else}
          <div class="bg-muted aspect-4/5 w-full animate-pulse rounded-md"></div>
        {/if}
        <figcaption class="text-muted-foreground flex justify-between text-xs">
          <span>
            {#if multiOutput}
              Visuels générés ({work.previewUrls.length})
            {:else if !canEdit}
              Après
            {:else if work.previewUrls[0]}
              <button
                type="button"
                class="hover:text-foreground underline-offset-2 hover:underline"
                onclick={() => (lightboxSrc = work.previewUrls[0])}
              >
                agrandir le résultat
              </button>
            {/if}
          </span>
          <span class="tabular-nums">
            {outputFile?.width ? `${outputFile.width}×${outputFile.height}` : ""}
            {outputFile?.size_bytes
              ? ` · ${formatFileSize(outputFile.size_bytes)}`
              : ""}
          </span>
        </figcaption>
      </figure>
    </div>

    {#if canFinalize}
      <!-- Finalisation IA (optionnelle, payante). -->
      <div class="border-border rounded-md border">
        <button
          type="button"
          class="text-foreground flex w-full items-center justify-between gap-2 px-3 py-2 text-sm"
          aria-expanded={showFinalize}
          onclick={() => (showFinalize = !showFinalize)}
        >
          <span class="flex items-center gap-2">
            <Sparkles size={14} aria-hidden="true" class="text-primary" />
            Finalisation IA (optionnelle)
            {#if finalized}
              <span
                class="bg-primary/10 text-primary rounded-full px-2 py-0.5 text-[10px] font-medium"
              >
                Finalisée
              </span>
            {/if}
          </span>
          <ChevronDown
            size={14}
            aria-hidden="true"
            class="transition-transform {showFinalize ? 'rotate-180' : ''}"
          />
        </button>
        {#if showFinalize}
          <div class="flex flex-col gap-3 px-3 pb-3">
            <p class="text-muted-foreground text-xs">
              Ces retouches sont intégrées à l'image ; le cadrage les
              conserve (il est rejoué sur l'image finalisée).
            </p>
            <div class="grid gap-3 sm:grid-cols-2">
              <div class="flex flex-col gap-1.5">
                <Label for={`fin-shadow-${work.asset?.id}`}>Ombre portée</Label>
                <Select
                  id={`fin-shadow-${work.asset?.id}`}
                  disabled={finalizing}
                  bind:value={fin.shadowMode}
                >
                  <option value="">Aucune</option>
                  <option value="soft">Douce</option>
                  <option value="hard">Dure</option>
                  <option value="floating">Flottante</option>
                </Select>
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for={`fin-bg-${work.asset?.id}`}>Arrière-plan</Label>
                <Select
                  id={`fin-bg-${work.asset?.id}`}
                  disabled={finalizing}
                  bind:value={fin.backgroundKind}
                >
                  <option value="keep">Conserver la couleur</option>
                  <option value="prompt">Décor IA (décrit ci-dessous)</option>
                </Select>
              </div>
            </div>
            {#if fin.backgroundKind === "prompt"}
              <div class="flex flex-col gap-1.5">
                <Label for={`fin-bg-prompt-${work.asset?.id}`}>Décor IA</Label>
                <textarea
                  id={`fin-bg-prompt-${work.asset?.id}`}
                  rows="2"
                  class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content max-h-40 w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                  placeholder="Décrivez le décor… (ex. table en marbre, lumière douce)"
                  disabled={finalizing}
                  bind:value={fin.backgroundPrompt}
                ></textarea>
              </div>
            {/if}
            <div class="flex flex-wrap items-center gap-4">
              <label class="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  class="accent-primary size-4"
                  disabled={finalizing}
                  bind:checked={fin.ironing}
                />
                Défroissage du vêtement (IA)
              </label>
              <label class="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  class="accent-primary size-4"
                  disabled={finalizing}
                  bind:checked={fin.beautify}
                />
                Retouche beauté (IA)
              </label>
              <label class="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  class="accent-primary size-4"
                  disabled={finalizing}
                  bind:checked={fin.upscale}
                />
                Agrandissement ×4 (IA)
                <span class="text-muted-foreground text-xs">
                  — images jusqu'à 1 Mpx (ex. sortie recadrée)
                </span>
              </label>
            </div>
            <div class="flex min-w-48 flex-col gap-1.5">
              <Label for={`fin-recolor-${work.asset?.id}`}>
                Recoloration du vêtement (optionnel)
              </Label>
              <Input
                id={`fin-recolor-${work.asset?.id}`}
                placeholder="Ex. bordeaux, bleu marine délavé…"
                disabled={finalizing}
                bind:value={fin.recolor}
              />
            </div>
            <div class="flex justify-end">
              <Button
                size="sm"
                disabled={!finHasOption || finalizing || work.rendering}
                onclick={runFinalize}
              >
                {finalizing ? "Finalisation…" : "Finaliser l'image (5 crédits)"}
              </Button>
            </div>
          </div>
        {/if}
      </div>
    {/if}

    <!-- Nom de fichier + enregistrement -->
    <div class="flex flex-wrap items-end gap-2">
      {#if !multiOutput}
        <div class="flex min-w-48 grow flex-col gap-1">
          <label
            class="text-muted-foreground text-xs"
            for={`rename-${work.asset?.id ?? image.url}`}
          >
            Nom du fichier
            {#if filenamePlaceholder}
              <span class="opacity-70">— pré-rempli selon le modèle de titre d'image</span>
            {:else}
              (optionnel)
            {/if}
          </label>
          <Input
            id={`rename-${work.asset?.id ?? image.url}`}
            placeholder="nom-automatique"
            disabled={saved || work.saving}
            bind:value={work.filename}
          />
        </div>
      {:else}
        <p class="text-muted-foreground grow self-center text-xs">
          Plusieurs visuels : les noms suivent le modèle de titre d'image.
        </p>
      {/if}
      {#if image.id != null}
        <label class="flex h-9 items-center gap-2 text-sm">
          <input
            type="checkbox"
            class="accent-primary size-4"
            disabled={saved || work.saving}
            bind:checked={work.replace}
          />
          Remplacer l'originale
        </label>
      {/if}
      {#if onDiscard && !saved}
        <ConfirmButton
          label="Écarter"
          variant="outline"
          class="text-destructive"
          disabled={work.saving || work.rendering}
          onconfirm={onDiscard}
        />
      {/if}
      <Button
        size="sm"
        disabled={saved || work.saving || work.rendering}
        onclick={onSave}
      >
        {saved
          ? "Enregistrée ✓"
          : work.saving
            ? "Enregistrement…"
            : "Enregistrer dans Tillin"}
      </Button>
    </div>
    {#if work.error}
      <p class="text-destructive text-xs" role="alert">{work.error}</p>
    {/if}
  </CardContent>
</Card>

{#if lightboxSrc}
  <Lightbox src={lightboxSrc} onClose={() => (lightboxSrc = null)} />
{/if}
