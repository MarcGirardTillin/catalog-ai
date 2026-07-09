// Appels typés vers le metering de consommation (usage LLM et autres métriques).
//
// Ces endpoints sont plus récents que le client généré (src/client) : on
// réutilise son instance axios configurée (baseURL + cookies) via `client`
// et on appelle les chemins bruts. À remplacer par les fonctions générées
// après régénération OpenAPI.
import { client } from "@/client/client.gen"

// Les montants et prix voyagent en chaînes décimales JSON (ex. "0.000003").

export type UsageSummaryLine = {
  provider: string
  model: string | null
  metric: string
  quantity: number
  unit_price: string | null
  cost: string | null
  billable: string | null
}

export type UsageSummary = {
  month: string
  currency: string
  coefficient: number
  lines: UsageSummaryLine[]
  totals: { cost: string; billable: string }
  // Nombre de (provider, model, metric) consommés sans tarif dans la grille.
  unpriced_count: number
}

export type UsageJobMetric = {
  provider: string
  metric: string
  quantity: number
}

export type UsageJobLine = {
  job_id: number | null
  job_type: string | null
  label: string
  created_at: string | null
  input_tokens: number
  output_tokens: number
  other_metrics: UsageJobMetric[]
  cost: string | null
  billable: string | null
}

export type UsageByJob = {
  month: string
  jobs: UsageJobLine[]
}

export type UsagePrice = {
  id: number
  provider: string
  model: string | null
  metric: string
  unit_price: string
  currency: string
}

export type UsagePriceCreate = {
  provider: string
  model?: string | null
  metric: string
  unit_price: string
  currency?: string
}

// Le client généré attend TData sous forme de map { statut: type } et
// renvoie `{ data, error }` (throwOnError = false par défaut).

export function getUsageSummary(month: string) {
  return client.get<{ 200: UsageSummary }, unknown>({
    responseType: "json",
    url: "/usage/summary",
    query: { month },
  })
}

export function getUsageByJob(month: string) {
  return client.get<{ 200: UsageByJob }, unknown>({
    responseType: "json",
    url: "/usage/by-job",
    query: { month },
  })
}

/** Export CSV du mois, en blob (l'auth passe par les cookies axios). */
export function getUsageExport(month: string) {
  return client.get<{ 200: Blob }, unknown>({
    responseType: "blob",
    url: "/usage/export",
    query: { month },
  })
}

// --- CRUD de la grille tarifaire ---

export function listUsagePrices() {
  return client.get<{ 200: UsagePrice[] }, unknown>({
    responseType: "json",
    url: "/usage/prices",
  })
}

export function createUsagePrice(body: UsagePriceCreate) {
  return client.post<{ 201: UsagePrice }, unknown>({
    responseType: "json",
    url: "/usage/prices",
    body,
    headers: { "Content-Type": "application/json" },
  })
}

export function updateUsagePrice(id: number, body: Partial<UsagePriceCreate>) {
  return client.patch<{ 200: UsagePrice }, unknown>({
    responseType: "json",
    url: `/usage/prices/${id}`,
    body,
    headers: { "Content-Type": "application/json" },
  })
}

export function deleteUsagePrice(id: number) {
  return client.delete<{ 204: unknown }, unknown>({
    url: `/usage/prices/${id}`,
  })
}
