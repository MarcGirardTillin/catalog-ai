<script lang="ts">
  // Boîte de dialogue modale maison (pas de lib externe) : overlay + carte
  // centrée, fermeture par Échap ou clic sur le fond (désactivable pendant
  // une action en cours via `dismissable`). Le contenu (corps + boutons) est
  // fourni par l'appelant via le snippet children.
  import type { Snippet } from "svelte"
  import X from "@lucide/svelte/icons/x"

  let {
    title,
    onClose,
    dismissable = true,
    children,
  }: {
    title: string
    onClose: () => void
    /** false = Échap/clic fond/✕ inactifs (action en cours). */
    dismissable?: boolean
    children: Snippet
  } = $props()

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape" && dismissable) onClose()
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div
  class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
  role="dialog"
  aria-modal="true"
  aria-label={title}
>
  <button
    type="button"
    class="absolute inset-0"
    aria-label="Fermer"
    tabindex="-1"
    onclick={() => dismissable && onClose()}
  ></button>
  <div
    class="bg-card border-border relative flex w-full max-w-md flex-col gap-4 rounded-lg border p-4 shadow-2xl"
  >
    <div class="flex items-start justify-between gap-3">
      <h2 class="font-title text-base font-bold">{title}</h2>
      <button
        type="button"
        class="text-muted-foreground hover:text-foreground -m-1 rounded-full p-1 transition-colors"
        aria-label="Fermer"
        disabled={!dismissable}
        onclick={onClose}
      >
        <X size={16} />
      </button>
    </div>
    {@render children()}
  </div>
</div>
