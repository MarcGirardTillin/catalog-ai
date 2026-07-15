<script lang="ts">
  // Visionneuse plein écran : agrandit une image (blob ou URL) pour la
  // consulter. Fermeture par clic n'importe où, bouton ✕ ou Échap.
  import X from "@lucide/svelte/icons/x"

  let {
    src,
    alt = "Aperçu agrandi",
    onClose,
  }: { src: string; alt?: string; onClose: () => void } = $props()

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") onClose()
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div
  class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
  role="dialog"
  aria-modal="true"
  aria-label={alt}
>
  <button
    type="button"
    class="absolute inset-0 cursor-zoom-out"
    aria-label="Fermer l'aperçu"
    onclick={onClose}
  ></button>
  <img
    {src}
    {alt}
    class="pointer-events-none relative max-h-full max-w-full rounded-md object-contain shadow-2xl"
  />
  <button
    type="button"
    class="absolute top-4 right-4 rounded-full bg-black/60 p-2 text-white transition-colors hover:bg-black/80"
    aria-label="Fermer l'aperçu"
    onclick={onClose}
  >
    <X size={18} />
  </button>
</div>
