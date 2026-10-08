// Calculs de l'éditeur d'image du studio, portés de l'éditeur Tillin
// (packages/ui/src/lib/image-edit.ts) : formats, quart de tour, miroir,
// taille de sortie, zone recadrée, poignées du cadre. Fonctions pures : le
// serveur (POST /imaging/assets/{id}/edit) produit la sortie réelle.

export type Point = { x: number; y: number }
export type Size = { width: number; height: number }
/** Zone recadrée en pixels de l'image tournée (débord autorisé = marge). */
export type Area = Size & Point

export type AspectKey = "1:1" | "16:9" | "4:5" | "3:4" | "5:4" | "libre"

export const ASPECTS: { value: AspectKey; label: string }[] = [
  { value: "1:1", label: "1:1" },
  { value: "16:9", label: "16:9" },
  { value: "4:5", label: "4:5" },
  { value: "3:4", label: "3:4" },
  { value: "5:4", label: "5:4" },
  { value: "libre", label: "Libre" },
]

const FIXED: Record<Exclude<AspectKey, "libre">, number> = {
  "1:1": 1,
  "16:9": 16 / 9,
  "4:5": 4 / 5,
  "3:4": 3 / 4,
  "5:4": 5 / 4,
}

/** Plus grand côté accepté en sortie (aligné sur le serveur). */
export const MAX_SIDE = 4000
/** Sous 1, l'image devient plus petite que la zone : marge à la couleur du fond. */
export const MIN_ZOOM = 0.25
export const MAX_ZOOM = 5
/** Pas des boutons et de la molette : 5 % de la taille affichée. */
export const ZOOM_FACTOR = 1.05
/** Pas des flèches de déplacement, en pixels affichés. */
export const MOVE_STEP = 20

export type ImageEdit = {
  aspect: AspectKey
  /** Rapport largeur / hauteur du format « Libre ». */
  freeRatio: number
  /** Décalage du centre de l'image par rapport au centre du cadre (px affichés). */
  pan: Point
  zoom: number
  /** Quarts de tour dans le sens horaire (0 à 3). */
  quarter: number
  flipH: boolean
  flipV: boolean
  /** Taille de sortie appliquée ; null = la résolution de la zone recadrée. */
  size: Size | null
}

/** État de départ : image entière, sans zoom ni rotation, au format de
 * l'image elle-même — celui choisi pour le traitement (4:5, 1:1…) quand il
 * correspond à un format fixe, sinon libre. */
export function initialEdit(natural: Size | null): ImageEdit {
  const ratio = natural && natural.height > 0 ? natural.width / natural.height : 1
  return {
    aspect: natural ? aspectOfRatio(ratio) : "libre",
    freeRatio: ratio,
    pan: { x: 0, y: 0 },
    zoom: 1,
    quarter: 0,
    flipH: false,
    flipV: false,
    size: null,
  }
}

export function aspectRatio(edit: Pick<ImageEdit, "aspect" | "freeRatio">): number {
  return edit.aspect === "libre" ? edit.freeRatio : FIXED[edit.aspect]
}

export const turn = (quarter: number, direction: 1 | -1) =>
  (((quarter + direction) % 4) + 4) % 4

/** Taille de l'image une fois tournée (quart de tour impair = côtés échangés). */
export function rotatedSize(natural: Size, quarter: number): Size {
  return quarter % 2
    ? { width: natural.height, height: natural.width }
    : { width: natural.width, height: natural.height }
}

/** Plus grand cadre au rapport voulu qui tient dans la scène (marge de 8 %). */
export function frameSize(stage: Size, ratio: number): Size {
  const maxW = stage.width * 0.92
  const maxH = stage.height * 0.92
  const width = Math.min(maxW, maxH * ratio)
  return { width, height: width / ratio }
}

/** Échelle d'affichage (px affichés par px image) : à zoom 1, l'image tournée
 *  couvre exactement le cadre. */
export function displayScale(natural: Size, frame: Size, edit: ImageEdit): number {
  const box = rotatedSize(natural, edit.quarter)
  return Math.max(frame.width / box.width, frame.height / box.height) * edit.zoom
}

/** Rectangle dans le repère de la scène (px affichés, origine en haut à gauche). */
export type Rect = Point & Size

/** Cadre maximal centré dans la scène. */
export function centeredRect(stage: Size, frame: Size): Rect {
  return {
    x: (stage.width - frame.width) / 2,
    y: (stage.height - frame.height) / 2,
    width: frame.width,
    height: frame.height,
  }
}

/** Zone (px de l'image tournée) sous un cadre quelconque de la scène, l'image
 *  restant à l'échelle du cadre maximal `frame` (elle ne bouge pas pendant
 *  qu'on tire une poignée). */
export function areaOfRect(
  natural: Size,
  stage: Size,
  frame: Size,
  rect: Rect,
  edit: ImageEdit,
): Area {
  const box = rotatedSize(natural, edit.quarter)
  const s = displayScale(natural, frame, edit)
  return {
    x: box.width / 2 + (rect.x - (stage.width / 2 + edit.pan.x)) / s,
    y: box.height / 2 + (rect.y - (stage.height / 2 + edit.pan.y)) / s,
    width: rect.width / s,
    height: rect.height / s,
  }
}

export type Handle = "nw" | "ne" | "sw" | "se" | "n" | "s" | "w" | "e"

/** Plus petit côté du cadre pendant un redimensionnement (px affichés). */
export const MIN_FRAME_SIDE = 40

/**
 * Cadre redimensionné en tirant une poignée de `dx`/`dy` px : le coin (ou le
 * côté) opposé reste fixe, le cadre reste dans la scène. `ratio` impose les
 * proportions (format fixe) ; null = libre. Les poignées de côté ne changent
 * qu'une dimension (format libre seulement).
 */
export function resizeRect(
  start: Rect,
  handle: Handle,
  dx: number,
  dy: number,
  stage: Size,
  ratio: number | null,
): Rect {
  const west = handle.includes("w")
  const north = handle.includes("n")
  const horizontal = handle !== "n" && handle !== "s"
  const vertical = handle !== "w" && handle !== "e"
  // Point fixe (coin ou côté opposé) et place disponible vers la poignée.
  const anchorX = west ? start.x + start.width : start.x
  const anchorY = north ? start.y + start.height : start.y
  const roomW = west ? anchorX : stage.width - anchorX
  const roomH = north ? anchorY : stage.height - anchorY
  let width = horizontal ? start.width + (west ? -dx : dx) : start.width
  let height = vertical ? start.height + (north ? -dy : dy) : start.height
  if (ratio !== null) {
    // La dimension qui a le plus bougé (relativement) entraîne l'autre.
    if (Math.abs(width - start.width) >= Math.abs(height - start.height) * ratio) {
      height = width / ratio
    } else {
      width = height * ratio
    }
    const fit = Math.min(1, roomW / width, roomH / height)
    width *= fit
    height *= fit
    const grow = Math.max(1, MIN_FRAME_SIDE / width, MIN_FRAME_SIDE / height)
    width *= grow
    height *= grow
  } else {
    width = Math.min(roomW, Math.max(MIN_FRAME_SIDE, width))
    height = Math.min(roomH, Math.max(MIN_FRAME_SIDE, height))
  }
  // Une poignée de côté garde le cadre centré sur l'autre axe.
  const x = horizontal ? (west ? anchorX - width : anchorX) : start.x
  const y = vertical ? (north ? anchorY - height : anchorY) : start.y
  return { x, y, width, height }
}

/** Inverse de `areaOf` : rouvre l'éditeur sur une édition déjà appliquée. */
export function editFromArea(
  natural: Size,
  frame: Size,
  base: Omit<ImageEdit, "pan" | "zoom">,
  area: Area,
): ImageEdit {
  const box = rotatedSize(natural, base.quarter)
  const s = frame.width / area.width
  const cover = Math.max(frame.width / box.width, frame.height / box.height)
  return {
    ...base,
    zoom: clampZoom(s / cover),
    pan: {
      x: (box.width / 2 - area.x) * s - frame.width / 2,
      y: (box.height / 2 - area.y) * s - frame.height / 2,
    },
  }
}

/** Déplacement borné : l'image peut sortir du cadre (marge) mais garde au
 *  moins un bord dedans, pour ne pas disparaître. */
export function clampPan(pan: Point, natural: Size, frame: Size, edit: ImageEdit): Point {
  const box = rotatedSize(natural, edit.quarter)
  const s = displayScale(natural, frame, edit)
  const clamp = (value: number, side: number, frameSide: number) => {
    const max = (side * s) / 2 + frameSide / 2
    return Math.min(max, Math.max(-max, value))
  }
  return {
    x: clamp(pan.x, box.width, frame.width),
    y: clamp(pan.y, box.height, frame.height),
  }
}

export const clampZoom = (zoom: number) =>
  Math.round(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom)) * 100) / 100

export const zoomStep = (zoom: number, direction: 1 | -1) =>
  clampZoom(direction > 0 ? zoom * ZOOM_FACTOR : zoom / ZOOM_FACTOR)

/** Curseur de zoom logarithmique : même distance = même facteur. */
export const ZOOM_SLIDER_MAX =
  Math.round((Math.log(MAX_ZOOM / MIN_ZOOM) / Math.log(ZOOM_FACTOR)) * 10) / 10
export const sliderOfZoom = (zoom: number) =>
  Math.log(clampZoom(zoom) / MIN_ZOOM) / Math.log(ZOOM_FACTOR)
export const zoomOfSlider = (position: number) =>
  clampZoom(MIN_ZOOM * ZOOM_FACTOR ** position)

/** Taille produite : la taille appliquée, sinon la zone (bornée à MAX_SIDE). */
export function outputSize(area: Area, size: Size | null): Size {
  const base = size ?? { width: Math.round(area.width), height: Math.round(area.height) }
  const scale = Math.min(1, MAX_SIDE / Math.max(base.width, base.height, 1))
  return {
    width: Math.max(1, Math.round(base.width * scale)),
    height: Math.max(1, Math.round(base.height * scale)),
  }
}

/** Entier de pixels lu dans un champ (« 1 080 », « 1080 px »). */
export function parsePixels(text: string): number | null {
  const digits = text.replace(/[\s  ]|px/gi, "")
  if (!/^\d+$/.test(digits)) return null
  const value = Number(digits)
  return value >= 1 ? value : null
}

/** « Appliquer » la taille saisie : en format fixe un seul côté suffit (l'autre
 *  suit le rapport) ; en libre les deux côtés donnent le nouveau rapport. */
export function applySize(
  edit: Pick<ImageEdit, "aspect" | "freeRatio">,
  widthText: string,
  heightText: string,
): { error: string } | { size: Size; freeRatio: number } {
  const width = parsePixels(widthText)
  const height = parsePixels(heightText)
  const tooBig = `${MAX_SIDE.toLocaleString("fr-FR")} px au plus par côté.`
  if ((width ?? 0) > MAX_SIDE || (height ?? 0) > MAX_SIDE) return { error: tooBig }
  if (edit.aspect === "libre") {
    if (width === null || height === null)
      return { error: "Saisissez la largeur et la hauteur en pixels." }
    return { size: { width, height }, freeRatio: width / height }
  }
  const ratio = aspectRatio(edit)
  if (width !== null) {
    const derived = Math.max(1, Math.round(width / ratio))
    if (derived > MAX_SIDE) return { error: tooBig }
    return { size: { width, height: derived }, freeRatio: edit.freeRatio }
  }
  if (height !== null) {
    const derived = Math.max(1, Math.round(height * ratio))
    if (derived > MAX_SIDE) return { error: tooBig }
    return { size: { width: derived, height }, freeRatio: edit.freeRatio }
  }
  return { error: "Saisissez une largeur ou une hauteur en pixels." }
}

/** Vrai si l'image produite diffère de l'image de départ. */
export function isEdited(edit: ImageEdit, natural: Size | null): boolean {
  const start = initialEdit(natural)
  return (
    edit.aspect !== start.aspect ||
    Math.abs(edit.freeRatio - start.freeRatio) > 1e-6 ||
    Math.abs(edit.zoom - 1) > 1e-6 ||
    Math.abs(edit.pan.x) > 0.5 ||
    Math.abs(edit.pan.y) > 0.5 ||
    edit.quarter !== 0 ||
    edit.flipH ||
    edit.flipV ||
    edit.size !== null
  )
}

/** Format fixe correspondant à un rapport (1 % de tolérance), sinon libre. */
export function aspectOfRatio(ratio: number): AspectKey {
  for (const [key, value] of Object.entries(FIXED)) {
    if (Math.abs(value - ratio) / value < 0.01) return key as AspectKey
  }
  return "libre"
}
