<script lang="ts">
  // « Modifier l'image » (modèle : éditeur de la fiche produit Tillin) : le
  // cadre reste fixe, l'image se déplace (glisser, flèches) et se zoome
  // (molette, curseur, boutons) dessous ; formats 1:1 · 16:9 · 4:5 · 5:4 ·
  // Libre, quart de tour, miroir, taille de sortie. L'aperçu « Rendu » est
  // calculé dans le navigateur ; Valider envoie l'édition au serveur, qui
  // l'applique à la sortie courante — finalisation IA comprise.
  import ArrowDown from "@lucide/svelte/icons/arrow-down"
  import ArrowLeft from "@lucide/svelte/icons/arrow-left"
  import ArrowRight from "@lucide/svelte/icons/arrow-right"
  import ArrowUp from "@lucide/svelte/icons/arrow-up"
  import FlipHorizontal2 from "@lucide/svelte/icons/flip-horizontal-2"
  import FlipVertical2 from "@lucide/svelte/icons/flip-vertical-2"
  import LoaderCircle from "@lucide/svelte/icons/loader-circle"
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw"
  import RotateCw from "@lucide/svelte/icons/rotate-cw"
  import ZoomIn from "@lucide/svelte/icons/zoom-in"
  import ZoomOut from "@lucide/svelte/icons/zoom-out"
  import { onDestroy, onMount, untrack } from "svelte"
  import { toast } from "svelte-sonner"

  import {
    editAsset,
    fetchEditSource,
    resetAssetEdit,
    type ImageAssetPublic,
  } from "@/lib/api/imaging"
  import { Button } from "@/lib/components/ui/button"
  import { Dialog } from "@/lib/components/ui/dialog"
  import { Input } from "@/lib/components/ui/input"
  import {
    ASPECTS,
    MAX_ZOOM,
    MIN_ZOOM,
    MOVE_STEP,
    ZOOM_SLIDER_MAX,
    applySize,
    areaOf,
    aspectOfRatio,
    aspectRatio,
    clampPan,
    clampZoom,
    displayScale,
    editFromArea,
    frameSize,
    initialEdit,
    isEdited,
    outputSize,
    renderPreview,
    sliderOfZoom,
    turn,
    zoomOfSlider,
    zoomStep,
    type AspectKey,
    type ImageEdit,
    type Size,
  } from "@/lib/imaging/image-edit"

  let {
    asset,
    onClose,
    onApplied,
  }: {
    asset: ImageAssetPublic
    onClose: () => void
    /** Asset à jour après Valider / Réinitialiser. */
    onApplied: (asset: ImageAssetPublic) => void
  } = $props()

  let sourceUrl = $state<string | null>(null)
  let image = $state<HTMLImageElement | null>(null)
  let natural = $state<Size | null>(null)
  let loadFailed = $state(false)
  // Couleur de la marge : le fond de l'image (coin haut-gauche de la base),
  // comme le serveur pour une normalisation ; blanc pour une génération.
  let margin = $state("#FFFFFF")

  let edit = $state<ImageEdit>(initialEdit(null))
  let stage = $state<Size>({ width: 0, height: 0 })
  let restored = false
  let busy = $state<"save" | "reset" | null>(null)
  let previewUrl = $state<string | null>(null)
  let widthText = $state("")
  let heightText = $state("")
  let sizeError = $state<string | null>(null)

  const frame = $derived(
    stage.width > 0 ? frameSize(stage, aspectRatio(edit)) : { width: 0, height: 0 },
  )
  const area = $derived(natural && frame.width > 0 ? areaOf(natural, frame, edit) : null)
  const output = $derived(area ? outputSize(area, edit.size) : natural)
  const edited = $derived(isEdited(edit, natural))
  const scale = $derived(natural && frame.width > 0 ? displayScale(natural, frame, edit) : 0)

  onMount(async () => {
    const url = await fetchEditSource(asset.id)
    if (!url) {
      loadFailed = true
      return
    }
    sourceUrl = url
    const img = new Image()
    img.onload = () => {
      natural = { width: img.naturalWidth, height: img.naturalHeight }
      if (asset.verb === "normalize") margin = cornerColor(img) ?? margin
      image = img
      edit = initialEdit(natural)
    }
    img.onerror = () => (loadFailed = true)
    img.src = url
  })

  onDestroy(() => {
    if (sourceUrl) URL.revokeObjectURL(sourceUrl)
    if (previewUrl) URL.revokeObjectURL(previewUrl)
  })

  function cornerColor(img: HTMLImageElement): string | null {
    const canvas = document.createElement("canvas")
    canvas.width = 1
    canvas.height = 1
    const ctx = canvas.getContext("2d")
    if (!ctx) return null
    ctx.drawImage(img, 0, 0, 1, 1, 0, 0, 1, 1)
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data
    return `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`
  }

  // Réouverture : reconstitue l'état affiché depuis l'édition enregistrée,
  // une fois la scène mesurée (le cadre en dépend).
  $effect(() => {
    if (restored || !natural || stage.width === 0) return
    restored = true
    const saved = asset.edit
    if (!saved) return
    untrack(() => {
      const ratio = saved.area.width / saved.area.height
      const aspect = aspectOfRatio(ratio)
      const base = {
        aspect,
        freeRatio: ratio,
        quarter: saved.quarter ?? 0,
        flipH: saved.flip_h ?? false,
        flipV: saved.flip_v ?? false,
        size: saved.size ?? null,
      }
      const box = frameSize(stage, aspect === "libre" ? ratio : aspectRatio(base))
      edit = editFromArea(natural!, box, base, saved.area)
      showSize(edit.size)
    })
  })

  // Aperçu « Rendu » recalculé un court instant après chaque geste.
  $effect(() => {
    const current = area
    const img = image
    const size = output
    const snapshot = $state.snapshot(edit) as ImageEdit
    const bg = margin
    if (!current || !img || !size) return
    let alive = true
    const timer = setTimeout(() => {
      renderPreview(img, current, snapshot, size, bg)
        .then((url) => {
          if (!alive) {
            URL.revokeObjectURL(url)
            return
          }
          if (previewUrl) URL.revokeObjectURL(previewUrl)
          previewUrl = url
        })
        .catch(() => {})
    }, 120)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  })

  function patch(next: Partial<ImageEdit>) {
    edit = { ...edit, ...next }
  }

  function showSize(size: Size | null) {
    widthText = size ? String(size.width) : ""
    heightText = size ? String(size.height) : ""
  }

  function setPan(x: number, y: number) {
    if (!natural) return
    patch({ pan: clampPan({ x, y }, natural, frame, edit) })
  }

  function zoomTo(next: number) {
    if (!natural) return
    const zoom = clampZoom(next)
    // Zoom autour du centre du cadre : le point visé reste au centre.
    const k = zoom / edit.zoom
    const nextEdit = { ...edit, zoom, pan: { x: edit.pan.x * k, y: edit.pan.y * k } }
    edit = { ...nextEdit, pan: clampPan(nextEdit.pan, natural, frame, nextEdit) }
  }

  function rotate(direction: 1 | -1) {
    const libre = edit.aspect === "libre"
    const size = libre && edit.size ? { width: edit.size.height, height: edit.size.width } : edit.size
    showSize(size)
    patch({
      quarter: turn(edit.quarter, direction),
      pan: { x: 0, y: 0 },
      freeRatio: libre ? 1 / edit.freeRatio : edit.freeRatio,
      size,
    })
  }

  // Miroir vu à l'écran : gardé dans le repère de l'image (avant rotation).
  function flipScreen(axis: "horizontal" | "vertical") {
    const local = (edit.quarter % 2 === 0) === (axis === "horizontal") ? "flipH" : "flipV"
    patch({ [local]: !edit[local] })
  }

  function screenFlipped(axis: "horizontal" | "vertical") {
    return (edit.quarter % 2 === 0) === (axis === "horizontal") ? edit.flipH : edit.flipV
  }

  function chooseAspect(aspect: AspectKey) {
    sizeError = null
    const size =
      edit.size && aspect !== "libre"
        ? {
            width: edit.size.width,
            height: Math.max(
              1,
              Math.round(edit.size.width / aspectRatio({ aspect, freeRatio: 1 })),
            ),
          }
        : edit.size
    showSize(size)
    patch({ aspect, pan: { x: 0, y: 0 }, size })
  }

  function applyTypedSize() {
    const result = applySize(edit, widthText, heightText)
    if ("error" in result) {
      sizeError = result.error
      return
    }
    sizeError = null
    showSize(result.size)
    patch({ size: result.size, freeRatio: result.freeRatio })
  }

  function resetEditor() {
    sizeError = null
    showSize(null)
    edit = initialEdit(natural)
  }

  // --- Gestes sur la scène ---
  let dragging = $state(false)
  let dragStart = { x: 0, y: 0, panX: 0, panY: 0 }

  function onPointerDown(event: PointerEvent) {
    if (!natural || busy) return
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
    dragging = true
    dragStart = { x: event.clientX, y: event.clientY, panX: edit.pan.x, panY: edit.pan.y }
  }

  function onPointerMove(event: PointerEvent) {
    if (!dragging) return
    setPan(dragStart.panX + event.clientX - dragStart.x, dragStart.panY + event.clientY - dragStart.y)
  }

  function onWheel(event: WheelEvent) {
    if (!natural || busy) return
    event.preventDefault()
    zoomTo(zoomStep(edit.zoom, event.deltaY < 0 ? 1 : -1))
  }

  function onStageKeydown(event: KeyboardEvent) {
    const moves: Record<string, [number, number]> = {
      ArrowUp: [0, -MOVE_STEP / 2],
      ArrowDown: [0, MOVE_STEP / 2],
      ArrowLeft: [-MOVE_STEP / 2, 0],
      ArrowRight: [MOVE_STEP / 2, 0],
    }
    const move = moves[event.key]
    if (!move) return
    event.preventDefault()
    setPan(edit.pan.x + move[0], edit.pan.y + move[1])
  }

  // --- Valider / Réinitialiser (serveur) ---
  async function validate() {
    if (!area || busy) return
    busy = "save"
    const round = (value: number) => Math.round(value * 100) / 100
    const { data, error } = edited
      ? await editAsset(asset.id, {
          area: {
            x: round(area.x),
            y: round(area.y),
            width: round(area.width),
            height: round(area.height),
          },
          quarter: edit.quarter,
          flip_h: edit.flipH,
          flip_v: edit.flipV,
          size: edit.size,
        })
      : await resetAssetEdit(asset.id)
    busy = null
    if (error || !data) {
      toast.error("L'image n'a pas pu être modifiée.")
      return
    }
    onApplied(data)
  }

  async function removeEdit() {
    if (busy) return
    busy = "reset"
    const { data, error } = await resetAssetEdit(asset.id)
    busy = null
    if (error || !data) {
      toast.error("Réinitialisation impossible.")
      return
    }
    onApplied(data)
  }

  // Ordre CSS = ordre du rendu : miroir dans le repère de l'image, puis quart
  // de tour, puis déplacement.
  const imageStyle = $derived(
    natural && scale
      ? `width:${natural.width * scale}px;height:${natural.height * scale}px;` +
          `transform:translate(-50%, -50%) translate(${edit.pan.x}px, ${edit.pan.y}px) ` +
          `rotate(${edit.quarter * 90}deg) scale(${edit.flipH ? -1 : 1}, ${edit.flipV ? -1 : 1})`
      : "",
  )
</script>

<Dialog title="Modifier l'image" wide dismissable={busy === null} {onClose}>
  <div class="grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,18rem)]">
    <div class="flex min-w-0 flex-col gap-4">
      {#if loadFailed}
        <p class="text-destructive text-sm" role="alert">
          L'image n'a pas pu être chargée.
        </p>
      {:else}
        <!-- Scène : cadre fixe, l'image bouge dessous (glisser, molette,
             flèches du clavier une fois la zone sélectionnée). -->
        <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
        <div
          class="relative h-72 touch-none overflow-hidden rounded-md outline-none select-none focus-visible:ring-2 sm:h-80 {dragging
            ? 'cursor-grabbing'
            : 'cursor-grab'}"
          style={`background:${margin}`}
          role="application"
          aria-label="Zone de recadrage — les flèches du clavier déplacent l'image"
          tabindex="0"
          bind:clientWidth={stage.width}
          bind:clientHeight={stage.height}
          onpointerdown={onPointerDown}
          onpointermove={onPointerMove}
          onpointerup={() => (dragging = false)}
          onpointercancel={() => (dragging = false)}
          onwheel={onWheel}
          onkeydown={onStageKeydown}
        >
          {#if sourceUrl && natural}
            <img
              src={sourceUrl}
              alt=""
              draggable="false"
              class="pointer-events-none absolute top-1/2 left-1/2 max-w-none"
              style={imageStyle}
            />
            <!-- Cadre : l'extérieur est assombri, l'intérieur montre le rendu. -->
            <div
              class="pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 border-2 border-white shadow-[0_0_0_9999px_rgba(0,0,0,0.5)]"
              style={`width:${frame.width}px;height:${frame.height}px`}
            >
              <div class="absolute inset-y-0 left-1/3 w-px bg-white/40"></div>
              <div class="absolute inset-y-0 left-2/3 w-px bg-white/40"></div>
              <div class="absolute inset-x-0 top-1/3 h-px bg-white/40"></div>
              <div class="absolute inset-x-0 top-2/3 h-px bg-white/40"></div>
            </div>
          {:else}
            <div class="grid h-full place-items-center">
              <LoaderCircle class="text-primary size-8 animate-spin" aria-hidden="true" />
              <span class="sr-only">Chargement de l'image…</span>
            </div>
          {/if}
        </div>

        <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div class="flex items-center gap-1" role="group" aria-label="Zoom">
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Zoom arrière"
              title="Zoom arrière"
              disabled={!natural || edit.zoom <= MIN_ZOOM}
              onclick={() => zoomTo(zoomStep(edit.zoom, -1))}
            >
              <ZoomOut size={14} />
            </Button>
            <input
              type="range"
              class="accent-primary h-2 w-20"
              min="0"
              max={ZOOM_SLIDER_MAX}
              step="0.2"
              aria-label="Zoom"
              aria-valuetext={`${Math.round(edit.zoom * 100)} %`}
              disabled={!natural}
              value={sliderOfZoom(edit.zoom)}
              oninput={(e) => zoomTo(zoomOfSlider(Number(e.currentTarget.value)))}
            />
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Zoom avant"
              title="Zoom avant"
              disabled={!natural || edit.zoom >= MAX_ZOOM}
              onclick={() => zoomTo(zoomStep(edit.zoom, 1))}
            >
              <ZoomIn size={14} />
            </Button>
            <span class="text-muted-foreground w-11 text-right text-xs tabular-nums" aria-hidden="true">
              {Math.round(edit.zoom * 100)} %
            </span>
          </div>
          <div class="flex gap-1" role="group" aria-label="Déplacement">
            {#each [
              { label: "vers le haut", icon: ArrowUp, dx: 0, dy: -MOVE_STEP },
              { label: "vers le bas", icon: ArrowDown, dx: 0, dy: MOVE_STEP },
              { label: "vers la gauche", icon: ArrowLeft, dx: -MOVE_STEP, dy: 0 },
              { label: "vers la droite", icon: ArrowRight, dx: MOVE_STEP, dy: 0 },
            ] as move (move.label)}
              <Button
                variant="outline"
                size="icon-sm"
                aria-label={`Déplacer l'image ${move.label}`}
                title={`Déplacer l'image ${move.label}`}
                disabled={!natural}
                onclick={() => setPan(edit.pan.x + move.dx, edit.pan.y + move.dy)}
              >
                <move.icon size={14} />
              </Button>
            {/each}
          </div>
          <div class="flex gap-1" role="group" aria-label="Miroir">
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Miroir horizontal"
              title="Miroir horizontal"
              aria-pressed={screenFlipped("horizontal")}
              class={screenFlipped("horizontal") ? "bg-primary/10 text-primary" : ""}
              disabled={!natural}
              onclick={() => flipScreen("horizontal")}
            >
              <FlipVertical2 size={14} />
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Miroir vertical"
              title="Miroir vertical"
              aria-pressed={screenFlipped("vertical")}
              class={screenFlipped("vertical") ? "bg-primary/10 text-primary" : ""}
              disabled={!natural}
              onclick={() => flipScreen("vertical")}
            >
              <FlipHorizontal2 size={14} />
            </Button>
          </div>
          <div class="flex gap-1" role="group" aria-label="Rotation">
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Tourner de 90° vers la gauche"
              title="Tourner de 90° vers la gauche"
              disabled={!natural}
              onclick={() => rotate(-1)}
            >
              <RotateCcw size={14} />
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Tourner de 90° vers la droite"
              title="Tourner de 90° vers la droite"
              disabled={!natural}
              onclick={() => rotate(1)}
            >
              <RotateCw size={14} />
            </Button>
          </div>
        </div>

        <div class="flex flex-col gap-2">
          <div class="flex items-center justify-between gap-4">
            <span class="text-xs font-medium" aria-hidden="true">Format</span>
            <button
              type="button"
              class="text-primary text-xs hover:underline disabled:opacity-50"
              disabled={!natural}
              onclick={resetEditor}
            >
              Réinitialiser
            </button>
          </div>
          <div class="bg-muted inline-flex max-w-full self-start overflow-x-auto rounded-md p-0.5" role="radiogroup" aria-label="Format">
            {#each ASPECTS as aspect (aspect.value)}
              <button
                type="button"
                role="radio"
                aria-checked={edit.aspect === aspect.value}
                class="rounded px-3 py-1 text-xs transition-colors {edit.aspect === aspect.value
                  ? 'bg-card text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'}"
                disabled={!natural}
                onclick={() => chooseAspect(aspect.value)}
              >
                {aspect.label}
              </button>
            {/each}
          </div>
        </div>

        <fieldset class="flex flex-col gap-2" disabled={!natural}>
          <legend class="pb-2 text-xs font-medium">Taille de l'image</legend>
          <div class="flex flex-wrap items-start gap-2">
            {#each [
              { key: "largeur", short: "L", label: "Largeur", hint: output?.width },
              { key: "hauteur", short: "H", label: "Hauteur", hint: output?.height },
            ] as field (field.key)}
              <label class="relative w-28">
                <span class="sr-only">{field.label} en pixels</span>
                <span class="text-muted-foreground pointer-events-none absolute top-2 left-2.5 text-xs" aria-hidden="true">
                  {field.short}
                </span>
                {#if field.key === "largeur"}
                  <Input
                    class="h-8 pr-8 pl-7 text-xs tabular-nums"
                    inputmode="numeric"
                    placeholder={field.hint ? String(field.hint) : ""}
                    bind:value={widthText}
                    onkeydown={(e) => e.key === "Enter" && (e.preventDefault(), applyTypedSize())}
                  />
                {:else}
                  <Input
                    class="h-8 pr-8 pl-7 text-xs tabular-nums"
                    inputmode="numeric"
                    placeholder={field.hint ? String(field.hint) : ""}
                    bind:value={heightText}
                    onkeydown={(e) => e.key === "Enter" && (e.preventDefault(), applyTypedSize())}
                  />
                {/if}
                <span class="text-muted-foreground pointer-events-none absolute top-2 right-2.5 text-xs" aria-hidden="true">
                  px
                </span>
              </label>
            {/each}
            <Button variant="outline" size="sm" class="h-8" onclick={applyTypedSize}>
              Appliquer
            </Button>
          </div>
          {#if sizeError}
            <span class="text-destructive text-xs" role="alert">{sizeError}</span>
          {/if}
        </fieldset>
      {/if}
    </div>

    <div class="flex min-w-0 flex-col gap-3">
      <figure class="flex flex-col gap-2">
        <figcaption class="flex items-center justify-between gap-2">
          <span class="text-xs font-medium">Rendu</span>
          {#if output}
            <span class="text-muted-foreground text-xs tabular-nums">
              {output.width} × {output.height} px
            </span>
          {/if}
        </figcaption>
        <div class="bg-muted grid aspect-square place-items-center overflow-hidden rounded-md border">
          {#if previewUrl || sourceUrl}
            <img
              src={previewUrl ?? sourceUrl}
              alt="Rendu après modification"
              class="size-full object-contain {busy ? 'opacity-40' : ''}"
            />
          {/if}
        </div>
      </figure>
      {#if asset.finalized}
        <p class="text-muted-foreground text-xs">
          La finalisation IA est conservée : le recadrage s'applique à l'image
          finalisée.
        </p>
      {/if}
      {#if asset.edit}
        <button
          type="button"
          class="text-muted-foreground hover:text-foreground self-start text-xs underline-offset-2 hover:underline disabled:opacity-50"
          disabled={busy !== null}
          onclick={removeEdit}
        >
          {busy === "reset" ? "Restauration…" : "Revenir à l'image sans modification"}
        </button>
      {/if}
    </div>
  </div>

  <div class="flex justify-end gap-2">
    <Button variant="outline" size="sm" disabled={busy !== null} onclick={onClose}>
      Annuler
    </Button>
    <Button
      size="sm"
      disabled={busy !== null || !area || (!edited && !asset.edit)}
      onclick={validate}
    >
      {busy === "save" ? "Application…" : "Valider les modifications"}
    </Button>
  </div>
</Dialog>
