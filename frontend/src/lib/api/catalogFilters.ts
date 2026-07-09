// Référentiel de classification (marques, catégories, saisons, fournisseurs,
// compositions) exposé par GET /catalog/filters. Chargé paresseusement et mis
// en cache pour la session : plusieurs composants (grille de review, formulaire
// de profil) le consomment sans re-requêter.
//
// `compositions` est plus récent que le client généré : on étend le type ici.
import { catalogGetFilters } from "@/client"
import type { CatalogFilters, FilterOption } from "@/client"

export type CatalogFiltersData = CatalogFilters & {
  compositions?: FilterOption[]
}

let cached: Promise<CatalogFiltersData | null> | null = null

/** Charge le référentiel une fois ; renvoie null en cas d'échec (les champs
 * concernés restent alors de simples champs texte). Un échec n'est pas mis en
 * cache : la prochaine page réessaiera. */
export async function loadCatalogFilters(): Promise<CatalogFiltersData | null> {
  if (cached === null) {
    cached = catalogGetFilters()
      .then(({ data }) => (data as CatalogFiltersData | undefined) ?? null)
      .catch(() => null)
  }
  const result = await cached
  if (result === null) cached = null
  return result
}

/** Titres (dédupliqués) d'une liste d'options, pour alimenter un <datalist>. */
export function optionTitles(options: FilterOption[] | undefined): string[] {
  return [
    ...new Set((options ?? []).map((o) => o.title).filter((t) => t.trim() !== "")),
  ]
}
