// Imports fournisseurs : adaptateur fin au-dessus du client OpenAPI généré.
//
// Les types viennent TOUS de src/client (zéro redéfinition manuelle, donc
// zéro dérive possible avec le backend). Les seuls raffinements locaux
// rendent OBLIGATOIRES des champs que le serveur émet toujours (pydantic
// default_factory) mais que l'OpenAPI marque optionnels — si le backend
// renomme/supprime un champ, la compilation casse quand même.
//
// Restent en appels bruts (instance axios du client généré) : l'upload
// multipart (champ répété `files`) et les téléchargements binaires (blob).
import {
  importProfilesCreateImportProfile,
  importProfilesDeleteImportProfile,
  importProfilesListImportProfiles,
  importProfilesUpdateImportProfile,
  importsBulkUpdateImportItems,
  importsLinkImportProducts,
  importsListImportItems,
  importsListImportProducts,
  importsListImports,
  importsPreviewImportFile,
  importsPreviewImportRows,
  importsReadImport,
  importsSetImportLocation,
  importsSetImportProfile,
  importsTransferImport,
  importsUpdateImportItem,
  locationsListLocations,
} from "@/client"
import type {
  ImportedProductOutput,
  ImportedVariantOutput,
  ImportFilePreview as GenImportFilePreview,
  ImportFilePreviewSheet as GenImportFilePreviewSheet,
  ImportItemPublic as GenImportItemPublic,
  ImportJobCounts as GenImportJobCounts,
  ImportJobPublic as GenImportJobPublic,
  ImportJobTotals as GenImportJobTotals,
  ImportLinkResult,
  ImportProductLine,
  ImportProducts,
  ImportProfileConfigOutput,
  ImportProfilePublic as GenImportProfilePublic,
  ImportRenderPreview,
  ImportTransferResult,
} from "@/client"
import { client } from "@/client/client.gen"

// --- Types (générés, avec raffinements "toujours émis par le serveur") ---

export type { ImportItemsBulkResult, LocationPublic } from "@/client"

export type ImportJobStatus = "pending" | "processing" | "completed" | "failed"

export type ImportJobCounts = Required<GenImportJobCounts>
export type ImportJobTotals = Required<GenImportJobTotals>

// Alias historiques (noms utilisés par les pages avant la migration),
// rendus obligatoires là où le serveur émet toujours la valeur (defaults).
export type LinkProductsResult = Required<ImportLinkResult>
export type ImportProductItem = Required<ImportProductLine>
export type ImportProductsResponse = Required<ImportProducts> & {
  items: ImportProductItem[]
}
export type ImportRowsPreview = Required<ImportRenderPreview>
export type TransferResult = Required<ImportTransferResult>
export type ImportFilePreviewSheet = Required<GenImportFilePreviewSheet>
export type ImportFilePreview = GenImportFilePreview & {
  sheets: ImportFilePreviewSheet[]
}

// Required<> retire l'optionnalité (le serveur émet toujours les champs à
// défaut pydantic) mais conserve les unions `| null`.
export type ImportedVariant = Required<ImportedVariantOutput>

export type ImportedProduct = Required<
  Omit<ImportedProductOutput, "variants">
> & {
  variants: ImportedVariant[]
}

export type ImportItemPublic = GenImportItemPublic & {
  payload: ImportedProduct
  warnings: string[]
}

export type ImportJobPublic = GenImportJobPublic & {
  counts: ImportJobCounts
  file_names: string[]
  warnings: string[]
  totals: ImportJobTotals
}

// Le CSV voyage en chaînes décimales ; l'Output généré (réponses) est déjà
// tout-chaînes, et reste assignable à l'Input (corps de création).
export type ImportProfileConfig = Required<
  Omit<ImportProfileConfigOutput, "coefficient">
> & { coefficient: string | null }

export type ImportProfilePublic = GenImportProfilePublic & {
  config: ImportProfileConfig
}

export type Paginated<T> = {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// --- Jobs d'import ---

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
  return importsListImports({ query }) as Promise<{
    data?: Paginated<ImportJobPublic>
    error?: unknown
  }>
}

export function readImport(id: number) {
  return importsReadImport({ path: { import_id: id } }) as Promise<{
    data?: ImportJobPublic
    error?: unknown
  }>
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
  return importsPreviewImportFile({
    path: { import_id: id },
    query: index ? { index } : undefined,
  }) as Promise<{ data?: ImportFilePreview; error?: unknown }>
}

export function listImportItems(
  id: number,
  query?: { page?: number; page_size?: number },
) {
  return importsListImportItems({ path: { import_id: id }, query }) as Promise<{
    data?: Paginated<ImportItemPublic>
    error?: unknown
  }>
}

// --- CRUD des profils d'import ---

export function listImportProfiles() {
  return importProfilesListImportProfiles() as Promise<{
    data?: ImportProfilePublic[]
    error?: unknown
  }>
}

export function createImportProfile(body: {
  name: string
  supplier_match: string
  config: ImportProfileConfig
}) {
  return importProfilesCreateImportProfile({ body }) as Promise<{
    data?: ImportProfilePublic
    error?: unknown
  }>
}

export function updateImportProfile(
  id: number,
  body: Partial<{ name: string; supplier_match: string; config: ImportProfileConfig }>,
) {
  return importProfilesUpdateImportProfile({
    path: { profile_id: id },
    body,
  }) as Promise<{ data?: ImportProfilePublic; error?: unknown }>
}

export function deleteImportProfile(id: number) {
  return importProfilesDeleteImportProfile({ path: { profile_id: id } })
}

// --- Review des items (édition du payload, exclusion/réintégration) ---

export function patchImportItem(
  jobId: number,
  itemId: number,
  body: { payload?: ImportedProduct; status?: "ready_for_review" | "rejected" },
) {
  return importsUpdateImportItem({
    path: { import_id: jobId, item_id: itemId },
    body,
  }) as Promise<{ data?: ImportItemPublic; error?: unknown }>
}

/** Inclusion/exclusion en masse (« tout transférer / tout écarter ») :
 * un seul PATCH atomique au lieu d'une requête par item. */
export function bulkUpdateImportItems(
  jobId: number,
  ids: number[],
  status: "ready_for_review" | "rejected",
) {
  return importsBulkUpdateImportItems({
    path: { import_id: jobId },
    body: { ids, status },
  })
}

/** Associe (ou détache avec null) un profil d'import au job. */
export function setImportProfile(id: number, profileId: number | null) {
  return importsSetImportProfile({
    path: { import_id: id },
    body: { profile_id: profileId },
  }) as Promise<{ data?: ImportJobPublic; error?: unknown }>
}

/** Associe (ou détache avec null) le magasin de destination du job. */
export function setImportLocation(id: number, locationId: number | null) {
  return importsSetImportLocation({
    path: { import_id: id },
    body: { location_id: locationId },
  }) as Promise<{ data?: ImportJobPublic; error?: unknown }>
}

// --- Export Tillin (aperçu, CSV, transfert) ---

export function getImportRows(id: number, profileId?: number) {
  return importsPreviewImportRows({
    path: { import_id: id },
    query: profileId != null ? { profile_id: profileId } : undefined,
  }) as Promise<{ data?: ImportRowsPreview; error?: unknown }>
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
  return locationsListLocations()
}

/** Transfert vers Tillin. `location_id` absent → le backend utilise la
 * location du job (400 `location_required` s'il n'y en a pas). */
export function transferImport(
  id: number,
  body: { location_id?: number; profile_id?: number },
) {
  return importsTransferImport({ path: { import_id: id }, body }) as Promise<{
    data?: TransferResult
    error?: unknown
  }>
}

// --- Pont import → produits Tillin (liaison et lecture des produits créés) ---

/** Relie les items transférés aux produits Tillin (résolution par référence).
 * 400 `{code:"not_transferred"}` si l'import n'a pas encore été transféré. */
export function linkImportProducts(id: number) {
  return importsLinkImportProducts({ path: { import_id: id } }) as Promise<{
    data?: LinkProductsResult
    error?: unknown
  }>
}

/** Produits de l'import avec leur liaison Tillin (onglet « Par import »). */
export function getImportProducts(id: number) {
  return importsListImportProducts({ path: { import_id: id } }) as Promise<{
    data?: ImportProductsResponse
    error?: unknown
  }>
}
