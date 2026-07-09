<script lang="ts">
  // Select stylé sur un référentiel de titres (même apparence que
  // FilterSelect). La valeur courante est injectée en tête si elle ne figure
  // pas dans le référentiel (une valeur extraite n'est jamais perdue) ; sans
  // référentiel chargé, repli sur un champ texte libre.
  import { Input } from "@/lib/components/ui/input"

  let {
    id,
    options,
    value = $bindable(),
    emptyLabel = "—",
    ariaLabel,
    placeholder,
    compact = false,
    onchange,
  }: {
    id?: string
    options: string[]
    value: string
    emptyLabel?: string
    ariaLabel?: string
    placeholder?: string
    /** Variante compacte (grille de review). */
    compact?: boolean
    onchange?: () => void
  } = $props()

  const selectClass = $derived(
    "border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 w-full rounded-md border transition-colors outline-none focus-visible:ring-1 " +
      (compact ? "h-8 px-2 text-xs" : "h-9 px-2.5 text-sm"),
  )

  const merged = $derived(
    value !== "" && !options.includes(value) ? [value, ...options] : options,
  )
</script>

{#if options.length === 0}
  <Input
    {id}
    aria-label={ariaLabel}
    {placeholder}
    class={compact ? "h-8 text-xs" : undefined}
    bind:value
    onchange={() => onchange?.()}
  />
{:else}
  <select
    {id}
    aria-label={ariaLabel}
    class={selectClass}
    bind:value
    onchange={() => onchange?.()}
  >
    <option value="">{emptyLabel}</option>
    {#each merged as title (title)}
      <option value={title}>{title}</option>
    {/each}
  </select>
{/if}
