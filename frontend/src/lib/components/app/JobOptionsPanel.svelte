<script lang="ts">
  // Options de génération à la création d'un job (instructions, SEO, sources).
  // Le parent récupère la config via `collectConfig()` (bind:this) : seules
  // les clés effectivement renseignées sont envoyées au backend.
  import { onMount } from "svelte"

  import { listInstructions } from "@/lib/api/instructions"
  import type { InstructionPublic } from "@/lib/api/instructions"
  import { Label } from "@/lib/components/ui/label"
  import TagInput from "@/lib/components/app/TagInput.svelte"

  const uid = $props.id()

  let instructions = $state<InstructionPublic[]>([])
  // Bibliothèque indisponible (backend pas encore déployé, réseau…) : le
  // panneau reste utilisable avec « Automatique » et « Texte libre ».
  let libraryUnavailable = $state(false)

  // "" = automatique, "custom" = texte libre, sinon l'id d'une instruction.
  let instructionChoice = $state("")
  let customText = $state("")
  let keywords = $state<string[]>([])
  let urlsRaw = $state("")

  onMount(async () => {
    const { data, error } = await listInstructions()
    if (error || data === undefined) {
      libraryUnavailable = true
      return
    }
    instructions = data
  })

  /** Clés de config reconnues par le backend, uniquement si renseignées. */
  export function collectConfig(): Record<string, unknown> {
    const config: Record<string, unknown> = {}
    if (instructionChoice === "custom") {
      const text = customText.trim()
      if (text) config.editorial_instructions = text
    } else if (instructionChoice !== "") {
      config.instruction_id = Number(instructionChoice)
    }
    if (keywords.length > 0) config.seo_keywords = [...keywords]
    const urls = urlsRaw
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line !== "")
    if (urls.length > 0) config.extra_website_urls = urls
    return config
  }
</script>

<div class="flex flex-col gap-4">
  <div class="flex flex-col gap-1.5">
    <Label for="{uid}-instruction">Instructions éditoriales</Label>
    <select
      id="{uid}-instruction"
      class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
      bind:value={instructionChoice}
    >
      <option value="">Automatique (défauts par catégorie)</option>
      {#each instructions as instruction (instruction.id)}
        <option value={String(instruction.id)}>{instruction.name}</option>
      {/each}
      <option value="custom">Texte libre…</option>
    </select>
    {#if libraryUnavailable}
      <p class="text-muted-foreground text-xs">
        Bibliothèque d'instructions indisponible pour le moment.
      </p>
    {/if}
    {#if instructionChoice === "custom"}
      <textarea
        id="{uid}-custom-instruction"
        rows="3"
        aria-label="Instructions éditoriales en texte libre"
        class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content max-h-60 min-h-20 w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
        placeholder="Instructions ponctuelles pour ce job uniquement…"
        bind:value={customText}
      ></textarea>
    {/if}
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="{uid}-keywords">Mots-clés SEO</Label>
    <TagInput
      id="{uid}-keywords"
      bind:values={keywords}
      placeholder="Ex. mode enfant — Entrée pour ajouter"
    />
  </div>

  <div class="flex flex-col gap-1.5">
    <Label for="{uid}-urls">Sources supplémentaires</Label>
    <textarea
      id="{uid}-urls"
      rows="3"
      class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content max-h-60 min-h-20 w-full resize-none rounded-md border p-2.5 font-mono text-xs transition-colors outline-none focus-visible:ring-1"
      placeholder={"Une URL par ligne, ex.\nhttps://www.marque.com/collection"}
      bind:value={urlsRaw}
    ></textarea>
    <p class="text-muted-foreground text-xs">
      Pages web consultées en plus des sites de la marque pendant la génération.
    </p>
  </div>
</div>
