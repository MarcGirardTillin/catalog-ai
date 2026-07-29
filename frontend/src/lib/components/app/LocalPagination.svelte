<script lang="ts" generics="T">
  // Pagination locale réutilisable (même design que la page Produits :
  // Précédent · x / y · Suivant) pour les tableaux/listes voués à grossir.
  // Le composant possède la page courante ; le parent rend les lignes de la
  // page via le snippet.
  import type { Snippet } from "svelte"

  import { Button } from "@/lib/components/ui/button"

  let {
    items,
    pageSize = 10,
    children,
  }: {
    items: T[]
    pageSize?: number
    children: Snippet<[T[]]>
  } = $props()

  let page = $state(1)
  const totalPages = $derived(Math.max(1, Math.ceil(items.length / pageSize)))
  // Un filtre/refresh qui réduit la liste ne doit pas laisser la page hors
  // bornes.
  $effect(() => {
    if (page > totalPages) page = totalPages
  })
  const visible = $derived(items.slice((page - 1) * pageSize, page * pageSize))
</script>

{@render children(visible)}
{#if totalPages > 1}
  <div class="flex items-center justify-between gap-2 px-4 py-2">
    <Button variant="outline" size="sm" disabled={page <= 1} onclick={() => (page -= 1)}>
      Précédent
    </Button>
    <span class="text-muted-foreground font-mono text-xs">
      {page} / {totalPages}
    </span>
    <Button
      variant="outline"
      size="sm"
      disabled={page >= totalPages}
      onclick={() => (page += 1)}
    >
      Suivant
    </Button>
  </div>
{/if}
