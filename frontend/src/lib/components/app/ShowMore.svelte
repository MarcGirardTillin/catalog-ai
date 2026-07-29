<script lang="ts" generics="T">
  // Pagination locale réutilisable pour les tableaux/listes voués à grossir :
  // n premières lignes + bouton « Voir plus (+step) ». Le composant possède
  // le compteur ; le parent rend les lignes visibles via le snippet.
  import { untrack, type Snippet } from "svelte"

  import { Button } from "@/lib/components/ui/button"

  let {
    items,
    initial = 10,
    step = 20,
    children,
  }: {
    items: T[]
    /** Nombre de lignes affichées au premier rendu. */
    initial?: number
    /** Lignes supplémentaires par clic sur « Voir plus ». */
    step?: number
    children: Snippet<[T[]]>
  } = $props()

  // Compteur initialisé une fois (la prop ne pilote que le premier rendu).
  let shown = $state(untrack(() => initial))
  const visible = $derived(items.slice(0, shown))
  const remaining = $derived(Math.max(0, items.length - shown))
</script>

{@render children(visible)}
{#if remaining > 0}
  <div class="flex items-center justify-center gap-2 py-1.5">
    <Button variant="ghost" size="sm" onclick={() => (shown += step)}>
      Voir plus (+{Math.min(step, remaining)})
    </Button>
    <span class="text-muted-foreground text-xs">
      {visible.length} sur {items.length}
    </span>
  </div>
{/if}
