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
  // dimensions, repositionnement manuel (drag + zoom → POST /render, aucune
  // refacturation), renommage et enregistrement vers Tillin.
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw"
  import { toast } from "svelte-sonner"

  import type { ProductImage } from "@/client"
  import { fetchAssetPreviews, renderAsset } from "@/lib/api/imaging"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { formatFileSize } from "@/lib/format"

  let {
    image,
    work,
    filenamePlaceholder = "",
    onSave,
  }: {
    image: ProductImage
    work: Work
    filenamePlaceholder?: string
    onSave: () => void
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
    const { data, error } = await renderAsset(asset.id, {
      offset_x: Math.round(work.offsetX),
      offset_y: Math.round(work.offsetY),
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

  function canvasFactor(): number {
    const canvasWidth = outputFile?.width ?? 1600
    const displayed = afterImg?.clientWidth || 1
    return canvasWidth / displayed
  }

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
      <!-- Avant -->
      <figure class="flex flex-col gap-1">
        <img
          src={image.url}
          alt="Avant"
          class="bg-muted aspect-4/5 w-full rounded-md object-contain"
        />
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
              <img
                src={preview}
                alt={`Visuel généré ${index + 1}`}
                class="bg-muted aspect-4/5 w-full rounded-md object-contain"
              />
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
              />
            {:else}
              <div class="bg-muted aspect-4/5 w-full animate-pulse rounded-md"></div>
            {/if}
            {#if work.rendering}
              <span
                class="bg-card/80 absolute right-1.5 bottom-1.5 rounded-full px-2 py-0.5 text-[10px]"
              >
                Recomposition…
              </span>
            {/if}
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
