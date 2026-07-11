// Produits : adaptateur fin au-dessus du client OpenAPI généré. Seul
// l'upload multipart reste un appel brut (FormData avec champ répété).
import { productsReadProduct } from "@/client"
import { client } from "@/client/client.gen"
import type { Product, ProductImagesUploadResult } from "@/client"

// Le client généré porte tous les champs produit (prix, variantes
// couleur/taille/prix d'achat, composition, tags, pays, saison, rayon…).
export type ProductDetail = Product

export function getProduct(id: number) {
  return productsReadProduct({ path: { product_id: id } })
}

/** Upload multipart : chaque fichier part sous le champ répété `files`. */
export function uploadProductImages(id: number, files: File[]) {
  const body = new FormData()
  for (const file of files) body.append("files", file, file.name)
  return client.post<{ 200: ProductImagesUploadResult }, unknown>({
    responseType: "json",
    url: `/products/${id}/images`,
    body,
  })
}
