// Appels typés vers les marques (sites web de référence).
//
// Ces endpoints sont plus récents que le client généré (src/client) : on
// réutilise son instance axios configurée (baseURL + cookies) via `client`
// et on appelle les chemins bruts. À remplacer par les fonctions générées
// après régénération OpenAPI.
import { client } from "@/client/client.gen"

export type BrandPublic = {
  id: number
  name: string | null
  website_urls: string[]
}

// Le client généré attend TData sous forme de map { statut: type } et
// renvoie `{ data, error }` (throwOnError = false par défaut).
export function listBrands() {
  return client.get<{ 200: BrandPublic[] }, unknown>({
    responseType: "json",
    url: "/brands",
  })
}

export function updateBrandWebsiteUrls(id: number, websiteUrls: string[]) {
  return client.put<{ 200: BrandPublic }, unknown>({
    responseType: "json",
    url: `/brands/${id}/website_urls`,
    body: { website_urls: websiteUrls },
    headers: { "Content-Type": "application/json" },
  })
}
