<script lang="ts">
  // Sélecteur « quoi enrichir » (transformations + instruction éditoriale),
  // partagé par le panneau produit et le pont import → enrichissement. Bouton
  // qui ouvre un petit panneau ; « Lancer » remonte le choix via onLaunch.
  import Sparkles from "@lucide/svelte/icons/sparkles"

  import { listInstructions, type InstructionPublic } from "@/lib/api/instructions"
  import { Button } from "@/lib/components/ui/button"

  type Transforms = {
    copy: boolean
    title: boolean
    weights: boolean
    images: boolean
  }

  let {
    label = "Enrichir",
    launchLabel = "Lancer l'enrichissement",
    busy = false,
    align = "left",
    onLaunch,
  }: {
    label?: string
    launchLabel?: string
    busy?: boolean
    align?: "left" | "right"
    onLaunch: (transforms: Transforms, instructionId: number | null) => void
  } = $props()

  let open = $state(false)
  let copy = $state(true)
  let title = $state(true)
  let weights = $state(true)
  let images = $state(true)
  const none = $derived(!copy && !title && !weights && !images)

  // Instruction éditoriale : sans choix explicite, les défauts du compte
  // s'appliquent (« Automatique »).
  let instructions = $state<InstructionPublic[]>([])
  let loaded = false
  let instructionId = $state("")

  function toggle() {
    open = !open
    if (open && !loaded) {
      loaded = true
      listInstructions().then(({ data }) => {
        instructions = data ?? []
      })
    }
  }

  function launch() {
    open = false
    onLaunch(
      { copy, title, weights, images },
      instructionId === "" ? null : Number(instructionId),
    )
  }
</script>

<div class="relative">
  <Button size="sm" disabled={busy} aria-expanded={open} onclick={toggle}>
    <Sparkles size={14} aria-hidden="true" />
    {busy ? "Préparation…" : label}
  </Button>
  {#if open}
    <div
      class="border-border bg-background absolute top-full z-20 mt-1 flex w-64 flex-col gap-2 rounded-md border p-3 shadow-md {align ===
      'right'
        ? 'right-0'
        : 'left-0'}"
    >
      <p class="text-xs font-medium">Quoi enrichir ?</p>
      <label class="flex items-center gap-1.5 text-xs">
        <input type="checkbox" bind:checked={copy} />
        Description & méta description
      </label>
      <label class="flex items-center gap-1.5 text-xs">
        <input type="checkbox" bind:checked={title} />
        Titre (modèle du compte)
      </label>
      <label class="flex items-center gap-1.5 text-xs">
        <input type="checkbox" bind:checked={weights} />
        Poids des variantes
      </label>
      <label class="flex items-center gap-1.5 text-xs">
        <input type="checkbox" bind:checked={images} />
        Images (visuels source)
      </label>
      <label class="flex flex-col gap-1 text-xs">
        Instructions éditoriales
        <select
          class="border-input bg-card text-foreground h-8 w-full rounded-md border px-2 text-xs outline-none"
          bind:value={instructionId}
        >
          <option value="">Automatique (défauts du compte)</option>
          {#each instructions as instruction (instruction.id)}
            <option value={String(instruction.id)}>{instruction.name}</option>
          {/each}
        </select>
      </label>
      <Button size="sm" disabled={none || busy} onclick={launch}>
        {launchLabel}
      </Button>
    </div>
  {/if}
</div>
