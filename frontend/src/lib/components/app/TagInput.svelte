<script lang="ts">
  // Saisie de tags simple : Entrée ajoute, ✕ retire (pas d'autocomplete).
  import X from "@lucide/svelte/icons/x"

  import { Input } from "@/lib/components/ui/input"

  let {
    values = $bindable(),
    id,
    placeholder = "Ajouter puis Entrée",
    disabled = false,
  }: {
    values: string[]
    id?: string
    placeholder?: string
    disabled?: boolean
  } = $props()

  let draft = $state("")

  function add() {
    const value = draft.trim()
    if (!value) return
    if (!values.some((v) => v.toLowerCase() === value.toLowerCase())) {
      values = [...values, value]
    }
    draft = ""
  }

  function remove(value: string) {
    values = values.filter((v) => v !== value)
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Enter") {
      event.preventDefault()
      add()
    } else if (event.key === "Backspace" && draft === "" && values.length > 0) {
      values = values.slice(0, -1)
    }
  }
</script>

<div class="flex flex-col gap-1.5">
  {#if values.length > 0}
    <div class="flex flex-wrap items-center gap-1.5">
      {#each values as value (value)}
        <span
          class="bg-muted/50 inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs"
        >
          {value}
          <button
            type="button"
            class="text-muted-foreground hover:text-foreground -mr-0.5 cursor-pointer rounded-full p-0.5"
            aria-label={`Retirer ${value}`}
            {disabled}
            onclick={() => remove(value)}
          >
            <X size={12} aria-hidden="true" />
          </button>
        </span>
      {/each}
    </div>
  {/if}
  <Input
    {id}
    {placeholder}
    {disabled}
    class="h-9 text-sm"
    bind:value={draft}
    onkeydown={onKeydown}
    onblur={add}
  />
</div>
