<script lang="ts" module>
  // Config de génération de visuels (porté mannequin) : cadrage + ambiance +
  // directives libres — traduits en instruction FASHN côté serveur. Partagé
  // entre les réglages (défauts du compte) et le studio (override ponctuel).
  export type GenerationConfig = {
    framing: "full_body" | "cropped_head"
    scene: "studio" | "lifestyle"
    instructions: string
  }
</script>

<script lang="ts">
  import { Label } from "@/lib/components/ui/label"
  import { Select } from "@/lib/components/ui/select"

  let {
    config = $bindable(),
    disabled = false,
    idPrefix = "gen",
  }: { config: GenerationConfig; disabled?: boolean; idPrefix?: string } =
    $props()
</script>

<div class="flex flex-col gap-3">
  <div class="grid gap-3 sm:grid-cols-2">
    <div class="flex flex-col gap-1.5">
      <Label for="{idPrefix}-framing">Cadrage du mannequin</Label>
      <Select id="{idPrefix}-framing" {disabled} bind:value={config.framing}>
        <option value="full_body">Mannequin entier</option>
        <option value="cropped_head">Tête coupée (sans visage)</option>
      </Select>
    </div>
    <div class="flex flex-col gap-1.5">
      <Label for="{idPrefix}-scene">Ambiance</Label>
      <Select id="{idPrefix}-scene" {disabled} bind:value={config.scene}>
        <option value="studio">Photo studio (fond neutre)</option>
        <option value="lifestyle">Mise en scène (lifestyle)</option>
      </Select>
    </div>
  </div>
  <div class="flex flex-col gap-1.5">
    <Label for="{idPrefix}-instructions">Directives libres (optionnel)</Label>
    <textarea
      id="{idPrefix}-instructions"
      rows="2"
      class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content max-h-40 w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
      placeholder="Ex. style urbain, lumière chaude, mannequin en mouvement…"
      {disabled}
      bind:value={config.instructions}
    ></textarea>
  </div>
</div>
