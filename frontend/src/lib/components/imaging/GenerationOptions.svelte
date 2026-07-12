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
      <select
        id="{idPrefix}-framing"
        class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
        {disabled}
        bind:value={config.framing}
      >
        <option value="full_body">Mannequin entier</option>
        <option value="cropped_head">Tête coupée (sans visage)</option>
      </select>
    </div>
    <div class="flex flex-col gap-1.5">
      <Label for="{idPrefix}-scene">Ambiance</Label>
      <select
        id="{idPrefix}-scene"
        class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
        {disabled}
        bind:value={config.scene}
      >
        <option value="studio">Photo studio (fond neutre)</option>
        <option value="lifestyle">Mise en scène (lifestyle)</option>
      </select>
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
