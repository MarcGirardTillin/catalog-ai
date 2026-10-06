<script lang="ts">
  // Onglet « Cadrage » sous l'aperçu (modèle : éditeur de la fiche produit
  // Tillin) : le cadre reste fixe et l'image se déplace (glisser, flèches) et
  // se zoome (molette, curseur, boutons) dessous ; poignées dans les angles
  // (et sur les côtés en format Libre) pour redimensionner le cadre, qui se
  // recale ensuite au maximum en zoomant l'image (comportement iPhone).
  // Chaque geste est appliqué peu après sur le serveur (édition locale et
  // gratuite de la sortie courante — une finalisation IA est conservée).
  import FlipHorizontal2 from "@lucide/svelte/icons/flip-horizontal-2"
  import FlipVertical2 from "@lucide/svelte/icons/flip-vertical-2"
  import LoaderCircle from "@lucide/svelte/icons/loader-circle"
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw"
  import RotateCw from "@lucide/svelte/icons/rotate-cw"
  import Undo2 from "@lucide/svelte/icons/undo-2"
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
  import { Input } from "@/lib/components/ui/input"
  import {
    ASPECTS,
    MAX_ZOOM,
    MIN_ZOOM,
    MOVE_STEP,
    ZOOM_SLIDER_MAX,
    applySize,
    areaOfRect,
    aspectOfRatio,
    aspectRatio,
    centeredRect,
    clampPan,
    clampZoom,
    displayScale,
    editFromArea,
    frameSize,
    initialEdit,
    isEdited,
    outputSize,
    resizeRect,
    sliderOfZoom,
    turn,
    zoomOfSlider,
    zoomStep,
    type AspectKey,
    type Handle,
    type ImageEdit,
    type Rect,
    type Size,
  } from "@/lib/imaging/image-edit"

  let {
    asset,
    onApplied,
  }: {
    asset: ImageAssetPublic
    /** Asset à jour après chaque application (le parent rafraîchit l'aperçu). */
    onApplied: (asset: ImageAssetPublic) => void
  } = $props()

  let sourceUrl = $state<string | null>(null)
  let natural = $state<Size | null>(null)
  let loadFailed = $state(false)
  // Couleur de la marge : le fond de l'image (coin haut-gauche de la base),
  // comme le serveur pour une normalisation ; blanc pour une génération.
  let margin = $state("#FFFFFF")

  let edit = $state<ImageEdit>(initialEdit(null))
  let stage = $state<Size>({ width: 0, height: 0 })
  let restored = false
  let widthText = $state("")
  let heightText = $state("")
  let sizeError = $state<string | null>(null)
  // Recalage animé du cadre après une poignée (comportement iPhone).
  let animating = $state(false)

  const frame = $derived(
    stage.width > 0 ? frameSize(stage, aspectRatio(edit)) : { width: 0, height: 0 },
  )
  // Pendant qu'on tire une poignée, le cadre affiché quitte le cadre maximal.
  let liveRect = $state<Rect | null>(null)
  const rect = $derived(liveRect ?? centeredRect(stage, frame))
  const scale = $derived(
    natural && frame.width > 0 ? displayScale(natural, frame, edit) : 0,
  )
  const area = $derived(
    natural && frame.width > 0 ? areaOfRect(natural, stage, frame, rect, edit) : null,
  )
  const output = $derived(area ? outputSize(area, edit.size) : natural)
  const edited = $derived(isEdited(edit, natural))

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
      edit = initialEdit(natural)
    }
    img.onerror = () => (loadFailed = true)
    img.src = url
  })

  onDestroy(() => {
    clearTimeout(applyTimer)
    if (sourceUrl) URL.revokeObjectURL(sourceUrl)
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
      edit = editFromArea(natural!, frameSize(stage, aspectRatio(base)), base, saved.area)
      showSize(edit.size)
    })
  })

  // --- Application sur le serveur : débouncée, séquencée (une à la fois) ---
  let applyTimer: ReturnType<typeof setTimeout> | undefined
  let applying = $state(false)
  let applyQueued = false
  let appliedOnce = $state(false)

  function scheduleApply(delayMs = 500) {
    clearTimeout(applyTimer)
    applyTimer = setTimeout(() => void runApply(), delayMs)
  }

  async function runApply() {
    if (!area || !natural) return
    if (applying) {
      applyQueued = true
      return
    }
    if (!edited && !asset.edit) return
    applying = true
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
    applying = false
    if (error || !data) {
      toast.error("Le cadrage n'a pas pu être appliqué.")
      return
    }
    appliedOnce = true
    onApplied(data)
    if (applyQueued) {
      applyQueued = false
      scheduleApply(50)
    }
  }

  function patch(next: Partial<ImageEdit>, apply = true) {
    edit = { ...edit, ...next }
    if (apply) scheduleApply()
  }

  function showSize(size: Size | null) {
    widthText = size ? String(size.width) : ""
    heightText = size ? String(size.height) : ""
  }

  function setPan(x: number, y: number, apply = true) {
    if (!natural) return
    patch({ pan: clampPan({ x, y }, natural, frame, edit) }, apply)
  }

  function zoomTo(next: number) {
    if (!natural) return
    const zoom = clampZoom(next)
    // Zoom autour du centre du cadre : le point visé reste au centre.
    const k = zoom / edit.zoom
    const nextEdit = { ...edit, zoom, pan: { x: edit.pan.x * k, y: edit.pan.y * k } }
    edit = { ...nextEdit, pan: clampPan(nextEdit.pan, natural, frame, nextEdit) }
    scheduleApply()
  }

  function rotate(direction: 1 | -1) {
    const libre = edit.aspect === "libre"
    const size =
      libre && edit.size ? { width: edit.size.height, height: edit.size.width } : edit.size
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
    scheduleApply(0)
  }

  // --- Glisser l'image sous le cadre ---
  let dragging = $state(false)
  let dragStart = { x: 0, y: 0, panX: 0, panY: 0 }

  function onPointerDown(event: PointerEvent) {
    if (!natural) return
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
    dragging = true
    dragStart = { x: event.clientX, y: event.clientY, panX: edit.pan.x, panY: edit.pan.y }
  }

  function onPointerMove(event: PointerEvent) {
    if (!dragging) return
    setPan(
      dragStart.panX + event.clientX - dragStart.x,
      dragStart.panY + event.clientY - dragStart.y,
      false,
    )
  }

  function onPointerUp() {
    if (!dragging) return
    dragging = false
    scheduleApply()
  }

  function onWheel(event: WheelEvent) {
    if (!natural) return
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

  // --- Poignées : redimensionner le cadre puis le recaler (iPhone) ---
  const CORNERS: Handle[] = ["nw", "ne", "sw", "se"]
  const SIDES: Handle[] = ["n", "s", "w", "e"]
  const handles = $derived(edit.aspect === "libre" ? [...CORNERS, ...SIDES] : CORNERS)
  const HANDLE_LABELS: Record<Handle, string> = {
    nw: "coin haut gauche",
    ne: "coin haut droit",
    sw: "coin bas gauche",
    se: "coin bas droit",
    n: "bord haut",
    s: "bord bas",
    w: "bord gauche",
    e: "bord droit",
  }
  let resizing: { handle: Handle; x: number; y: number; start: Rect } | null = null

  function handleRatio(): number | null {
    return edit.aspect === "libre" ? null : aspectRatio(edit)
  }

  function onHandleDown(event: PointerEvent, handle: Handle) {
    if (!natural) return
    event.stopPropagation()
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
    resizing = { handle, x: event.clientX, y: event.clientY, start: { ...rect } }
  }

  function onHandleMove(event: PointerEvent) {
    if (!resizing) return
    liveRect = resizeRect(
      resizing.start,
      resizing.handle,
      event.clientX - resizing.x,
      event.clientY - resizing.y,
      stage,
      handleRatio(),
    )
  }

  /** Recale le cadre redimensionné au maximum de la scène en zoomant
   *  l'image d'autant : la zone choisie reste exactement la même. */
  function commitResize() {
    resizing = null
    if (!liveRect || !natural || !area) {
      liveRect = null
      return
    }
    const chosen = area
    const libre = edit.aspect === "libre"
    const ratio = chosen.width / chosen.height
    const base = {
      aspect: edit.aspect,
      freeRatio: libre ? ratio : edit.freeRatio,
      quarter: edit.quarter,
      flipH: edit.flipH,
      flipV: edit.flipV,
      // En libre, une taille imposée ne correspond plus au nouveau rapport.
      size: libre ? null : edit.size,
    }
    if (libre && edit.size) showSize(null)
    animating = true
    edit = editFromArea(natural, frameSize(stage, aspectRatio(base)), base, chosen)
    liveRect = null
    setTimeout(() => (animating = false), 220)
    scheduleApply()
  }

  function onHandleKeydown(event: KeyboardEvent, handle: Handle) {
    const steps: Record<string, [number, number]> = {
      ArrowUp: [0, -MOVE_STEP / 2],
      ArrowDown: [0, MOVE_STEP / 2],
      ArrowLeft: [-MOVE_STEP / 2, 0],
      ArrowRight: [MOVE_STEP / 2, 0],
    }
    const step = steps[event.key]
    if (!step || !natural) return
    event.preventDefault()
    event.stopPropagation()
    liveRect = resizeRect({ ...rect }, handle, step[0], step[1], stage, handleRatio())
    commitResize()
  }

  function handleStyle(handle: Handle): string {
    const left = handle.includes("w") ? rect.x : handle.includes("e") ? rect.x + rect.width : rect.x + rect.width / 2
    const top = handle.includes("n") ? rect.y : handle.includes("s") ? rect.y + rect.height : rect.y + rect.height / 2
    return `left:${left}px;top:${top}px`
  }

  const HANDLE_CURSORS: Record<Handle, string> = {
    nw: "cursor-nwse-resize",
    se: "cursor-nwse-resize",
    ne: "cursor-nesw-resize",
    sw: "cursor-nesw-resize",
    n: "cursor-ns-resize",
    s: "cursor-ns-resize",
    w: "cursor-ew-resize",
    e: "cursor-ew-resize",
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

<div class="flex flex-col gap-3">
  {#if loadFailed}
    <p class="text-destructive text-sm" role="alert">L'image n'a pas pu être chargée.</p>
  {:else}
    <!-- Scène : cadre fixe, l'image bouge dessous. -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
    <div
      class="relative aspect-4/5 w-full touch-none overflow-hidden rounded-md outline-none select-none focus-visible:ring-2 {dragging
        ? 'cursor-grabbing'
        : 'cursor-grab'}"
      style={`background:${margin}`}
      role="application"
      aria-label="Zone de cadrage — les flèches du clavier déplacent l'image"
      tabindex="0"
      bind:clientWidth={stage.width}
      bind:clientHeight={stage.height}
      onpointerdown={onPointerDown}
      onpointermove={onPointerMove}
      onpointerup={onPointerUp}
      onpointercancel={onPointerUp}
      onwheel={onWheel}
      onkeydown={onStageKeydown}
    >
      {#if sourceUrl && natural}
        <img
          src={sourceUrl}
          alt=""
          draggable="false"
          class="pointer-events-none absolute top-1/2 left-1/2 max-w-none {animating
            ? 'transition-all duration-200'
            : ''}"
          style={imageStyle}
        />
        <!-- Cadre : l'extérieur est assombri, l'intérieur montre le rendu. -->
        <div
          class="pointer-events-none absolute border-2 border-white shadow-[0_0_0_9999px_rgba(0,0,0,0.5)] {animating
            ? 'transition-all duration-200'
            : ''}"
          style={`left:${rect.x}px;top:${rect.y}px;width:${rect.width}px;height:${rect.height}px`}
        >
          <div class="absolute inset-y-0 left-1/3 w-px bg-white/40"></div>
          <div class="absolute inset-y-0 left-2/3 w-px bg-white/40"></div>
          <div class="absolute inset-x-0 top-1/3 h-px bg-white/40"></div>
          <div class="absolute inset-x-0 top-2/3 h-px bg-white/40"></div>
        </div>
        {#if !animating}
          {#each handles as handle (handle)}
            <button
              type="button"
              class="border-primary absolute z-10 size-3.5 -translate-x-1/2 -translate-y-1/2 touch-none rounded-[3px] border-2 bg-white shadow focus-visible:ring-2 focus-visible:outline-none {HANDLE_CURSORS[
                handle
              ]}"
              style={handleStyle(handle)}
              aria-label={`Redimensionner le cadre — ${HANDLE_LABELS[handle]} (flèches du clavier)`}
              onpointerdown={(e) => onHandleDown(e, handle)}
              onpointermove={onHandleMove}
              onpointerup={commitResize}
              onpointercancel={commitResize}
              onkeydown={(e) => onHandleKeydown(e, handle)}
            ></button>
          {/each}
        {/if}
        {#if applying}
          <span class="bg-card/80 absolute right-1.5 bottom-1.5 z-10 rounded-full px-2 py-0.5 text-[10px]">
            Application…
          </span>
        {/if}
      {:else}
        <div class="grid h-full place-items-center">
          <LoaderCircle class="text-primary size-8 animate-spin" aria-hidden="true" />
          <span class="sr-only">Chargement de l'image…</span>
        </div>
      {/if}
    </div>

    <!-- Zoom, rotation, miroir : centrés sous l'image, comme l'onglet Produit. -->
    <div class="flex flex-wrap items-center justify-center gap-x-3 gap-y-2">
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
          class="accent-primary h-2 w-24 sm:w-28"
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
      <div class="flex gap-1" role="group" aria-label="Rotation et miroir">
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
    </div>

    <!-- Format + taille de sortie + réinitialisation du cadrage. -->
    <div class="flex flex-wrap items-center justify-center gap-2">
      <div class="bg-muted inline-flex max-w-full overflow-x-auto rounded-md p-0.5" role="radiogroup" aria-label="Format">
        {#each ASPECTS as aspect (aspect.value)}
          <button
            type="button"
            role="radio"
            aria-checked={edit.aspect === aspect.value}
            class="rounded px-2.5 py-1 text-xs transition-colors {edit.aspect === aspect.value
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'}"
            disabled={!natural}
            onclick={() => chooseAspect(aspect.value)}
          >
            {aspect.label}
          </button>
        {/each}
      </div>
      <fieldset class="flex items-center gap-1" disabled={!natural}>
        <legend class="sr-only">Taille de l'image en pixels</legend>
        <label class="relative w-20">
          <span class="sr-only">Largeur en pixels</span>
          <span class="text-muted-foreground pointer-events-none absolute top-1.5 left-2 text-[11px]" aria-hidden="true">L</span>
          <Input
            class="h-7 pr-1 pl-5 text-xs tabular-nums"
            inputmode="numeric"
            placeholder={output ? String(output.width) : ""}
            bind:value={widthText}
            onkeydown={(e) => e.key === "Enter" && (e.preventDefault(), applyTypedSize())}
          />
        </label>
        <label class="relative w-20">
          <span class="sr-only">Hauteur en pixels</span>
          <span class="text-muted-foreground pointer-events-none absolute top-1.5 left-2 text-[11px]" aria-hidden="true">H</span>
          <Input
            class="h-7 pr-1 pl-5 text-xs tabular-nums"
            inputmode="numeric"
            placeholder={output ? String(output.height) : ""}
            bind:value={heightText}
            onkeydown={(e) => e.key === "Enter" && (e.preventDefault(), applyTypedSize())}
          />
        </label>
        <Button variant="outline" size="sm" class="h-7 px-2 text-xs" onclick={applyTypedSize}>
          px
        </Button>
      </fieldset>
      <!-- Toujours rendu (invisible sans cadrage) : la ligne reste centrée. -->
      <Button
        variant="ghost"
        size="sm"
        class={edited || asset.edit ? undefined : "invisible"}
        aria-hidden={!(edited || asset.edit)}
        tabindex={edited || asset.edit ? undefined : -1}
        onclick={resetEditor}
      >
        <Undo2 size={13} aria-hidden="true" data-icon="inline-start" />
        Réinitialiser
      </Button>
    </div>
    {#if sizeError}
      <p class="text-destructive text-center text-xs" role="alert">{sizeError}</p>
    {/if}
    <p class="text-muted-foreground text-center text-xs">
      {#if output}
        Sortie {output.width} × {output.height} px
      {/if}
      {#if asset.finalized}
        · la finalisation IA est conservée
      {/if}
      {#if appliedOnce && !applying}
        · cadrage appliqué
      {/if}
    </p>
  {/if}
</div>
