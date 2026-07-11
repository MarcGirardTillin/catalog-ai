// Console admin (opérateur uniquement) : adaptateur fin au-dessus du client
// OpenAPI généré — types et appels viennent de src/client, zéro redéfinition.
import {
  adminListAccounts,
  adminReadAccountActivity,
  adminReadAccountSettingsAdmin,
  adminReadAccountTimeseries,
  adminReadAccountUsage,
  adminReadAccountUsageByJob,
  adminReadAdminTimeseries,
  adminReadOverview,
  adminUpdateAccountSettingsAdmin,
} from "@/client"
import type { AccountSettings } from "@/client"

export type {
  AdminAccountActivity,
  AdminAccountSummary,
  AdminActivityEntry,
  AdminOverview,
  AdminOverviewLine,
} from "@/client"
// Réglages complets d'un compte, vue opérateur.
export type AdminAccountSettings = AccountSettings

export function listAdminAccounts() {
  return adminListAccounts()
}

export function getAdminOverview(month?: string) {
  return adminReadOverview({ query: month ? { month } : undefined })
}

// Groupements du graphique opérateur : total, par service (libellés neutres),
// par modèle ou par provider.
export type AdminTimeseriesGroupBy = "none" | "service" | "model" | "provider"

/** Série quotidienne du facturable sommée sur TOUS les comptes. */
export function getAdminTimeseries(
  month: string,
  groupBy: AdminTimeseriesGroupBy,
) {
  return adminReadAdminTimeseries({ query: { month, group_by: groupBy } })
}

/** Série quotidienne du facturable d'UN compte (vue opérateur complète). */
export function getAdminAccountTimeseries(
  accountId: number,
  month: string,
  groupBy: AdminTimeseriesGroupBy,
) {
  return adminReadAccountTimeseries({
    path: { account_id: accountId },
    query: { month, group_by: groupBy },
  })
}

/** Summary COMPLET (non expurgé) d'un compte. */
export function getAdminAccountUsage(accountId: number, month?: string) {
  return adminReadAccountUsage({
    path: { account_id: accountId },
    query: month ? { month } : undefined,
  })
}

/** Détail par job COMPLET (non expurgé) d'un compte. */
export function getAdminAccountUsageByJob(accountId: number, month?: string) {
  return adminReadAccountUsageByJob({
    path: { account_id: accountId },
    query: month ? { month } : undefined,
  })
}

export function getAdminAccountActivity(accountId: number) {
  return adminReadAccountActivity({ path: { account_id: accountId } })
}

export function getAdminAccountSettings(accountId: number) {
  return adminReadAccountSettingsAdmin({ path: { account_id: accountId } })
}

/** Écriture opérateur des réglages d'un compte (objet COMPLET). */
export function putAdminAccountSettings(
  accountId: number,
  body: AdminAccountSettings,
) {
  return adminUpdateAccountSettingsAdmin({
    path: { account_id: accountId },
    body,
  })
}
