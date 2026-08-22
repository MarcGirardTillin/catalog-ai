<script lang="ts">
  // Workspace Enrichissement : la bibliothèque d'instructions, le contexte
  // boutique et le modèle de titre sortent des Paramètres pour devenir une
  // section à part entière (comme les Profils d'import).
  import { createQuery, useQueryClient } from "@tanstack/svelte-query"
  import { navigate } from "svelte5-router"
  import { toast } from "svelte-sonner"

  import { settingsReadAccountSettings, statsDashboardStats } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { Label } from "@/lib/components/ui/label"
  import { Select } from "@/lib/components/ui/select"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import { TabBar } from "@/lib/components/ui/tabs"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import InstructionLibrary from "@/lib/components/enrichment/InstructionLibrary.svelte"
  import ImageTitleTemplateBuilder, {
    buildImageTemplate,
    parseImageTemplate,
    type TemplatePart,
  } from "@/lib/components/imaging/ImageTitleTemplateBuilder.svelte"
  import GenerationOptions, {
    type GenerationConfig,
  } from "@/lib/components/imaging/GenerationOptions.svelte"
  import ProcessingOptions, {
    type StudioOptions,
  } from "@/lib/components/imaging/ProcessingOptions.svelte"
  import { saveAccountSettingsPartial } from "@/lib/accountSettings.svelte"

  let { appName }: { appName: string } = $props()

  // --- Onglets (état local ; les panneaux restent montés pour conserver
  // les saisies en cours quand on change d'onglet — même pattern que les
  // Paramètres). ---
  // NOTE : le modèle de titre et les poids par défaut par catégorie ont
  // déménagé dans les Réglages boutique (/boutique) — ils servent aux deux
  // pipelines, pas seulement à l'enrichissement (demande Marc 2026-07-29).
  const TABS = [
    { key: "instructions", label: "Instructions" },
    { key: "context", label: "Contexte boutique" },
    { key: "imaging", label: "Imagerie" },
  ] as const
  type TabKey = (typeof TABS)[number]["key"]
  let tab = $state<TabKey>("instructions")

  // Modules souscrits : Instructions et Contexte relèvent de
  // l'enrichissement, Imagerie du studio. La nav masque déjà la page quand
  // l'enrichissement est coupé, mais elle reste accessible par URL directe.
  const featureStatsQuery = createQuery(() => ({
    queryKey: ["stats", "dashboard"],
    queryFn: async () => {
      const { data, error } = await statsDashboardStats()
      if (error || !data) throw new Error("stats_load_failed")
      return data
    },
  }))
  const visibleTabs = $derived.by(() => {
    const stats = featureStatsQuery.data
    const canEnrich = stats?.feature_enrich !== false
    const canStudio = stats?.feature_studio !== false
    const allowed: Record<TabKey, boolean> = {
      instructions: canEnrich,
      context: canEnrich,
      imaging: canStudio,
    }
    return TABS.filter((t) => allowed[t.key])
  })
  $effect(() => {
    if (visibleTabs.length > 0 && !visibleTabs.some((t) => t.key === tab)) {
      tab = visibleTabs[0].key
    }
  })

  // --- Défauts d'enrichissement du compte (un seul objet AccountSettings ;
  // la sauvegarde préserve les champs gérés ailleurs : notifications,
  // coefficient de facturation…). ---
  let accountLoaded = $state(false)
  let savingAccount = $state(false)
  let editorialInstructions = $state("")
  let clientContext = $state("")
  let metaMaxLength = $state(160)
  // Langue des contenus générés + noms de produits gardés dans leur langue
  // (Marc 2026-08-22).
  let contentLanguage = $state<"fr" | "en">("fr")
  let keepProductNames = $state(true)

  // --- Imagerie : défauts de normalisation + modèle de nom des images ---
  let imagingOptions = $state<StudioOptions>({
    remove_bg: true,
    bg_color: "FFFFFF",
    ratio: "4:5",
    center: true,
    margin_percent: 0,
    format: "webp",
    quality: 80,
    max_kb: 300,
  })
  let imageTemplateParts = $state<TemplatePart[]>([])
  let generationConfig = $state<GenerationConfig>({
    engine: "fashn",
    framing: "full_body",
    scene: "studio",
    pose: "",
    photoroomPose: "",
    modelPreset: "",
    scenePreset: "",
    gender: "auto",
    instructions: "",
  })
  // Instructions de mise à plat par défaut (pré-remplies dans le studio).
  let flatInstructions = $state("")

  const imageTitleTemplate = $derived(buildImageTemplate(imageTemplateParts))

  // Lecture des réglages du compte (cache TanStack). Les valeurs chargées
  // sont copiées UNE FOIS dans les champs éditables locaux ci-dessus : un
  // refetch (invalidation, focus) ne doit pas écraser une saisie en cours.
  const queryClient = useQueryClient()
  const settingsQuery = createQuery(() => ({
    queryKey: ["settings", "account"],
    queryFn: async () => {
      const { data, error } = await settingsReadAccountSettings()
      if (error || !data) throw new Error("settings_load_failed")
      return data
    },
  }))

  $effect(() => {
    if (settingsQuery.isError && !accountLoaded) {
      toast.error("Impossible de charger les réglages d'enrichissement.")
    }
  })

  $effect(() => {
    const data = settingsQuery.data
    if (!data || accountLoaded) return
    editorialInstructions = data.editorial_instructions ?? ""
    clientContext = data.client_context ?? ""
    metaMaxLength = data.meta_max_length ?? 160
    contentLanguage = data.content_language ?? "fr"
    keepProductNames = data.keep_product_names ?? true
    imagingOptions = {
      remove_bg: data.imaging_remove_bg ?? true,
      bg_color: data.imaging_bg_color ?? "FFFFFF",
      ratio: data.imaging_ratio ?? "4:5",
      center: data.imaging_center ?? true,
      margin_percent: data.imaging_margin_percent ?? 0,
      format: data.imaging_format ?? "webp",
      quality: data.imaging_quality ?? 80,
      max_kb: data.imaging_max_kb ?? 300,
    }
    imageTemplateParts = data.image_title_template
      ? parseImageTemplate(data.image_title_template)
      : []
    generationConfig = {
      engine: data.imaging_generation_engine ?? "fashn",
      framing: data.imaging_generation_framing ?? "full_body",
      scene: data.imaging_generation_scene ?? "studio",
      pose: data.imaging_generation_pose ?? "",
      photoroomPose: "",
      modelPreset: data.imaging_generation_model_preset ?? "",
      scenePreset: data.imaging_generation_scene_preset ?? "",
      gender: data.imaging_generation_gender ?? "auto",
      instructions: data.imaging_generation_instructions ?? "",
    }
    flatInstructions = data.imaging_flat_instructions ?? ""
    accountLoaded = true
    savedSignature = settingsSignature()
  })

  async function saveAccount() {
    const metaMax = Number(metaMaxLength)
    if (!Number.isFinite(metaMax) || metaMax < 50 || metaMax > 320) {
      toast.error("La longueur max de la meta doit être entre 50 et 320.")
      return
    }
    const quality = Math.round(Number(imagingOptions.quality))
    const maxKb = Math.round(Number(imagingOptions.max_kb))
    if (!Number.isFinite(quality) || quality < 1 || quality > 100) {
      toast.error("La qualité d'image doit être entre 1 et 100.")
      return
    }
    if (!Number.isFinite(maxKb) || maxKb < 1 || maxKb > 5000) {
      toast.error("Le poids max doit être entre 1 et 5000 Ko.")
      return
    }
    const marginPercent = Number(imagingOptions.margin_percent)
    if (!Number.isFinite(marginPercent) || marginPercent < 0 || marginPercent > 45) {
      toast.error("La marge doit être entre 0 et 45 %.")
      return
    }
    if (!/^#?[0-9a-fA-F]{6}$/.test(imagingOptions.bg_color)) {
      toast.error("La couleur de fond doit être un code hex (ex. FFFFFF).")
      return
    }
    savingAccount = true
    const ok = await saveAccountSettingsPartial({
      editorial_instructions: editorialInstructions.trim() || null,
      client_context: clientContext.trim() || null,
      meta_max_length: metaMax,
      content_language: contentLanguage,
      keep_product_names: keepProductNames,
      imaging_remove_bg: imagingOptions.remove_bg,
      imaging_bg_color: imagingOptions.bg_color.replace(/^#/, "").toUpperCase(),
      imaging_ratio: imagingOptions.ratio,
      imaging_center: imagingOptions.center,
      imaging_margin_percent: marginPercent,
      imaging_format: imagingOptions.format,
      imaging_quality: quality,
      imaging_max_kb: maxKb,
      image_title_template:
        imageTemplateParts.length > 0 ? imageTitleTemplate : null,
      imaging_generation_framing: generationConfig.framing,
      imaging_generation_scene: generationConfig.scene,
      imaging_generation_pose: generationConfig.pose || null,
      imaging_generation_instructions:
        generationConfig.instructions.trim() || null,
      imaging_generation_engine: generationConfig.engine,
      imaging_generation_model_preset: generationConfig.modelPreset || null,
      imaging_generation_scene_preset: generationConfig.scenePreset || null,
      imaging_generation_gender: generationConfig.gender,
      imaging_flat_instructions: flatInstructions.trim(),
    })
    savingAccount = false
    if (!ok) {
      toast.error("Enregistrement impossible.")
      return
    }
    queryClient.invalidateQueries({ queryKey: ["settings", "account"] })
    savedSignature = settingsSignature()
    toast.success("Réglages d'enrichissement enregistrés")
  }

  // --- État « modifications non enregistrées » (feedback Marc 2026-08-22 :
  // le bouton en bas de page n'est pas visible et on peut quitter sans
  // enregistrer). Signature = tous les champs éditables ; la barre collante
  // n'apparaît que quand elle diverge de la dernière sauvegarde. ---
  function settingsSignature(): string {
    return JSON.stringify({
      editorialInstructions,
      clientContext,
      metaMaxLength,
      contentLanguage,
      keepProductNames,
      imagingOptions,
      imageTemplateParts,
      generationConfig,
      flatInstructions,
    })
  }
  let savedSignature = $state("")
  const dirty = $derived(accountLoaded && settingsSignature() !== savedSignature)

  function onBeforeUnload(event: BeforeUnloadEvent) {
    if (dirty) event.preventDefault()
  }
</script>

<svelte:window onbeforeunload={onBeforeUnload} />

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Réglages d'enrichissement" }]}>
      {#if visibleTabs.length === 0}
        <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
          <Card>
            <CardContent class="flex flex-col items-start gap-3 py-6">
              <p class="text-sm">
                Le module d'enrichissement n'est pas activé pour votre compte.
              </p>
              <Button variant="secondary" onclick={() => navigate("/")}>
                Retour au tableau de bord
              </Button>
            </CardContent>
          </Card>
        </div>
      {:else}
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <h1 class="font-title text-lg font-bold">Réglages d'enrichissement</h1>

        <TabBar tabs={visibleTabs} bind:value={tab} label="Sections de l'enrichissement" />

        <!-- Onglet Instructions (bibliothèque + défaut du compte) -->
        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "instructions"}>
          <InstructionLibrary />

          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">
                Instructions éditoriales par défaut
              </CardTitle>
              <CardDescription class="text-muted-foreground text-xs">
                Appliquées aux nouveaux jobs ; chaque job peut les surcharger.
              </CardDescription>
            </CardHeader>
            <CardContent class="flex flex-col gap-4">
              {#if !accountLoaded}
                <Skeleton class="h-20 w-full" />
              {:else}
                <div class="flex flex-col gap-1.5">
                  <Label for="editorial-instructions">
                    Instructions éditoriales par défaut
                  </Label>
                  <textarea
                    id="editorial-instructions"
                    rows="3"
                    class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content max-h-60 w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                    placeholder="Ex. Ton chaleureux, vouvoiement, mettre en avant la durabilité…"
                    bind:value={editorialInstructions}
                  ></textarea>
                </div>
              {/if}
            </CardContent>
          </Card>

        </div>

        <!-- Onglet Contexte boutique (markdown injecté dans chaque génération) -->
        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "context"}>
          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">Contexte boutique</CardTitle>
              <CardDescription class="text-muted-foreground text-xs">
                Règles de la boutique injectées dans chaque génération.
              </CardDescription>
            </CardHeader>
            <CardContent class="flex flex-col gap-4">
              {#if !accountLoaded}
                <Skeleton class="h-24 w-full" />
                <Skeleton class="h-9 w-56" />
              {:else}
                <div class="flex flex-col gap-1.5">
                  <Label for="client-context">Contexte boutique</Label>
                  <textarea
                    id="client-context"
                    rows="4"
                    class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content max-h-80 min-h-24 w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                    placeholder="Règles de la boutique injectées dans chaque génération : positionnement, public cible, vocabulaire à privilégier ou à éviter… (markdown accepté)"
                    bind:value={clientContext}
                  ></textarea>
                  <p class="text-muted-foreground text-xs">
                    Ce texte (markdown) est ajouté au contexte de chaque génération.
                  </p>
                </div>
                <div class="flex flex-col gap-1.5 sm:max-w-56">
                  <Label for="meta-max">Longueur max de la meta description</Label>
                  <input
                    id="meta-max"
                    type="number"
                    min="50"
                    max="320"
                    class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                    bind:value={metaMaxLength}
                  />
                </div>
                <div class="flex flex-col gap-1.5 sm:max-w-56">
                  <Label for="content-language">Langue des contenus générés</Label>
                  <Select id="content-language" bind:value={contentLanguage}>
                    <option value="fr">Français</option>
                    <option value="en">Anglais</option>
                  </Select>
                </div>
                <label class="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    class="mt-0.5 size-4 shrink-0"
                    bind:checked={keepProductNames}
                  />
                  <span>
                    Conserver les noms de produits dans leur langue d'origine
                    <span class="text-muted-foreground block text-xs font-normal">
                      Un titre anglais cité dans une description reste en
                      anglais (« Stockholm BBQ Emb » n'est pas traduit).
                    </span>
                  </span>
                </label>
              {/if}
            </CardContent>
          </Card>

        </div>

        <!-- Onglet Imagerie (défauts de normalisation + nom des images) -->
        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "imaging"}>
          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">
                Normalisation des images
              </CardTitle>
              <CardDescription class="text-muted-foreground text-xs">
                Défauts appliqués à chaque traitement d'image (studio, panneau
                produit et enrichissements) ; ajustables au cas par cas dans le
                studio.
              </CardDescription>
            </CardHeader>
            <CardContent class="flex flex-col gap-4">
              {#if !accountLoaded}
                <Skeleton class="h-24 w-full" />
              {:else}
                <ProcessingOptions bind:options={imagingOptions} />
              {/if}
            </CardContent>
          </Card>

          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">
                Génération de visuels (porté mannequin)
              </CardTitle>
              <CardDescription class="text-muted-foreground text-xs">
                Instruction donnée au service de visuels pour chaque
                génération ; ajustable au cas par cas dans le studio.
              </CardDescription>
            </CardHeader>
            <CardContent class="flex flex-col gap-4">
              {#if !accountLoaded}
                <Skeleton class="h-24 w-full" />
              {:else}
                <GenerationOptions
                  bind:config={generationConfig}
                  idPrefix="settings-gen"
                  showEngine
                />
              {/if}
            </CardContent>
          </Card>

          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">Mise à plat</CardTitle>
              <CardDescription class="text-muted-foreground text-xs">
                Instructions par défaut du verbe « Mise à plat » — pré-remplies
                dans le studio à chaque lancement, ajustables au cas par cas.
              </CardDescription>
            </CardHeader>
            <CardContent class="flex flex-col gap-4">
              {#if !accountLoaded}
                <Skeleton class="h-16 w-full" />
              {:else}
                <textarea
                  id="settings-flat-instructions"
                  rows="3"
                  aria-label="Instructions de mise à plat par défaut"
                  class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content max-h-40 w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                  placeholder="Ex. enlève le cintre, mets les chaussettes à l'endroit, enlève l'étiquette produit…"
                  maxlength="500"
                  bind:value={flatInstructions}
                ></textarea>
              {/if}
            </CardContent>
          </Card>

          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">Nom des images</CardTitle>
              <CardDescription class="text-muted-foreground text-xs">
                Nom de fichier appliqué aux images enregistrées dans Tillin
                (studio et enrichissements) ; un nom saisi à la main dans le
                studio reste prioritaire.
              </CardDescription>
            </CardHeader>
            <CardContent class="flex flex-col gap-4">
              {#if !accountLoaded}
                <Skeleton class="h-16 w-full" />
              {:else}
                <ImageTitleTemplateBuilder bind:parts={imageTemplateParts} />
              {/if}
            </CardContent>
          </Card>

        </div>

        <!-- Réserve de place pour la barre collante quand elle est visible. -->
        {#if dirty}
          <div class="h-14" aria-hidden="true"></div>
        {/if}
      </div>

      <!-- Barre collante « modifications non enregistrées » : visible dès
           qu'un champ diverge de la dernière sauvegarde, quel que soit
           l'onglet ou la position de scroll (feedback Marc 2026-08-22). -->
      {#if dirty}
        <div class="border-border bg-card fixed inset-x-0 bottom-0 z-10 border-t p-3 sm:left-60">
          <div class="mx-auto flex max-w-4xl items-center justify-between gap-3">
            <p class="text-muted-foreground text-xs">
              Modifications non enregistrées.
            </p>
            <Button size="sm" disabled={savingAccount} onclick={saveAccount}>
              {savingAccount ? "Enregistrement…" : "Enregistrer"}
            </Button>
          </div>
        </div>
      {/if}
      {/if}
    </AppShell>
  {/snippet}
</RequireAuth>
