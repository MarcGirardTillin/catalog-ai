<script lang="ts" module>
  // Statut d'une image source dans le studio.
  export type WorkStatus = "idle" | "running" | "done" | "failed" | "saved"
</script>

<script lang="ts">
  // Grille des images sources du produit : sélection multiple + badge d'état.
  import type { ProductImage } from "@/client"

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
    <button
      type="button"
      class="group relative overflow-hidden rounded-md border text-left transition-shadow
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
      <span
        class="border-input absolute top-1.5 left-1.5 flex size-4 items-center justify-center rounded-sm border bg-white/90 text-[10px] font-bold
          {checked ? 'border-primary bg-primary text-primary-foreground' : 'text-transparent'}"
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
  {/each}
</div>
