<script lang="ts" module>
  // Config de génération de visuels (porté mannequin) : moteur + cadrage +
  // ambiance + orientation + directives libres — traduits en instruction
  // FASHN ou en presets Photoroom Virtual Model côté serveur. Partagé entre
  // les réglages (défauts du compte) et le studio (override ponctuel).
  export type GenerationPose =
    | ""
    | "face"
    | "back"
    | "profile_left"
    | "profile_right"
    | "three_quarter_left"
    | "three_quarter_right"

  export type GenerationEngine = "fashn" | "photoroom"

  /** Poses natives Photoroom Virtual Model ; "" = laissée libre. */
  export type PhotoroomPose =
    | ""
    | "random"
    | "standing"
    | "34turn"
    | "powerstance"
    | "walkingforward"
    | "handinpocket"
    | "crossedarms"
    | "back"
    | "overtheshoulder"
    | "seated"
    | "adjustingclothing"
    | "playfulspin"

  export type GenerationConfig = {
    engine: GenerationEngine
    framing: "full_body" | "cropped_head"
    scene: "studio" | "lifestyle"
    /** Orientation du mannequin (FASHN) ; "" = laissée libre (défaut). */
    pose: GenerationPose
    /** Pose native Photoroom ; "" = laissée libre. */
    photoroomPose: PhotoroomPose
    /** Preset mannequin Photoroom ; "" = choix libre du modèle. */
    modelPreset: ModelPreset | ""
    /** Preset décor Photoroom ; "" = selon l'ambiance ci-dessus. */
    scenePreset: ScenePreset | ""
    instructions: string
  }

  // Presets Photoroom, libellés FR (valeur API -> libellé).
  export const MODEL_PRESETS = [
    ["avery", "Avery"],
    ["sam", "Sam"],
    ["taylor", "Taylor"],
    ["kendall", "Kendall"],
    ["jordan", "Jordan"],
    ["casey", "Casey"],
    ["maya", "Maya"],
    ["reece", "Reece"],
    ["lena", "Lena"],
    ["julia", "Julia"],
    ["jackson", "Jackson"],
    ["sophia", "Sophia"],
    ["emma", "Emma"],
    ["ava", "Ava"],
    ["zoe", "Zoé"],
    ["fiona", "Fiona"],
  ] as const
  export type ModelPreset = (typeof MODEL_PRESETS)[number][0]
  export const SCENE_PRESETS = [
    ["studio", "Studio"],
    ["coloredstudio", "Studio coloré"],
    ["concretestudio", "Studio béton"],
    ["street", "Rue"],
    ["bedroom", "Chambre"],
    ["sunset", "Coucher de soleil"],
    ["factory", "Usine"],
    ["beach", "Plage"],
    ["tropical", "Tropical"],
    ["library", "Bibliothèque"],
    ["forest", "Forêt"],
    ["businessdistrict", "Quartier d'affaires"],
    ["countryside", "Campagne"],
    ["flowers", "Fleurs"],
    ["goldenlight", "Lumière dorée"],
    ["mountain", "Montagne"],
    ["pool", "Piscine"],
    ["latincity", "Ville latine"],
    ["cafe", "Café"],
    ["asiancity", "Ville asiatique"],
    ["nightlights", "Lumières nocturnes"],
    ["desert", "Désert"],
    ["random", "Aléatoire"],
  ] as const
  export type ScenePreset = (typeof SCENE_PRESETS)[number][0]
  export const PHOTOROOM_POSES: [PhotoroomPose, string][] = [
    ["standing", "Debout"],
    ["34turn", "Trois-quarts"],
    ["powerstance", "Pose affirmée"],
    ["walkingforward", "En marche"],
    ["handinpocket", "Main dans la poche"],
    ["crossedarms", "Bras croisés"],
    ["back", "De dos"],
    ["overtheshoulder", "Par-dessus l'épaule"],
    ["seated", "Assis·e"],
    ["adjustingclothing", "Ajuste le vêtement"],
    ["playfulspin", "Mouvement tournoyant"],
    ["random", "Aléatoire"],
  ]
</script>

<script lang="ts">
  import { Label } from "@/lib/components/ui/label"
  import { Select } from "@/lib/components/ui/select"

  let {
    config = $bindable(),
    disabled = false,
    idPrefix = "gen",
    showEngine = false,
  }: {
    config: GenerationConfig
    disabled?: boolean
    idPrefix?: string
    /** Affiche le sélecteur de moteur + les presets Photoroom. */
    showEngine?: boolean
  } = $props()

  const isPhotoroom = $derived(showEngine && config.engine === "photoroom")
</script>

<div class="flex flex-col gap-3">
  {#if showEngine}
    <div class="flex flex-col gap-1.5">
      <Label for="{idPrefix}-engine">Moteur de génération</Label>
      <Select id="{idPrefix}-engine" {disabled} bind:value={config.engine}>
        <option value="fashn">FASHN — rendu photoréaliste</option>
        <option value="photoroom">Photoroom — mannequin virtuel</option>
      </Select>
    </div>
  {/if}
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
    {#if isPhotoroom}
      <!-- Moteur Photoroom : presets natifs (mannequin, décor, pose) — le
           select de pose FASHN est remplacé par les poses Photoroom. -->
      <div class="flex flex-col gap-1.5">
        <Label for="{idPrefix}-model-preset">Mannequin (optionnel)</Label>
        <Select
          id="{idPrefix}-model-preset"
          {disabled}
          bind:value={config.modelPreset}
        >
          <option value="">Choix libre</option>
          {#each MODEL_PRESETS as [value, label] (value)}
            <option {value}>{label}</option>
          {/each}
        </Select>
      </div>
      <div class="flex flex-col gap-1.5">
        <Label for="{idPrefix}-scene-preset">Décor (optionnel)</Label>
        <Select
          id="{idPrefix}-scene-preset"
          {disabled}
          bind:value={config.scenePreset}
        >
          <option value="">Selon l'ambiance</option>
          {#each SCENE_PRESETS as [value, label] (value)}
            <option {value}>{label}</option>
          {/each}
        </Select>
      </div>
      <div class="flex flex-col gap-1.5">
        <Label for="{idPrefix}-photoroom-pose">Pose (optionnel)</Label>
        <Select
          id="{idPrefix}-photoroom-pose"
          {disabled}
          bind:value={config.photoroomPose}
        >
          <option value="">Laissée libre</option>
          {#each PHOTOROOM_POSES as [value, label] (value)}
            <option {value}>{label}</option>
          {/each}
        </Select>
      </div>
    {:else}
      <div class="flex flex-col gap-1.5">
        <Label for="{idPrefix}-pose">Orientation du mannequin (optionnel)</Label>
        <Select id="{idPrefix}-pose" {disabled} bind:value={config.pose}>
          <option value="">Laissée libre</option>
          <option value="face">De face</option>
          <option value="back">De dos</option>
          <option value="profile_left">Profil gauche</option>
          <option value="profile_right">Profil droit</option>
          <option value="three_quarter_left">3/4 face gauche</option>
          <option value="three_quarter_right">3/4 face droite</option>
        </Select>
      </div>
    {/if}
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
