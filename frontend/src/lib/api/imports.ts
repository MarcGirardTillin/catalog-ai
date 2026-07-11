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

// Cumuls sur toutes les variantes extraites (quantité absente = 1 unité ;
// montants = quantité × prix unitaire, en chaînes décimales JSON).
export type ImportJobTotals = {
  quantity: number
  wholesale_amount: string | null
  retail_amount: string | null
}

export type ImportJobPublic = {
  id: number
  status: ImportJobStatus
  // Nom du 1er fichier (compat) ; `file_names` liste tous les fichiers du lot.
  file_name: string
  file_names: string[]
  counts: ImportJobCounts
  totals: ImportJobTotals
  // Infos lues sur le document lui-même (bons de commande surtout).
  po_number: string | null
  supplier: string | null
  warnings: string[]
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  duration_seconds: number | null
  // Profil d'import associé au job (règles d'export Tillin), null si aucun.
  profile_id: number | null
  // Magasin (location Tillin) de destination du job, null si non choisi.
  location_id: number | null
}

// --- Profils d'import (règles de transformation vers le CSV Tillin) ---

// Les décimaux (coefficient, arrondi, TVA) voyagent en chaînes JSON.
export type ImportProfileConfig = {
  price_mode: "retail_as_is" | "coefficient"
  coefficient: string | null
  round_up_to: string
  barcode_mode: "ean" | "constructed"
  brand_mode: "as_extracted" | "fixed"
  brand_value: string
  supplier_label: string
  season_label: string
  tax_rate: string
  status: string
}

export type ImportProfilePublic = {
  id: number
  name: string
  supplier_match: string
  config: ImportProfileConfig
  created_at: string
  updated_at: string
}

export type ImportProfileCreate = {
  name: string
  supplier_match: string
  config: ImportProfileConfig
}

// Aperçu des lignes du CSV Tillin généré pour un job + profil.
export type ImportRowsPreview = {
  columns: string[]
  rows: string[][]
  warnings: string[]
  row_count: number
}

export type LocationPublic = {
  id: number
  title: string
}

export type TransferResult = {
  ok: boolean
  row_count: number
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

export type ImportFilePreviewSheet = {
  sheet: string | null
  rows: string[][]
  total_rows: number
  truncated: boolean
}

export type ImportFilePreview = {
  kind: "pdf" | "tabular"
  file_name: string
  sheets: ImportFilePreviewSheet[]
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

/** Upload multipart : plusieurs fichiers d'un même bon de commande sous le
 * champ répété `files`, plus le magasin et le profil choisis au dépôt.
 * Axios sérialise le FormData et pose le boundary lui-même. */
export function createImport(
  files: File[],
  locationId?: number,
  profileId?: number,
) {
  const body = new FormData()
  for (const file of files) body.append("files", file, file.name)
  if (locationId != null) body.append("location_id", String(locationId))
  if (profileId != null) body.append("profile_id", String(profileId))
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

/** Fichier source original, en blob (l'auth passe par les cookies axios).
 * `index` cible un fichier précis du lot (0 par défaut). */
export function getImportFile(id: number, index = 0) {
  return client.get<{ 200: Blob }, unknown>({
    responseType: "blob",
    url: `/imports/${id}/file`,
    query: index ? { index } : undefined,
  })
}

/** Premières lignes parsées d'un fichier tabulaire (xlsx/csv) du lot. */
export function previewImportFile(id: number, index = 0) {
  return client.get<{ 200: ImportFilePreview }, unknown>({
    responseType: "json",
    url: `/imports/${id}/file/preview`,
    query: index ? { index } : undefined,
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

// --- CRUD des profils d'import ---

export function listImportProfiles() {
  return client.get<{ 200: ImportProfilePublic[] }, unknown>({
    responseType: "json",
    url: "/import-profiles",
  })
}

export function createImportProfile(body: ImportProfileCreate) {
  return client.post<{ 201: ImportProfilePublic }, unknown>({
    responseType: "json",
    url: "/import-profiles",
    body,
    headers: { "Content-Type": "application/json" },
  })
}

export function updateImportProfile(id: number, body: Partial<ImportProfileCreate>) {
  return client.patch<{ 200: ImportProfilePublic }, unknown>({
    responseType: "json",
    url: `/import-profiles/${id}`,
    body,
    headers: { "Content-Type": "application/json" },
  })
}

export function deleteImportProfile(id: number) {
  return client.delete<{ 204: unknown }, unknown>({
    url: `/import-profiles/${id}`,
  })
}

// --- Review des items (édition du payload, exclusion/réintégration) ---

export function patchImportItem(
  jobId: number,
  itemId: number,
  body: { payload?: ImportedProduct; status?: "ready_for_review" | "rejected" },
) {
  return client.patch<{ 200: ImportItemPublic }, unknown>({
    responseType: "json",
    url: `/imports/${jobId}/items/${itemId}`,
    body,
    headers: { "Content-Type": "application/json" },
  })
}

/** Associe (ou détache avec null) un profil d'import au job. */
export function setImportProfile(id: number, profileId: number | null) {
  return client.put<{ 200: ImportJobPublic }, unknown>({
    responseType: "json",
    url: `/imports/${id}/profile`,
    body: { profile_id: profileId },
    headers: { "Content-Type": "application/json" },
  })
}

/** Associe (ou détache avec null) le magasin de destination du job. */
export function setImportLocation(id: number, locationId: number | null) {
  return client.put<{ 200: ImportJobPublic }, unknown>({
    responseType: "json",
    url: `/imports/${id}/location`,
    body: { location_id: locationId },
    headers: { "Content-Type": "application/json" },
  })
}

// --- Export Tillin (aperçu, CSV, transfert) ---

export function getImportRows(id: number, profileId?: number) {
  return client.get<{ 200: ImportRowsPreview }, unknown>({
    responseType: "json",
    url: `/imports/${id}/rows`,
    query: profileId != null ? { profile_id: profileId } : undefined,
  })
}

/** CSV Tillin généré, en blob (l'auth passe par les cookies axios). */
export function getImportCsv(id: number, profileId?: number) {
  return client.get<{ 200: Blob }, unknown>({
    responseType: "blob",
    url: `/imports/${id}/csv`,
    query: profileId != null ? { profile_id: profileId } : undefined,
  })
}

export function listLocations() {
  return client.get<{ 200: LocationPublic[] }, unknown>({
    responseType: "json",
    url: "/locations",
  })
}

/** Transfert vers Tillin. `location_id` absent → le backend utilise la
 * location du job (400 `location_required` s'il n'y en a pas). */
export function transferImport(
  id: number,
  body: { location_id?: number; profile_id?: number },
) {
  return client.post<{ 200: TransferResult }, unknown>({
    responseType: "json",
    url: `/imports/${id}/transfer`,
    body,
    headers: { "Content-Type": "application/json" },
  })
}

// --- Pont import → produits Tillin (liaison et lecture des produits créés) ---

export type LinkProductsResult = {
  linked: number
  already_linked: number
  not_found: string[]
}

export type ImportProductItem = {
  item_id: number
  status: string
  supplier_ref: string
  title: string | null
  brand: string | null
  image_url: string | null
  variant_count: number
  // Id du produit Tillin créé par le transfert, null tant que non relié.
  tillin_product_id: number | null
}

export type ImportProductsResponse = {
  import_id: number
  file_name: string
  items: ImportProductItem[]
  linked_count: number
  unlinked_count: number
}

/** Relie les items transférés aux produits Tillin (résolution par référence).
 * 400 `{code:"not_transferred"}` si l'import n'a pas encore été transféré. */
export function linkImportProducts(id: number) {
  return client.post<{ 200: LinkProductsResult }, unknown>({
    responseType: "json",
    url: `/imports/${id}/link-products`,
  })
}

/** Produits de l'import avec leur liaison Tillin (onglet « Par import »). */
export function getImportProducts(id: number) {
  return client.get<{ 200: ImportProductsResponse }, unknown>({
    responseType: "json",
    url: `/imports/${id}/products`,
  })
}
