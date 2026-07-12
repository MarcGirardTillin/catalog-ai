<script lang="ts" module>
  // Options de normalisation entièrement renseignées (le studio pré-remplit
  // depuis les réglages du compte puis envoie l'objet complet au backend).
  export type StudioOptions = {
    remove_bg: boolean
    bg_color: string
    ratio: "4:5" | "1:1" | "3:4" | "16:9" | "original"
    center: boolean
    format: "webp" | "jpeg" | "jpg" | "png"
    quality: number
    max_kb: number
  }

  export const RATIO_LABELS: Record<StudioOptions["ratio"], string> = {
    "4:5": "4:5 (portrait e-commerce)",
    "1:1": "1:1 (carré)",
    "3:4": "3:4",
    "16:9": "16:9 (paysage)",
    original: "Format d'origine",
  }
</script>

<script lang="ts">
  // Panneau « traitements à la carte » : chaque étape de la normalisation est
  // débrayable. Seul le détourage appelle le service d'imagerie (facturé) —
  // le reste est de la composition locale.
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Select } from "@/lib/components/ui/select"
  import { Switch } from "@/lib/components/ui/switch"

  let {
    options = $bindable(),
    disabled = false,
  }: { options: StudioOptions; disabled?: boolean } = $props()

  const hexValue = $derived(`#${options.bg_color.replace(/^#/, "")}`)

  function onColorPicked(event: Event) {
    const value = (event.currentTarget as HTMLInputElement).value
    options.bg_color = value.replace(/^#/, "").toUpperCase()
  }
</script>

<div class="grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
  <div class="flex items-center gap-2">
    <Switch id="opt-removebg" {disabled} bind:checked={options.remove_bg} />
    <Label for="opt-removebg" class="font-normal">Détourer le produit</Label>
  </div>
  <div class="flex items-center gap-2">
    <Switch id="opt-center" {disabled} bind:checked={options.center} />
    <Label for="opt-center" class="font-normal">Centrer le produit</Label>
  </div>
  <div class="flex items-center gap-2">
    <Label for="opt-bg" class="shrink-0">Fond</Label>
    <input
      id="opt-bg"
      type="color"
      class="border-input h-9 w-10 shrink-0 cursor-pointer rounded-md border p-1"
      {disabled}
      value={hexValue}
      onchange={onColorPicked}
    />
    <Input
      class="font-mono uppercase"
      maxlength={7}
      {disabled}
      bind:value={options.bg_color}
    />
  </div>
  <div class="flex items-center gap-2">
    <Label for="opt-ratio" class="shrink-0">Format</Label>
    <Select id="opt-ratio" {disabled} bind:value={options.ratio}>
      {#each Object.entries(RATIO_LABELS) as [value, label] (value)}
        <option {value}>{label}</option>
      {/each}
    </Select>
  </div>
  <div class="flex items-center gap-2">
    <Label for="opt-format" class="shrink-0">Fichier</Label>
    <Select id="opt-format" {disabled} bind:value={options.format}>
      <option value="webp">WebP (recommandé)</option>
      <option value="jpeg">JPEG</option>
      <option value="png">PNG</option>
    </Select>
  </div>
  <div class="flex items-center gap-2">
    <Label for="opt-quality" class="shrink-0">Qualité</Label>
    <Input
      id="opt-quality"
      type="number"
      min="1"
      max="100"
      step="1"
      inputmode="numeric"
      {disabled}
      bind:value={options.quality}
    />
    <Label for="opt-maxkb" class="shrink-0">Poids max (Ko)</Label>
    <Input
      id="opt-maxkb"
      type="number"
      min="10"
      max="5000"
      step="10"
      inputmode="numeric"
      {disabled}
      bind:value={options.max_kb}
    />
  </div>
</div>
