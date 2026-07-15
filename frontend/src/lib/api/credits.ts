// Crédits prépayés : adaptateur fin au-dessus du client OpenAPI généré —
// solde/mouvements client, série quotidienne, et ledger admin (octrois).
import {
  adminGrantAccountCredits,
  adminReadAccountCredits,
  creditsReadCredits,
  creditsReadCreditTimeseries,
} from "@/client"
import type { CreditGrantRequest } from "@/client"

export type {
  AdminCredits,
  CreditEntryPublic,
  CreditGrantRequest,
  CreditMonth,
  CreditOverview,
  CreditPack,
  CreditTimeseries,
  CreditTimeseriesPoint,
  CreditTimeseriesSeries,
} from "@/client"

/**
 * Message à afficher quand un lancement est refusé pour solde insuffisant
 * (402 insufficient_credits), null pour toute autre erreur. Les boutons ne
 * sont pas désactivés côté client : le serveur est la source de vérité, le
 * toast explicite suffit.
 */
export function insufficientCreditsMessage(error: unknown): string | null {
  if (
    error &&
    typeof error === "object" &&
    (error as { code?: unknown }).code === "insufficient_credits"
  ) {
    return "Crédits épuisés — rechargez votre compte pour lancer de nouveaux traitements."
  }
  return null
}

/** Solde, packs et mouvements du mois du compte de l'utilisateur connecté. */
export function getCredits(month?: string) {
  return creditsReadCredits({ query: month ? { month } : undefined })
}

/** Crédits consommés par jour (une série par action, mois complet). */
export function getCreditTimeseries(month?: string) {
  return creditsReadCreditTimeseries({ query: month ? { month } : undefined })
}

// --- Admin (opérateur) ---

export function getAdminAccountCredits(accountId: number) {
  return adminReadAccountCredits({ path: { account_id: accountId } })
}

/** Écriture manuelle au ledger : octroi, achat de pack ou ajustement (signé). */
export function grantAdminAccountCredits(
  accountId: number,
  body: CreditGrantRequest,
) {
  return adminGrantAccountCredits({ path: { account_id: accountId }, body })
}
