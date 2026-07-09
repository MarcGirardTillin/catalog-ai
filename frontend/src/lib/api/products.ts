// Appels bruts vers les produits (client généré non régénéré : on réutilise
// son instance axios configurée, même pattern que src/lib/api/imports.ts).
import { client } from "@/client/client.gen"
import type { Product } from "@/client"

// Le backend expose désormais `price` (prix de vente, chaîne décimale JSON)
// sur le produit et ses variantes ; le type généré ne le connaît pas encore —
// extension locale en attendant la régénération OpenAPI.
export type ProductDetail = Omit<Product, "variants"> & {
  price?: string | null
  variants?: (NonNullable<Product["variants"]>[number] & {
    price?: string | null
  })[]
}

export function getProduct(id: number) {
  return client.get<{ 200: ProductDetail }, unknown>({
    responseType: "json",
    url: `/products/${id}`,
  })
}
