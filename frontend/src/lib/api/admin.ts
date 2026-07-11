// Appels typés vers la console admin (opérateur uniquement — le backend
// répond 403 admin_required pour les autres). Même pattern que lib/api/usage :
// instance axios du client généré, chemins bruts.
import { client } from "@/client/client.gen"

import type { UsageByJob, UsageSummary } from "@/lib/api/usage"

export type AdminAccountSummary = {
  id: number
  name: string
  user_count: number
  created_at: string
  last_activity_at: string | null
}

// Montants en chaînes décimales JSON.
export type AdminOverviewLine = {
  account_id: number
  account_name: string
  cost: string
  billable: string
  margin: string
  coefficient: number
  jobs_count: number
  imports_count: number
  failed_items: number
}

export type AdminOverview = {
  month: string
  currency: string
  lines: AdminOverviewLine[]
}

export type AdminActivityEntry = {
  job_id: number
  job_type: string
  label: string
  status: string
  total_items: number
  failed_items: number
  created_at: string
}

export type AdminAccountActivity = {
  account_id: number
  entries: AdminActivityEntry[]
}

// Réglages complets d'un compte, vue opérateur (mêmes clés qu'AccountSettings).
export type AdminAccountSettings = {
  title_template: string | null
  title_case: "none" | "upper" | "capitalize"
  editorial_instructions: string | null
  client_context: string | null
  meta_max_length: number
  notify_on_job_done: boolean
  notify_email: string | null
  billing_coefficient: number
  billing_day: number
  minutes_saved_per_import_product: number
  minutes_saved_per_enriched_product: number
}

export function listAdminAccounts() {
  return client.get<{ 200: AdminAccountSummary[] }, unknown>({
    responseType: "json",
    url: "/admin/accounts",
  })
}

export function getAdminOverview(month?: string) {
  return client.get<{ 200: AdminOverview }, unknown>({
    responseType: "json",
    url: "/admin/overview",
    query: month ? { month } : undefined,
  })
}

/** Summary COMPLET (non expurgé) d'un compte. */
export function getAdminAccountUsage(accountId: number, month?: string) {
  return client.get<{ 200: UsageSummary }, unknown>({
    responseType: "json",
    url: `/admin/accounts/${accountId}/usage`,
    query: month ? { month } : undefined,
  })
}

/** Détail par job COMPLET (non expurgé) d'un compte. */
export function getAdminAccountUsageByJob(accountId: number, month?: string) {
  return client.get<{ 200: UsageByJob }, unknown>({
    responseType: "json",
    url: `/admin/accounts/${accountId}/usage/by-job`,
    query: month ? { month } : undefined,
  })
}

export function getAdminAccountActivity(accountId: number) {
  return client.get<{ 200: AdminAccountActivity }, unknown>({
    responseType: "json",
    url: `/admin/accounts/${accountId}/activity`,
  })
}

export function getAdminAccountSettings(accountId: number) {
  return client.get<{ 200: AdminAccountSettings }, unknown>({
    responseType: "json",
    url: `/admin/accounts/${accountId}/settings`,
  })
}

/** Écriture opérateur des réglages d'un compte (objet COMPLET). */
export function putAdminAccountSettings(
  accountId: number,
  body: AdminAccountSettings,
) {
  return client.put<{ 200: AdminAccountSettings }, unknown>({
    responseType: "json",
    url: `/admin/accounts/${accountId}/settings`,
    body,
    headers: { "Content-Type": "application/json" },
  })
}
