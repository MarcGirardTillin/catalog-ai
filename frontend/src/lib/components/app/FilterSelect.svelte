<script lang="ts">
  import type { FilterOption } from "@/client"
  import { Select } from "@/lib/components/ui/select"

  // A compact native <select> for a classification filter. Value is the
  // selected option id (or null for "all").
  let {
    label,
    options,
    value = $bindable(),
    onchange,
  }: {
    label: string
    options: FilterOption[]
    value: number | null
    onchange?: () => void
  } = $props()
</script>

<label class="flex min-w-0 flex-1 flex-col gap-1">
  <span class="text-foreground text-xs font-medium">{label}</span>
  <Select class="px-2" bind:value onchange={() => onchange?.()}>
    <option value={null}>Tous</option>
    {#each options as option (option.id)}
      <option value={option.id}>{option.title}</option>
    {/each}
  </Select>
</label>
