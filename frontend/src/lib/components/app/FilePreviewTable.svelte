<script lang="ts">
  // Tableau d'aperçu brut d'un fichier tabulaire : la première ligne est
  // traitée comme en-tête, le reste défile dans un conteneur borné.
  type Sheet = {
    sheet?: string | null
    rows: string[][]
    total_rows?: number
    truncated?: boolean
  }

  let { sheets }: { sheets: Sheet[] } = $props()
</script>

<div class="flex flex-col gap-3">
  {#each sheets as table, index (index)}
    {#if table.sheet && sheets.length > 1}
      <p class="text-muted-foreground text-xs font-medium">Feuille : {table.sheet}</p>
    {/if}
    {#if table.rows.length === 0}
      <p class="text-muted-foreground text-xs">Feuille vide.</p>
    {:else}
      <div class="border-border max-h-80 overflow-auto rounded-md border">
        <table class="w-full text-xs">
          <thead class="bg-muted/50 sticky top-0">
            <tr>
              {#each table.rows[0] as header, col (col)}
                <th
                  class="text-muted-foreground border-border border-b px-2 py-1.5 text-left font-medium whitespace-nowrap"
                >
                  {header}
                </th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each table.rows.slice(1) as row, rowIndex (rowIndex)}
              <tr class="border-border/50 border-b last:border-b-0">
                {#each row as cell, col (col)}
                  <td class="max-w-48 truncate px-2 py-1 whitespace-nowrap" title={cell}>
                    {cell}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if table.truncated && table.total_rows}
        <p class="text-muted-foreground text-xs">
          Aperçu limité aux {table.rows.length} premières lignes sur {table.total_rows}.
        </p>
      {/if}
    {/if}
  {/each}
</div>
