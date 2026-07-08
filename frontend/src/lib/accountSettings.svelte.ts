// Réglages de compte partagés entre les pages (module d'état Svelte 5),
// chargés paresseusement : la review lit meta_max_length sans refetch à
// chaque item. Les défauts s'appliquent tant que le chargement n'a pas abouti.
import { settingsReadAccountSettings } from "@/client"
import type { AccountSettings } from "@/client"

// Le backend expose désormais `client_context` (contexte boutique markdown) ;
// le type généré ne le connaît pas encore — extension locale en attendant la
// régénération du client.
export type AccountSettingsExtended = AccountSettings & {
  client_context?: string | null
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
