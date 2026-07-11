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
