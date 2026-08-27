<script lang="ts" module>
  // Options communes aux deux générations Photoroom « une image -> une
  // image » : mise à plat (flat lay) et mannequin invisible (ghost
  // mannequin). Format + style libre optionnel.
  export type FlatGhostConfig = {
    ratio: "4:5" | "1:1" | "3:4" | "16:9"
    prompt: string
    resolution: "1k" | "2k" | "4k"
    /** Moteur de la mise à plat (ignoré par le ghost mannequin). */
    engine: "photoroom" | "gpt"
    /** Couleur exacte du vêtement (hex) ; "" = celle de la photo source. */
    garmentColor: string
  }
</script>

<script lang="ts">
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Select } from "@/lib/components/ui/select"

  let {
    config = $bindable(),
    disabled = false,
    idPrefix = "flat",
    promptPlaceholder = "Ex. fond lin clair, lumière naturelle, plié soigneusement…",
    showEngine = false,
  }: {
    config: FlatGhostConfig
    disabled?: boolean
    idPrefix?: string
    promptPlaceholder?: string
    /** Affiche le sélecteur de moteur (mise à plat uniquement). */
    showEngine?: boolean
  } = $props()
</script>

<div class="flex flex-col gap-3">
  {#if showEngine}
    <div class="flex flex-col gap-1.5">
      <Label for="{idPrefix}-engine">Moteur</Label>
      <Select id="{idPrefix}-engine" {disabled} bind:value={config.engine}>
        <option value="photoroom">Photoroom — flat lay</option>
        <option value="gpt">GPT Image — composition guidée (multi-vues)</option>
      </Select>
    </div>
  {/if}
  <div class="flex flex-col gap-1.5">
    <Label for="{idPrefix}-ratio">Format</Label>
    <Select id="{idPrefix}-ratio" {disabled} bind:value={config.ratio}>
      <option value="4:5">Portrait 4:5</option>
      <option value="3:4">Portrait 3:4</option>
      <option value="1:1">Carré 1:1</option>
      <option value="16:9">Paysage 16:9</option>
    </Select>
  </div>
  {#if showEngine}
    <div class="flex flex-col gap-1.5">
      <Label for="{idPrefix}-garment-color">Couleur du vêtement (optionnel)</Label>
      <div class="flex items-center gap-2">
        <input
          id="{idPrefix}-garment-color"
          type="color"
          class="border-input bg-card h-9 w-12 cursor-pointer rounded-md border p-1"
          {disabled}
          value={/^#[0-9a-fA-F]{6}$/.test(config.garmentColor) ? config.garmentColor : "#888888"}
          oninput={(e) => (config.garmentColor = e.currentTarget.value)}
        />
        <Input
          class="max-w-32 font-mono"
          placeholder="#1F4E3D"
          {disabled}
          bind:value={config.garmentColor}
        />
        {#if config.garmentColor}
          <button
            type="button"
            class="text-muted-foreground cursor-pointer text-xs underline-offset-2 hover:underline"
            onclick={() => (config.garmentColor = "")}
          >
            Effacer
          </button>
        {/if}
      </div>
      <p class="text-muted-foreground text-xs">
        Impose la teinte exacte sur tous les rendus (la couleur dérive
        parfois entre générations). Vide = couleur de la photo.
      </p>
    </div>
  {/if}
  <div class="flex flex-col gap-1.5">
    <Label for="{idPrefix}-resolution">Qualité</Label>
    <Select id="{idPrefix}-resolution" {disabled} bind:value={config.resolution}>
      <option value="1k">1K — coût normal</option>
      <option value="2k">2K — coût ×2</option>
      <option value="4k">4K — coût ×4</option>
    </Select>
  </div>
  <div class="flex flex-col gap-1.5">
    <Label for="{idPrefix}-prompt">Style (optionnel)</Label>
    <textarea
      id="{idPrefix}-prompt"
      rows="2"
      class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content max-h-40 w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
      placeholder={promptPlaceholder}
      {disabled}
      bind:value={config.prompt}
    ></textarea>
  </div>
</div>
