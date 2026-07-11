// Metering de consommation : adaptateur fin au-dessus du client OpenAPI
// généré — les types viennent TOUS de src/client (aucune redéfinition à la
// main, donc aucune dérive possible avec le backend). Seul l'export CSV
// reste un appel brut (blob + cookies).
import {
  usageCreateUsagePrice,
  usageDeleteUsagePrice,
  usageListUsagePrices,
  usageReadUsageByJob,
  usageReadUsageSummary,
  usageReadUsageTimeseries,
  usageRefreezeSnapshot,
  usageUpdateUsagePrice,
} from "@/client"
import type { UsagePriceCreate, UsagePriceUpdate } from "@/client"
import { client } from "@/client/client.gen"

export type {
  UsageByJob,
  UsageJobLine,
  UsageJobMetric,
  UsagePriceCreate,
  UsageSummary,
  UsageSummaryLine,
  UsageTimeseries,
  UsageTimeseriesPoint,
  UsageTimeseriesSeries,
} from "@/client"
// Alias historiques (noms utilisés par les pages avant la migration).
export type { UsagePricePublic as UsagePrice } from "@/client"

export type UsageTimeseriesGroupBy = "none" | "model" | "provider"

export function getUsageSummary(month: string) {
  return usageReadUsageSummary({ query: { month } })
}

export function getUsageByJob(month: string) {
  return usageReadUsageByJob({ query: { month } })
}

/** Série temporelle quotidienne du facturable, regroupée ou non. */
export function getUsageTimeseries(
  month: string,
  groupBy: UsageTimeseriesGroupBy,
) {
  return usageReadUsageTimeseries({ query: { month, group_by: groupBy } })
}

/**
 * Re-figement d'un mois déjà facturé avec les tarifs actuels (admin).
 * 400 {code:"not_frozen"} si le mois n'est pas encore facturé.
 */
export function refreezeUsageMonth(month: string) {
  return usageRefreezeSnapshot({ query: { month } })
}

/** Export CSV du mois, en blob (l'auth passe par les cookies axios). */
export function getUsageExport(month: string) {
  return client.get<{ 200: Blob }, unknown>({
    responseType: "blob",
    url: "/usage/export",
    query: { month },
  })
}

// --- CRUD de la grille tarifaire (admin) ---

export function listUsagePrices() {
  return usageListUsagePrices()
}

export function createUsagePrice(body: UsagePriceCreate) {
  return usageCreateUsagePrice({ body })
}

export function updateUsagePrice(id: number, body: UsagePriceUpdate) {
  return usageUpdateUsagePrice({ path: { price_id: id }, body })
}

export function deleteUsagePrice(id: number) {
  return usageDeleteUsagePrice({ path: { price_id: id } })
}
