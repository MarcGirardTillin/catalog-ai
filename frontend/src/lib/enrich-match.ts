// Information qui a permis de rapprocher la fiche source du produit Tillin
// (resolution_json.matched_by, posé par le backend depuis 2026-10-08).
import type { ItemPublic } from "@/client";

const MATCH_LABELS: Record<string, string> = {
  barcode: "code-barres",
  reference: "référence",
  title: "titre",
};

export function matchedByLabel(item: ItemPublic): string | null {
  const value = item.resolution_json?.matched_by;
  if (typeof value === "string") return MATCH_LABELS[value] ?? value;
  // Items antérieurs : seul un score de 1 est univoque (code-barres exact).
  if (item.source_url && item.match_score === 1) return MATCH_LABELS.barcode;
  return null;
}
