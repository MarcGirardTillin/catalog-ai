// Traitement d'images (sprint imagerie, Phase A) : verbes à la carte du
// panneau produit. Les appels typés passent par le SDK généré ; seule la
// preview binaire est récupérée en blob (l'auth est un cookie httpOnly, un
// <img src> cross-origin ne le porterait pas de façon fiable).
import {
  type CropBox,
  type FinalizeRequest,
  type GenerateFlatOptions,
  type GenerateModelOptions,
  type ImageAssetPublic,
  type NormalizeOptions,
  type RenderRequest,
  type StagedFilePublic,
  imagingDiscardAsset,
  imagingFinalizeAsset,
  imagingListImagingAssets,
  imagingListPendingProducts,
  imagingReadAsset,
  imagingRenderAsset,
  imagingSaveAsset,
  itemsNormalizeItemImageRoute,
  productsGenerateFlatImage,
  productsGenerateGhostImage,
  productsRecolorImage,
  productsSwapModelImage,
  productsGenerateModelImage,
  productsNormalizeImage,
} from "@/client"
import { client } from "@/client/client.gen"

export type {
  CropBox,
  FinalizeRequest,
  GenerateFlatOptions,
  GenerateModelOptions,
  ImageAssetPublic,
  NormalizeOptions,
  RenderRequest,
  StagedFilePublic,
}

export function normalizeImage(
  productId: number,
  imageUrl: string,
  productImageId: number | null,
  options?: NormalizeOptions,
) {
  return productsNormalizeImage({
    path: { product_id: productId },
    body: { image_url: imageUrl, product_image_id: productImageId, options },
  })
}

export function generateModelImage(
  productId: number,
  imageUrl: string,
  productImageId: number | null,
  options?: GenerateModelOptions,
  additionalImageUrls?: string[],
) {
  return productsGenerateModelImage({
    path: { product_id: productId },
    body: {
      image_url: imageUrl,
      product_image_id: productImageId,
      options,
      additional_image_urls: additionalImageUrls,
    },
  })
}

/** Mise à plat stylisée (Photoroom flat lay ou GPT Image) — 202 + polling.
 * `additionalImageUrls` : autres vues du produit (moteur GPT, max 3). */
export function generateFlatImage(
  productId: number,
  imageUrl: string,
  productImageId: number | null,
  options?: GenerateFlatOptions,
  additionalImageUrls?: string[] | null,
) {
  return productsGenerateFlatImage({
    path: { product_id: productId },
    body: {
      image_url: imageUrl,
      product_image_id: productImageId,
      options,
      additional_image_urls: additionalImageUrls ?? null,
    },
  })
}

/** Mannequin invisible (Photoroom ghost mannequin) — 202 + polling. */
export function generateGhostImage(
  productId: number,
  imageUrl: string,
  productImageId: number | null,
  options?: GenerateFlatOptions,
) {
  return productsGenerateGhostImage({
    path: { product_id: productId },
    body: { image_url: imageUrl, product_image_id: productImageId, options },
  })
}

/** « Remplacer le mannequin » (face swap FASHN) : identité changée, tenue
 * conservée. face_id = visage de la bibliothèque du compte (null = identité
 * libre pilotée par le prompt). */
export function swapModelImage(
  productId: number,
  imageUrl: string,
  productImageId: number | null,
  options: {
    face_id: number | null
    face_reference_mode: "match_base" | "match_reference"
    prompt: string | null
  },
) {
  return productsSwapModelImage({
    path: { product_id: productId },
    body: {
      image_url: imageUrl,
      product_image_id: productImageId,
      ...options,
    },
  })
}

/** « Changer la couleur » (FASHN edit) : couleur du picker OU image de
 * référence — au moins l'une des deux ; le débit suit la qualité choisie. */
export function recolorImage(
  productId: number,
  imageUrl: string,
  productImageId: number | null,
  options: {
    color: string | null
    reference_image_url: string | null
    instructions: string | null
    resolution: "1k" | "2k" | "4k"
  },
) {
  return productsRecolorImage({
    path: { product_id: productId },
    body: {
      image_url: imageUrl,
      product_image_id: productImageId,
      ...options,
    },
  })
}

/** Finalisation IA d'une normalisation positionnée (payant, synchrone) :
 *  ombre, décor IA, défroissage, upscale, beautifier, recoloration — un seul
 *  appel Photoroom, un seul débit. Un re-render local ultérieur l'annule. */
export function finalizeAsset(assetId: number, body: FinalizeRequest) {
  return imagingFinalizeAsset({ path: { asset_id: assetId }, body })
}

export function getAsset(assetId: number) {
  return imagingReadAsset({ path: { asset_id: assetId } })
}

/** Listing des assets du compte (réhydratation studio, historique).
 *  `pending` = terminés mais ni enregistrés ni écartés. */
export function listAssets(query: {
  product_id?: number
  verb?: "normalize" | "generate_model" | "generate_flat" | "generate_ghost"
  pending?: boolean
  month?: string
}) {
  return imagingListImagingAssets({ query })
}

/** Ids produits ayant au moins un visuel studio à vérifier (pastille). */
export function listPendingImagingProducts() {
  return imagingListPendingProducts()
}

/** Écarte un résultat non enregistré (purge le staging, garde la trace). */
export function discardAsset(assetId: number) {
  return imagingDiscardAsset({ path: { asset_id: assetId } })
}

export function saveAsset(
  assetId: number,
  replace: boolean,
  filenames?: (string | null)[],
) {
  return imagingSaveAsset({
    path: { asset_id: assetId },
    body: { replace, filenames },
  })
}

/** Recomposition locale (repositionnement / options) — aucun nouvel appel
 *  provider, réponse synchrone avec l'asset à jour (`?r=` sur les previews). */
export function renderAsset(assetId: number, body: RenderRequest) {
  return imagingRenderAsset({ path: { asset_id: assetId }, body })
}

/** Normalise (ou rétablit) UNE image stagée d'un item d'enrichissement —
 *  action par image de la review (les originales sont stagées par défaut). */
export function normalizeItemImage(itemId: number, url: string, revert: boolean) {
  return itemsNormalizeItemImageRoute({
    path: { item_id: itemId },
    body: { url, revert },
  })
}

/** Récupère les fichiers stagés d'un asset et retourne des object-URLs
 *  (à révoquer par l'appelant via URL.revokeObjectURL). */
export async function fetchAssetPreviews(
  asset: ImageAssetPublic,
): Promise<string[]> {
  const urls: string[] = []
  // Les preview_urls portent un `?r={rev}` après re-render : les utiliser
  // telles quelles évite tout cache HTTP périmé.
  for (const previewUrl of asset.preview_urls ?? []) {
    const { data } = await client.get<{ 200: Blob }, unknown>({
      responseType: "blob",
      url: previewUrl,
    })
    if (data instanceof Blob) urls.push(URL.createObjectURL(data))
  }
  return urls
}

/** Attend la fin d'un asset génératif (polling léger). Retourne l'asset
 *  terminal (completed/failed) ou null si le suivi a été interrompu. */
export async function waitForAsset(
  assetId: number,
  options: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<ImageAssetPublic | null> {
  const interval = options.intervalMs ?? 3000
  const deadline = Date.now() + (options.timeoutMs ?? 180_000)
  while (Date.now() < deadline) {
    if (options.signal?.aborted) return null
    const { data } = await getAsset(assetId)
    if (data && data.status !== "pending" && data.status !== "processing") {
      return data
    }
    await new Promise((resolve) => setTimeout(resolve, interval))
  }
  return null
}
