// Marques (sites web de référence) : adaptateur fin au-dessus du client
// OpenAPI généré — types et appels viennent de src/client.
import { brandsListBrands, brandsUpdateBrandWebsiteUrls } from "@/client"
import type { BrandPublic as GenBrandPublic } from "@/client"

// `website_urls` a un default serveur : toujours émis (raffinement requis).
export type BrandPublic = GenBrandPublic & { website_urls: string[] }

export function listBrands() {
  return brandsListBrands() as Promise<{
    data?: BrandPublic[]
    error?: unknown
  }>
}

export function updateBrandWebsiteUrls(id: number, websiteUrls: string[]) {
  return brandsUpdateBrandWebsiteUrls({
    path: { brand_id: id },
    body: { website_urls: websiteUrls },
  }) as Promise<{ data?: BrandPublic; error?: unknown }>
}
