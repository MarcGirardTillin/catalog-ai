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
  // Résultat d'une normalisation : avant/après grand format avec poids et
  // dimensions, repositionnement manuel (aperçu en direct pendant le drag,
  // POST /render au relâchement — aucune refacturation), guides de placement,
  // zoom plein écran, renommage, enregistrement vers Tillin ou rejet.
  import ChevronDown from "@lucide/svelte/icons/chevron-down"
  import CropIcon from "@lucide/svelte/icons/crop"
  import Grid3x3 from "@lucide/svelte/icons/grid-3x3"
  import Maximize2 from "@lucide/svelte/icons/maximize-2"
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw"
  import Sparkles from "@lucide/svelte/icons/sparkles"
  import { toast } from "svelte-sonner"

  import type { ProductImage } from "@/client"
  import { insufficientCreditsMessage } from "@/lib/api/credits"
  import { fetchAssetPreviews, finalizeAsset, renderAsset } from "@/lib/api/imaging"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { ConfirmButton } from "@/lib/components/ui/confirm-button"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Select } from "@/lib/components/ui/select"
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
      crop: work.crop,
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
    work.crop = null
    cropMode = false
    cropSel = null
    scheduleRender(0)
  }

  // Échelle pilotable au clavier : champ % + crans de 5 (mêmes bornes que la
  // barre : 30 → 200 %).
  function setScalePercent(percent: number) {
    if (!Number.isFinite(percent)) return
    work.scale = Math.min(2, Math.max(0.3, Math.round(percent) / 100))
    scheduleRender()
  }

  function onScaleTyped(event: Event) {
    const input = event.currentTarget as HTMLInputElement
    setScalePercent(Number(input.value))
    input.value = String(Math.round(work.scale * 100))
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

  // --- Guides de placement (patrons) : tiers, croix centrale ---
  // Actifs par défaut (demande Marc) ; le bouton grille les masque.
  let showGuides = $state(true)
  const guidesVisible = $derived(canRender && (dragging || showGuides))

  // --- Zoom plein écran ---
  let lightboxSrc = $state<string | null>(null)

  // --- Recadrage : sélection au ratio verrouillé sur l'aperçu ---
  // La sélection vit en pixels d'affichage relatifs au conteneur ; à
  // l'application elle est convertie en pixels canevas (composée avec un
  // recadrage déjà en place — l'aperçu affiché EST la zone recadrée).
  let cropMode = $state(false)
  let cropSel = $state<{ x: number; y: number; w: number; h: number } | null>(null)
  let cropDrawing = $state(false)
  let cropStart = { x: 0, y: 0 }
  let containerEl: HTMLDivElement | null = $state(null)

  /** Boîte réellement rendue par l'aperçu object-contain (px affichage). */
  function contentBox() {
    const el = afterImg
    const w = outputFile?.width
    const h = outputFile?.height
    if (!el || !w || !h) return null
    const s = Math.min(el.clientWidth / w, el.clientHeight / h)
    return {
      left: (el.clientWidth - w * s) / 2,
      top: (el.clientHeight - h * s) / 2,
      width: w * s,
      height: h * s,
    }
  }

  function relPos(event: PointerEvent) {
    const rect = containerEl!.getBoundingClientRect()
    return { x: event.clientX - rect.left, y: event.clientY - rect.top }
  }

  function updateCropSel(event: PointerEvent) {
    const box = contentBox()
    if (!box) return
    const pos = relPos(event)
    const aspect = box.height / box.width // = ratio de sortie (verrouillé)
    const dx = pos.x - cropStart.x
    const dy = pos.y - cropStart.y
    let w = Math.max(Math.abs(dx), Math.abs(dy) / aspect)
    let h = w * aspect
    let x = dx >= 0 ? cropStart.x : cropStart.x - w
    let y = dy >= 0 ? cropStart.y : cropStart.y - h
    // Reste dans la zone d'image rendue, sans casser le ratio.
    x = Math.max(box.left, x)
    y = Math.max(box.top, y)
    const shrink = Math.min(
      1,
      (box.left + box.width - x) / w,
      (box.top + box.height - y) / h,
    )
    w *= shrink
    h *= shrink
    cropSel = { x, y, w, h }
  }

  function applyCrop() {
    const box = contentBox()
    const sel = cropSel
    const outputW = outputFile?.width
    if (!box || !sel || !outputW || sel.w < 12) return
    // px affichage → px de la sortie COURANTE (un recadrage antérieur ne
    // change pas l'échelle : c'est une coupe pixel, pas un resize).
    const factor = outputW / box.width
    const base = work.crop ?? { x: 0, y: 0 }
    work.crop = {
      x: Math.max(0, Math.round(base.x + (sel.x - box.left) * factor)),
      y: Math.max(0, Math.round(base.y + (sel.y - box.top) * factor)),
      width: Math.max(1, Math.round(sel.w * factor)),
      height: Math.max(1, Math.round(sel.h * factor)),
    }
    cropMode = false
    cropSel = null
    scheduleRender(0)
  }

  function onPointerDown(event: PointerEvent) {
    if (!canRender) return
    if (finalized && !finalizeWarned) {
      // La finalisation est « cuite » : le premier repositionnement qui suit
      // recompose depuis le cutout et l'annule — on prévient une fois.
      const proceed = window.confirm(
        "Repositionner recompose l'image et annule la finalisation IA — " +
          "une nouvelle finalisation sera facturée. Continuer ?",
      )
      if (!proceed) return
      finalizeWarned = true
    }
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
    if (cropMode) {
      cropDrawing = true
      cropStart = relPos(event)
      cropSel = null
      return
    }
    dragging = true
    dragStart = {
      x: event.clientX,
      y: event.clientY,
      offsetX: work.offsetX,
      offsetY: work.offsetY,
    }
  }

  function onPointerMove(event: PointerEvent) {
    if (cropDrawing) {
      updateCropSel(event)
      return
    }
    if (!dragging) return
    const factor = canvasFactor()
    work.offsetX = dragStart.offsetX + (event.clientX - dragStart.x) * factor
    work.offsetY = dragStart.offsetY + (event.clientY - dragStart.y) * factor
  }

  function onPointerUp() {
    if (cropDrawing) {
      cropDrawing = false
      // Un simple clic (sélection minuscule) annule la sélection en cours.
      if (cropSel && cropSel.w < 12) cropSel = null
      return
    }
    if (!dragging) return
    dragging = false
    scheduleRender(0) // POST au relâchement (pas pendant le drag)
  }

  const repositioned = $derived(
    work.offsetX !== 0 ||
      work.offsetY !== 0 ||
      work.scale !== 1 ||
      work.crop !== null,
  )

  // --- Finalisation IA (payante, « cuite » dans l'image) : ombre, décor IA,
  // défroissage, upscale, beautifier, recoloration — UN appel = UN débit.
  // À appliquer une fois le cadrage validé : un re-render local l'annule.
  const finalized = $derived(work.asset?.finalized === true)
  let showFinalize = $state(false)
  let finalizing = $state(false)
  // Avertissement « repositionner annule la finalisation » : une seule
  // confirmation par finalisation (le drag suivant recompose sans redemander).
  let finalizeWarned = false
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
    finalizeWarned = false
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
            bind:this={containerEl}
            class="relative overflow-hidden rounded-md {cropMode
              ? 'cursor-crosshair'
              : canRender
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
              <!-- Patrons : règle des tiers + croix centrale. -->
              <div class="pointer-events-none absolute inset-0" aria-hidden="true">
                <div class="absolute inset-y-0 left-1/3 w-px bg-white/50 mix-blend-difference"></div>
                <div class="absolute inset-y-0 left-2/3 w-px bg-white/50 mix-blend-difference"></div>
                <div class="absolute inset-x-0 top-1/3 h-px bg-white/50 mix-blend-difference"></div>
                <div class="absolute inset-x-0 top-2/3 h-px bg-white/50 mix-blend-difference"></div>
                <div class="absolute top-1/2 left-1/2 h-4 w-px -translate-x-1/2 -translate-y-1/2 bg-white mix-blend-difference"></div>
                <div class="absolute top-1/2 left-1/2 h-px w-4 -translate-x-1/2 -translate-y-1/2 bg-white mix-blend-difference"></div>
              </div>
            {/if}
            {#if cropMode}
              <!-- Sélection de recadrage (ratio verrouillé, tracée au drag). -->
              <div class="pointer-events-none absolute inset-0 z-10" aria-hidden="true">
                {#if cropSel}
                  <div
                    class="absolute border-2 border-white shadow-[0_0_0_9999px_rgba(0,0,0,0.45)]"
                    style="left:{cropSel.x}px;top:{cropSel.y}px;width:{cropSel.w}px;height:{cropSel.h}px"
                  ></div>
                {:else}
                  <p
                    class="bg-card/85 absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full px-3 py-1 text-[11px]"
                  >
                    Tracez la zone à conserver
                  </p>
                {/if}
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
                <button
                  type="button"
                  class="rounded-full p-1.5 transition-colors {cropMode
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-card/80 text-foreground hover:bg-card'}"
                  aria-label="Recadrer l'image"
                  aria-pressed={cropMode}
                  title="Recadrer"
                  onpointerdown={(e) => e.stopPropagation()}
                  onclick={() => {
                    cropMode = !cropMode
                    cropSel = null
                  }}
                >
                  <CropIcon size={14} />
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
        {#if canRender}
          <!-- Contrôles sous l'image MODIFIÉE, centrés (demande Marc). -->
          {#if cropMode}
            <!-- Mode recadrage : tracer, puis appliquer ou abandonner. -->
            <div class="flex flex-wrap items-center justify-center gap-2">
              <span class="text-muted-foreground w-full text-center text-xs">
                Tracez la zone à conserver — proportions verrouillées au format.
              </span>
              <Button
                size="sm"
                disabled={!cropSel || cropSel.w < 12}
                onclick={applyCrop}
              >
                <CropIcon size={13} aria-hidden="true" data-icon="inline-start" />
                Recadrer
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onclick={() => {
                  cropMode = false
                  cropSel = null
                }}
              >
                Annuler
              </Button>
            </div>
          {:else}
            <!-- Échelle (barre courte + crans de 5 + saisie directe) + reset -->
            <div class="flex flex-wrap items-center justify-center gap-2">
              <Button
                variant="outline"
                size="sm"
                class="h-7 px-2 font-mono"
                aria-label="Réduire de 5 %"
                onclick={() => setScalePercent(Math.round(work.scale * 100) - 5)}
              >
                −5
              </Button>
              <input
                type="range"
                min="0.3"
                max="2"
                step="0.05"
                class="accent-primary h-2 w-28 sm:w-36"
                aria-label="Taille du produit (%)"
                bind:value={work.scale}
                oninput={() => scheduleRender()}
              />
              <Button
                variant="outline"
                size="sm"
                class="h-7 px-2 font-mono"
                aria-label="Agrandir de 5 %"
                onclick={() => setScalePercent(Math.round(work.scale * 100) + 5)}
              >
                +5
              </Button>
              <span class="flex items-center gap-1">
                <input
                  type="number"
                  min="30"
                  max="200"
                  step="5"
                  inputmode="numeric"
                  class="border-input h-7 w-16 rounded-md border bg-transparent px-2 text-right font-mono text-xs tabular-nums"
                  aria-label="Taille du produit en pourcentage"
                  value={Math.round(work.scale * 100)}
                  onchange={onScaleTyped}
                />
                <span class="text-muted-foreground text-xs">%</span>
              </span>
              {#if repositioned}
                <Button variant="ghost" size="sm" onclick={resetPosition}>
                  <RotateCcw size={13} aria-hidden="true" data-icon="inline-start" />
                  Réinitialiser
                </Button>
              {/if}
            </div>
          {/if}
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
      <!-- Finalisation IA (optionnelle, payante) — sur la position validée. -->
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
              À appliquer une fois le cadrage validé : ces retouches sont
              intégrées à l'image — repositionner ensuite les annule (une
              nouvelle finalisation sera facturée).
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
