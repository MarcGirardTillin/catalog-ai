// Appels bruts vers les produits (on réutilise l'instance axios configurée du
// client généré, même pattern que src/lib/api/imports.ts).
import { client } from "@/client/client.gen"
import type { Product, ProductImagesUploadResult } from "@/client"

// Le client généré porte désormais tous les champs produit (prix, variantes
// couleur/taille/prix d'achat, composition, tags, pays, saison, rayon…).
export type ProductDetail = Product

export function getProduct(id: number) {
  return client.get<{ 200: ProductDetail }, unknown>({
    responseType: "json",
    url: `/products/${id}`,
  })
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
