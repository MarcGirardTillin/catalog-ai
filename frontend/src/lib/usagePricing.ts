// Grille de coûts fournisseurs (vue opérateur) : helpers de saisie/affichage
// partagés entre la grille commune (/admin/pricing) et les exceptions d'un
// compte (/admin/accounts/:id). Les métriques *_tokens sont stockées à
// l'unité mais saisies et lues en € par million.

export function isTokenMetric(metric: string): boolean {
  return metric.trim().endsWith("_tokens")
}

/** Prix unitaire affiché : « 3,00 € / M » pour les tokens, sinon par unité. */
export function formatUnitPrice(
  metric: string,
  unitPrice: string | null | undefined,
): string {
  if (unitPrice == null) return "—"
  const n = Number(unitPrice)
  if (!Number.isFinite(n)) return "—"
  if (isTokenMetric(metric)) {
    return `${(n * 1_000_000).toLocaleString("fr-FR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })} € / M`
  }
  return `${n.toLocaleString("fr-FR", { maximumFractionDigits: 6 })} € / unité`
}

/** Chaîne décimale sans notation scientifique (ex. 3e-7 → "0.0000003"). */
export function toDecimalString(value: number): string {
  if (!Number.isFinite(value)) return "0"
  const fixed = value.toFixed(12)
  return fixed.includes(".") ? fixed.replace(/\.?0+$/, "") : fixed
}

/** Valeur du champ prix d'un formulaire (par million pour les tokens). */
export function priceInputValue(metric: string, unitPrice: string): string {
  const unit = Number(unitPrice)
  if (!Number.isFinite(unit)) return ""
  return String(isTokenMetric(metric) ? unit * 1_000_000 : unit)
}

/** Saisie du formulaire → prix unitaire stocké (null si invalide). */
export function unitPriceFromInput(metric: string, input: string): string | null {
  const value = Number(String(input).replace(",", "."))
  if (!Number.isFinite(value) || value < 0 || String(input).trim() === "") {
    return null
  }
  return toDecimalString(isTokenMetric(metric) ? value / 1_000_000 : value)
}

/** Code d'erreur métier renvoyé par l'API (`{code: "..."}`), s'il y en a un. */
export function apiErrorCode(error: unknown): string | undefined {
  return (error as { code?: string } | null)?.code
}
