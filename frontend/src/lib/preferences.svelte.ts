// Préférences UI de l'utilisateur, partagées entre les pages (module d'état
// Svelte 5). Les défauts s'appliquent tant que le chargement n'a pas abouti.
import { toast } from "svelte-sonner"

import { settingsReadMyPreferences, settingsUpdateMyPreferences } from "@/client"
import type { UserPreferences } from "@/client"

export const prefs = $state<Required<UserPreferences>>({
  shortcuts_enabled: false,
  auto_advance: true,
  density: "comfortable",
  products_per_page: 20,
})

let loaded = false

/** Charge les préférences une fois par session ; en cas d'erreur, les défauts restent. */
export async function loadPreferences(): Promise<void> {
  if (loaded) return
  loaded = true
  const { data, error } = await settingsReadMyPreferences()
  if (error || !data) return
  prefs.shortcuts_enabled = data.shortcuts_enabled ?? prefs.shortcuts_enabled
  prefs.auto_advance = data.auto_advance ?? prefs.auto_advance
  prefs.density = data.density ?? prefs.density
  prefs.products_per_page = data.products_per_page ?? prefs.products_per_page
}

/** Sauvegarde l'objet complet (le PUT remplace toutes les préférences). */
export async function savePreferences(): Promise<void> {
  const { error } = await settingsUpdateMyPreferences({ body: { ...prefs } })
  if (error) toast.error("Enregistrement des préférences impossible.")
  else toast.success("Préférences enregistrées")
}
