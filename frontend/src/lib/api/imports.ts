// Appels typés vers les imports de fichiers fournisseurs.
//
// Ces endpoints sont plus récents que le client généré (src/client) : on
// réutilise son instance axios configurée (baseURL + cookies) via `client`
// et on appelle les chemins bruts. À remplacer par les fonctions générées
// après régénération OpenAPI.
import { client } from "@/client/client.gen"

export type ImportJobStatus = "pending" | "processing" | "completed" | "failed"

export type ImportJobCounts = {
  total: number
  ready_for_review: number
  failed: number
}

export type ImportJobPublic = {
  id: number
  status: ImportJobStatus
  file_name: string
  counts: ImportJobCounts
  warnings: string[]
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  duration_seconds: number | null
}

export type ImportedVariant = {
  ean: string | null
  color: string | null
  size: string | null
  quantity: number | null
  // Les prix arrivent en chaînes décimales JSON (ex. "12.50").
  wholesale_price: string | null
  retail_price: string | null
  supplier_sku: string | null
  confidence: Record<string, number>
}

export type ImportedProduct = {
  supplier_ref: string
  title: string | null
  brand: string | null
  category: string | null
  season: string | null
  gender: string | null
  composition: string | null
  hs_code: string | null
  manufacturing_country: string | null
  image_urls: string[]
  variants: ImportedVariant[]
  confidence: Record<string, number>
}

export type ImportItemPublic = {
  id: number
  status: string
  payload: ImportedProduct
  warnings: string[]
  error: string | null
  created_at: string
}

export type Paginated<T> = {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// Le client généré attend TData sous forme de map { statut: type } et
// renvoie `{ data, error }` (throwOnError = false par défaut).

/** Upload multipart : axios sérialise le FormData et pose le boundary lui-même. */
export function createImport(file: File) {
  const body = new FormData()
  body.append("file", file)
  return client.post<{ 201: ImportJobPublic }, unknown>({
    responseType: "json",
    url: "/imports",
    body,
  })
}

export function listImports(query?: { page?: number; page_size?: number }) {
  return client.get<{ 200: Paginated<ImportJobPublic> }, unknown>({
    responseType: "json",
    url: "/imports",
    query,
  })
}

export function readImport(id: number) {
  return client.get<{ 200: ImportJobPublic }, unknown>({
    responseType: "json",
    url: `/imports/${id}`,
  })
}

export function listImportItems(
  id: number,
  query?: { page?: number; page_size?: number },
) {
  return client.get<{ 200: Paginated<ImportItemPublic> }, unknown>({
    responseType: "json",
    url: `/imports/${id}/items`,
    query,
  })
}
