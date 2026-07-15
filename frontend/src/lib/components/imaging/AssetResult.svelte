<script lang="ts" module>
  import type { ImageAssetPublic } from "@/lib/api/imaging"

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
    rendering: boolean
    saving: boolean
  }
</script>

<script lang="ts">
  // Résultat d'une normalisation : avant/après grand format avec poids et
  // dimensions, repositionnement manuel (aperçu en direct pendant le drag,
  // POST /render au relâchement — aucune refacturation), guides de placement,
  // zoom plein écran, renommage, enregistrement vers Tillin ou rejet.
  import Grid3x3 from "@lucide/svelte/icons/grid-3x3"
  import Maximize2 from "@lucide/svelte/icons/maximize-2"
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw"
  import { toast } from "svelte-sonner"

  import type { ProductImage } from "@/client"
  import { fetchAssetPreviews, renderAsset } from "@/lib/api/imaging"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { ConfirmButton } from "@/lib/components/ui/confirm-button"
  import { Input } from "@/lib/components/ui/input"
  import { formatFileSize } from "@/lib/format"

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
  const multiOutput = $derived(work.previewUrls.length > 1)
  // Le repositionnement ne s'applique qu'aux sorties uniques (normalisation).
  const canRender = $derived(
    work.asset?.can_render === true && !work.saving && !multiOutput,
  )
  const saved = $derived(work.status === "saved")

  // --- Re-render (repositionnement) : débouncé, séquencé (1 à la fois) ---
  let renderTimer: ReturnType<typeof setTimeout> | undefined
  let renderQueued = false

  function scheduleRender(delayMs = 400) {
    if (!canRender) return
    clearTimeout(renderTimer)
    renderTimer = setTimeout(() => void runRender(), delayMs)
  }

  async function runRender() {
    const asset = work.asset
    if (!asset || work.saving) return
    if (work.rendering) {
      renderQueued = true // un render tourne : rejouer à la fin
      return
    }
    work.rendering = true
    const sent = { x: Math.round(work.offsetX), y: Math.round(work.offsetY) }
    const { data, error } = await renderAsset(asset.id, {
      offset_x: sent.x,
      offset_y: sent.y,
      scale: Number(work.scale.toFixed(2)),
    })
    if (error || !data) {
      work.rendering = false
      toast.error("Recomposition impossible.")
      return
    }
    work.asset = data
    const previews = await fetchAssetPreviews(data)
    for (const url of work.previewUrls) URL.revokeObjectURL(url)
    work.previewUrls = previews
    // La nouvelle preview intègre ces offsets : le décalage CSS retombe à 0.
    renderedOffset = sent
    work.rendering = false
    if (renderQueued) {
      renderQueued = false
      scheduleRender(50) // dernière position posée pendant le render
    }
  }

  function resetPosition() {
    work.offsetX = 0
    work.offsetY = 0
    work.scale = 1
    scheduleRender(0)
  }

  // --- Drag natif sur l'aperçu : delta écran → pixels canevas ---
  let afterImg: HTMLImageElement | null = $state(null)
  let dragging = $state(false)
  let dragStart = { x: 0, y: 0, offsetX: 0, offsetY: 0 }
  // Offsets intégrés dans la preview affichée (mis à jour à chaque render) :
  // l'écart avec work.offsetX/Y se traduit en translation CSS immédiate, d'où
  // un déplacement visible PENDANT le drag (le rendu exact — produit seul
  // déplacé, fond fixe — revient au relâchement). La capture initiale est
  // voulue : c'est l'état au montage (réhydratation comprise).
  // svelte-ignore state_referenced_locally
  let renderedOffset = $state({ x: work.offsetX, y: work.offsetY })

  function canvasFactor(): number {
    const canvasWidth = outputFile?.width ?? 1600
    const displayed = afterImg?.clientWidth || 1
    return canvasWidth / displayed
  }

  const previewShift = $derived.by(() => {
    const factor = canvasFactor() || 1
    return {
      x: (work.offsetX - renderedOffset.x) / factor,
      y: (work.offsetY - renderedOffset.y) / factor,
    }
  })

  // --- Guides de placement (patrons) : tiers, croix centrale, marge 10 % ---
  let showGuides = $state(false)
  const guidesVisible = $derived(canRender && (dragging || showGuides))

  // --- Zoom plein écran ---
  let lightboxSrc = $state<string | null>(null)

  function onPointerDown(event: PointerEvent) {
    if (!canRender) return
    dragging = true
    dragStart = {
      x: event.clientX,
      y: event.clientY,
      offsetX: work.offsetX,
      offsetY: work.offsetY,
    }
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  }

  function onPointerMove(event: PointerEvent) {
    if (!dragging) return
    const factor = canvasFactor()
    work.offsetX = dragStart.offsetX + (event.clientX - dragStart.x) * factor
    work.offsetY = dragStart.offsetY + (event.clientY - dragStart.y) * factor
  }

  function onPointerUp() {
    if (!dragging) return
    dragging = false
    scheduleRender(0) // POST au relâchement (pas pendant le drag)
  }

  const repositioned = $derived(
    work.offsetX !== 0 || work.offsetY !== 0 || work.scale !== 1,
  )
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
      <!-- Après (drag pour repositionner quand sortie unique) -->
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
                  class="bg-muted aspect-4/5 w-full rounded-md object-contain"
                />
              </button>
            {/each}
          </div>
        {:else}
          <div
            class="relative overflow-hidden rounded-md {canRender
              ? 'cursor-grab'
              : ''} {dragging ? 'cursor-grabbing' : ''}"
            role="presentation"
            onpointerdown={onPointerDown}
            onpointermove={onPointerMove}
            onpointerup={onPointerUp}
            onpointercancel={onPointerUp}
          >
            {#if work.previewUrls[0]}
              <img
                bind:this={afterImg}
                src={work.previewUrls[0]}
                alt="Après"
                draggable="false"
                class="bg-muted aspect-4/5 w-full object-contain select-none {work.rendering
                  ? 'opacity-60'
                  : ''}"
                style={previewShift.x !== 0 || previewShift.y !== 0
                  ? `transform: translate(${previewShift.x}px, ${previewShift.y}px)`
                  : undefined}
              />
            {:else}
              <div class="bg-muted aspect-4/5 w-full animate-pulse rounded-md"></div>
            {/if}
            {#if guidesVisible}
              <!-- Patrons : règle des tiers, croix centrale, boîte de marge
                   10 % (miroir du margin_pct de la composition serveur). -->
              <div class="pointer-events-none absolute inset-0" aria-hidden="true">
                <div class="absolute inset-y-0 left-1/3 w-px bg-white/50 mix-blend-difference"></div>
                <div class="absolute inset-y-0 left-2/3 w-px bg-white/50 mix-blend-difference"></div>
                <div class="absolute inset-x-0 top-1/3 h-px bg-white/50 mix-blend-difference"></div>
                <div class="absolute inset-x-0 top-2/3 h-px bg-white/50 mix-blend-difference"></div>
                <div class="absolute top-1/2 left-1/2 h-4 w-px -translate-x-1/2 -translate-y-1/2 bg-white mix-blend-difference"></div>
                <div class="absolute top-1/2 left-1/2 h-px w-4 -translate-x-1/2 -translate-y-1/2 bg-white mix-blend-difference"></div>
                <div class="absolute inset-[10%] rounded-sm border border-dashed border-white/70 mix-blend-difference"></div>
              </div>
            {/if}
            {#if work.rendering}
              <span
                class="bg-card/80 absolute right-1.5 bottom-1.5 rounded-full px-2 py-0.5 text-[10px]"
              >
                Recomposition…
              </span>
            {/if}
            <!-- Outils de l'aperçu (le clic direct est réservé au drag). -->
            <div class="absolute top-1.5 right-1.5 flex gap-1">
              {#if canRender}
                <button
                  type="button"
                  class="rounded-full p-1.5 transition-colors {showGuides
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-card/80 text-foreground hover:bg-card'}"
                  aria-label="Afficher les guides de placement"
                  aria-pressed={showGuides}
                  title="Guides de placement"
                  onpointerdown={(e) => e.stopPropagation()}
                  onclick={() => (showGuides = !showGuides)}
                >
                  <Grid3x3 size={14} />
                </button>
              {/if}
              {#if work.previewUrls[0]}
                <button
                  type="button"
                  class="bg-card/80 hover:bg-card rounded-full p-1.5 transition-colors"
                  aria-label="Agrandir le résultat"
                  title="Agrandir"
                  onpointerdown={(e) => e.stopPropagation()}
                  onclick={() => (lightboxSrc = work.previewUrls[0])}
                >
                  <Maximize2 size={14} />
                </button>
              {/if}
            </div>
          </div>
        {/if}
        <figcaption class="text-muted-foreground flex justify-between text-xs">
          <span>
            {multiOutput
              ? `Visuels générés (${work.previewUrls.length})`
              : `Après${canRender ? " — glissez pour repositionner" : ""}`}
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

    {#if canRender}
      <!-- Échelle + reset -->
      <div class="flex flex-wrap items-center gap-3">
        <label class="text-muted-foreground flex grow items-center gap-2 text-xs">
          Taille
          <input
            type="range"
            min="0.3"
            max="2"
            step="0.05"
            class="accent-primary h-2 grow"
            bind:value={work.scale}
            oninput={() => scheduleRender()}
          />
          <span class="w-10 text-right font-mono tabular-nums">
            {Math.round(work.scale * 100)}%
          </span>
        </label>
        {#if repositioned}
          <Button variant="ghost" size="sm" onclick={resetPosition}>
            <RotateCcw size={13} aria-hidden="true" data-icon="inline-start" />
            Réinitialiser
          </Button>
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
            Nom du fichier (optionnel)
          </label>
          <Input
            id={`rename-${work.asset?.id ?? image.url}`}
            placeholder={filenamePlaceholder || "nom-automatique"}
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
