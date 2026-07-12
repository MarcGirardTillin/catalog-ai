// Libellés fr partagés des données de consommation (pages client et admin).
// Le mapping provider → service reflète SERVICE_LABELS côté backend : pour un
// client le backend l'applique déjà (redaction serveur) ; côté admin les
// providers arrivent en clair et le regroupement « par service » se fait ici.

export const SERVICE_LABELS: Record<string, string> = {
  claude: "Génération de texte",
  openai: "Génération de texte",
  photoroom: "Traitement d'image",
  fashn: "Traitement d'image",
  firecrawl: "Recherche produit",
}

/** Libellé de service du chiffrage image — pivot de la colonne « Images traitées ». */
export const IMAGE_SERVICE_LABEL = "Traitement d'image"

export function serviceLabel(provider: string): string {
  return SERVICE_LABELS[provider] ?? "Autre"
}

/** Normalise un champ provider en libellé de service, que le payload soit
 *  expurgé (provider = déjà un libellé, conservé tel quel) ou complet
 *  (provider brut type "photoroom" → mappé). Un admin qui consulte la page
 *  Consommation client reçoit le payload complet : sans cette normalisation,
 *  les compteurs par service tombent à zéro. */
export function toServiceLabel(provider: string): string {
  return SERVICE_LABELS[provider] ?? provider
}

// Libellés fr des métriques techniques (repli : nom brut).
export const METRIC_LABELS: Record<string, string> = {
  input_tokens: "Unités de texte (entrée)",
  output_tokens: "Unités de texte (sortie)",
  images: "Images traitées",
  credits: "Crédits de génération",
  web_searches: "Recherches web",
  search_credits: "Recherches produit",
  extract_credits: "Extractions de page",
}

export function metricLabel(metric: string): string {
  return METRIC_LABELS[metric] ?? metric
}
