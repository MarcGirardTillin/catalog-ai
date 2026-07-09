<script lang="ts">
  // Job/item status pill using the Tillin DS bg/fg/dot triplets (app.css).
  const STYLES: Record<string, { label: string; badge: string; dot: string }> = {
    // Item statuses.
    pending: { label: "En attente", badge: "bg-draft text-draft-foreground", dot: "bg-draft-dot" },
    processing: { label: "En cours", badge: "bg-info text-info-foreground", dot: "bg-info-dot" },
    ready_for_review: { label: "À vérifier", badge: "bg-warning text-warning-foreground", dot: "bg-warning-dot" },
    approved: { label: "Validé", badge: "bg-success text-success-foreground", dot: "bg-success-dot" },
    applied: { label: "Appliqué", badge: "bg-success text-success-foreground", dot: "bg-success-dot" },
    rejected: { label: "Écarté", badge: "bg-destructive/10 text-destructive", dot: "bg-destructive-dot" },
    failed: { label: "Échec", badge: "bg-destructive/10 text-destructive", dot: "bg-destructive-dot" },
    // Job statuses (pending/processing/failed shared above).
    completed: { label: "Terminé", badge: "bg-success text-success-foreground", dot: "bg-success-dot" },
    partial: { label: "Partiel", badge: "bg-warning text-warning-foreground", dot: "bg-warning-dot" },
  }

  // `context="import"` : l'état final `applied` se lit « Transféré » côté
  // imports (produit créé dans Tillin) vs « Appliqué » côté enrichissements.
  let { status, context }: { status: string; context?: "import" | "enrichment" } = $props()

  const style = $derived.by(() => {
    const base =
      STYLES[status] ?? { label: status, badge: "bg-muted text-muted-foreground", dot: "bg-muted-foreground" }
    if (status === "applied" && context === "import") {
      return { ...base, label: "Transféré" }
    }
    return base
  })
</script>

<span
  class={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${style.badge}`}
>
  <span class={`size-1.5 rounded-full ${style.dot}`} aria-hidden="true"></span>
  {style.label}
</span>
