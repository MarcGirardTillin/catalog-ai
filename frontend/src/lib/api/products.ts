// Produits : adaptateur fin au-dessus du client OpenAPI généré. Seul
// l'upload multipart reste un appel brut (FormData avec champ répété).
import {
  productsDeleteProductImage,
  productsReadProduct,
  productsRenameProductImage,
} from "@/client"
import { client } from "@/client/client.gen"
import type { Product, ProductImagesUploadResult } from "@/client"

// Le client généré porte tous les champs produit (prix, variantes
// couleur/taille/prix d'achat, composition, tags, pays, saison, rayon…).
export type ProductDetail = Product

export function getProduct(id: number) {
  return productsReadProduct({ path: { product_id: id } })
}

/** Réordonne la galerie Tillin : la liste ordonnée d'ids devient les
 * positions 1..n. Renvoie le produit relu. */
export function reorderProductImages(id: number, imageIds: number[]) {
  return client.put<{ 200: Product }, unknown>({
    responseType: "json",
    url: `/products/${id}/images/positions`,
    body: { product_image_ids: imageIds },
  })
}

/** « Supprime » une image (désactivation Xano : retirée de la boutique).
 * Renvoie le produit relu. */
export function removeProductImage(id: number, imageId: number) {
  return productsDeleteProductImage({
    path: { product_id: id, image_id: imageId },
  })
}

/** Renomme une image (ré-upload sous le nouveau nom + désactivation de
 * l'ancienne : nouvel id, position conservée). Renvoie le produit relu. */
export function renameProductImage(id: number, imageId: number, name: string) {
  return productsRenameProductImage({
    path: { product_id: id, image_id: imageId },
    body: { name },
  })
}

/** Upload multipart : chaque fichier part sous le champ répété `files`.
 * `applyTemplate` : nommer selon le modèle de nom d'images du compte. */
export function uploadProductImages(
  id: number,
  files: File[],
  applyTemplate = true,
) {
  const body = new FormData()
  for (const file of files) body.append("files", file, file.name)
  body.append("apply_template", applyTemplate ? "true" : "false")
  return client.post<{ 200: ProductImagesUploadResult }, unknown>({
    responseType: "json",
    url: `/products/${id}/images`,
    body,
  })
}
