// Traitement d'images (sprint imagerie, Phase A) : verbes à la carte du
// panneau produit. Les appels typés passent par le SDK généré ; seule la
// preview binaire est récupérée en blob (l'auth est un cookie httpOnly, un
// <img src> cross-origin ne le porterait pas de façon fiable).
import {
  type ImageAssetPublic,
  imagingReadAsset,
  imagingSaveAsset,
  productsGenerateModelImage,
  productsNormalizeImage,
} from "@/client"
import { client } from "@/client/client.gen"

export type { ImageAssetPublic }

export function normalizeImage(
  productId: number,
  imageUrl: string,
  productImageId: number | null,
) {
  return productsNormalizeImage({
    path: { product_id: productId },
    body: { image_url: imageUrl, product_image_id: productImageId },
  })
}

export function generateModelImage(
  productId: number,
  imageUrl: string,
  productImageId: number | null,
) {
  return productsGenerateModelImage({
    path: { product_id: productId },
    body: { image_url: imageUrl, product_image_id: productImageId },
  })
}

export function getAsset(assetId: number) {
  return imagingReadAsset({ path: { asset_id: assetId } })
}

export function saveAsset(assetId: number, replace: boolean) {
  return imagingSaveAsset({
    path: { asset_id: assetId },
    body: { replace },
  })
}

/** Normalise (ou rétablit) UNE image stagée d'un item d'enrichissement —
 *  action par image de la review (les originales sont stagées par défaut). */
export function normalizeItemImage(itemId: number, url: string, revert: boolean) {
  return client.post<{ 200: import("@/client").ItemPublic }, unknown>({
    responseType: "json",
    url: `/items/${itemId}/images/normalize`,
    body: { url, revert },
  })
}

/** Récupère les fichiers stagés d'un asset et retourne des object-URLs
 *  (à révoquer par l'appelant via URL.revokeObjectURL). */
export async function fetchAssetPreviews(
  asset: ImageAssetPublic,
): Promise<string[]> {
  const urls: string[] = []
  for (const [index] of (asset.preview_urls ?? []).entries()) {
    const { data } = await client.get<{ 200: Blob }, unknown>({
      responseType: "blob",
      url: `/imaging/assets/${asset.id}/files/${index}`,
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
