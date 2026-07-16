<script lang="ts" module>
  // Statut d'une image source dans le studio.
  export type WorkStatus = "idle" | "running" | "done" | "failed" | "saved"
</script>

<script lang="ts">
  // Grille des images sources du produit : sélection multiple + badge d'état,
  // et zoom plein écran (même geste que les résultats du studio).
  import Maximize2 from "@lucide/svelte/icons/maximize-2"

  import type { ProductImage } from "@/client"

  import Lightbox from "./Lightbox.svelte"

  let {
    images,
    statuses,
    selected,
    onToggle,
    disabled = false,
  }: {
    images: ProductImage[]
    statuses: Record<string, WorkStatus>
    selected: string[]
    onToggle: (url: string) => void
    disabled?: boolean
  } = $props()

  // Zoom plein écran (null = fermé).
  let lightboxSrc = $state<string | null>(null)

  const BADGES: Record<WorkStatus, { label: string; tone: string }> = {
    idle: { label: "", tone: "" },
    running: { label: "En cours…", tone: "bg-blue-500/15 text-blue-700 dark:text-blue-400" },
    done: { label: "Traitée", tone: "bg-amber-500/15 text-amber-700 dark:text-amber-400" },
    failed: { label: "Échec", tone: "bg-destructive/15 text-destructive" },
    saved: { label: "Enregistrée", tone: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400" },
  }
</script>

<div class="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
  {#each images as image (image.url)}
    {@const status = statuses[image.url] ?? "idle"}
    {@const badge = BADGES[status]}
    {@const checked = selected.includes(image.url)}
    <!-- Le zoom est un bouton FRÈRE de la tuile, pas un enfant : la tuile est
         elle-même un <button> (sélection) et un bouton imbriqué serait du HTML
         invalide. D'où l'enveloppe relative. -->
    <div class="relative">
      <button
        type="button"
        class="group relative w-full overflow-hidden rounded-md border text-left transition-shadow
          {checked ? 'border-primary ring-primary/40 ring-2' : 'border-border hover:ring-primary/30 hover:ring-1'}"
        disabled={disabled || status === 'running'}
        aria-pressed={checked}
        onclick={() => onToggle(image.url)}
      >
        <img
          src={image.url}
          alt="Image produit {image.position ?? ''}"
          class="bg-muted aspect-square w-full object-contain"
          loading="lazy"
        />
        <!-- Les classes bg/border vivent ENTIÈREMENT dans le conditionnel :
             deux utilitaires bg-* concurrents laisseraient l'ordre CSS décider. -->
        <span
          class="absolute top-1.5 left-1.5 flex size-4.5 items-center justify-center rounded-full border text-[11px] font-bold shadow-sm
            {checked
            ? 'border-primary bg-primary text-primary-foreground'
            : 'border-input bg-white/90 text-transparent'}"
          aria-hidden="true"
        >
          ✓
        </span>
        {#if badge.label}
          <span
            class="absolute right-1 bottom-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium {badge.tone}"
          >
            {badge.label}
          </span>
        {/if}
      </button>
      <!-- Le zoom reste actif même quand la tuile est désactivée (traitement
           en cours) : regarder une image ne change rien à l'état. -->
      <button
        type="button"
        class="bg-card/80 hover:bg-card text-foreground absolute top-1.5 right-1.5 rounded-full p-1.5 shadow-sm transition-colors"
        aria-label="Agrandir l'image {image.position ?? ''}"
        title="Agrandir"
        onclick={() => (lightboxSrc = image.url)}
      >
        <Maximize2 size={14} aria-hidden="true" />
      </button>
    </div>
  {/each}
</div>

{#if lightboxSrc}
  <Lightbox src={lightboxSrc} onClose={() => (lightboxSrc = null)} />
{/if}
