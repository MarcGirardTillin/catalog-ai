// Réglages de compte partagés entre les pages (module d'état Svelte 5),
// chargés paresseusement : la review lit meta_max_length sans refetch à
// chaque item. Les défauts s'appliquent tant que le chargement n'a pas abouti.
import { settingsReadAccountSettings, settingsUpdateAccountSettings } from "@/client"
import type { AccountSettings } from "@/client"

// Le backend expose désormais `billing_coefficient` (coefficient de
// facturation de la consommation) ; le type généré ne le connaît pas encore —
// extension locale en attendant la régénération du client.
export type AccountSettingsExtended = AccountSettings & {
  client_context?: string | null
  billing_coefficient?: number
}

export const accountSettings = $state({
  meta_max_length: 160,
})

let loaded = false

/** Charge les réglages de compte une fois par session ; en cas d'erreur, les défauts restent. */
export async function loadAccountSettings(): Promise<void> {
  if (loaded) return
  loaded = true
  const { data, error } = await settingsReadAccountSettings()
  if (error || !data) return
  accountSettings.meta_max_length = data.meta_max_length ?? 160
}

/**
 * Met à jour une partie des réglages de compte en préservant les autres
 * champs : GET de l'objet complet, fusion du patch, PUT. Utilisé par les
 * pages qui n'éditent qu'un sous-ensemble (Enrichissement, Consommation,
 * Paramètres). Retourne false si la lecture ou l'écriture échoue.
 */
export async function saveAccountSettingsPartial(
  patch: Partial<AccountSettingsExtended>,
): Promise<boolean> {
  const { data, error } = await settingsReadAccountSettings()
  if (error || !data) return false
  const body: AccountSettingsExtended = { ...data, ...patch }
  const { error: putError } = await settingsUpdateAccountSettings({ body })
  if (putError !== undefined) return false
  if (patch.meta_max_length != null) {
    // Répercute la valeur sur le store partagé (compteur meta en review).
    accountSettings.meta_max_length = patch.meta_max_length
  }
  return true
}
