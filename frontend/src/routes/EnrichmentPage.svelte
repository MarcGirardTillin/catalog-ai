<script lang="ts">
  // Workspace Enrichissement : la bibliothèque d'instructions, le contexte
  // boutique et le modèle de titre sortent des Paramètres pour devenir une
  // section à part entière (comme les Profils d'import).
  import { createQuery, useQueryClient } from "@tanstack/svelte-query"
  import { toast } from "svelte-sonner"

  import {
    catalogGetFilters,
    catalogSetCategoryDefaultWeight,
    settingsReadAccountSettings,
  } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { Label } from "@/lib/components/ui/label"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import { TabBar } from "@/lib/components/ui/tabs"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import InstructionLibrary from "@/lib/components/enrichment/InstructionLibrary.svelte"
  import TitleTemplateBuilder, {
    parseTemplate,
  } from "@/lib/components/enrichment/TitleTemplateBuilder.svelte"
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
  const TABS = [
    { key: "instructions", label: "Instructions" },
    { key: "context", label: "Contexte boutique" },
    { key: "title", label: "Modèle de titre" },
    { key: "imaging", label: "Imagerie" },
    { key: "weights", label: "Poids par défaut" },
  ] as const
  type TabKey = (typeof TABS)[number]["key"]
  let tab = $state<TabKey>("instructions")

  // --- Défauts d'enrichissement du compte (un seul objet AccountSettings ;
  // la sauvegarde préserve les champs gérés ailleurs : notifications,
  // coefficient de facturation…). ---
  let accountLoaded = $state(false)
  let savingAccount = $state(false)
  let editorialInstructions = $state("")
  let clientContext = $state("")
  let metaMaxLength = $state(160)

  // App default is {title}; the builder starts there.
  let templateTokens = $state<string[]>(["title"])
  let templateSeparator = $state(" ")
  let titleCase = $state<"none" | "upper" | "capitalize" | "title">("none")

  const titleTemplate = $derived(
    templateTokens.map((key) => `{${key}}`).join(templateSeparator),
  )

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
    instructions: "",
  })

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
    if (data.title_template) {
      const parsed = parseTemplate(data.title_template)
      if (parsed) {
        templateTokens = parsed.tokens
        templateSeparator = parsed.separator
      }
    }
    const loadedCase = (data as { title_case?: string }).title_case
    if (
      loadedCase === "upper" ||
      loadedCase === "capitalize" ||
      loadedCase === "title"
    ) {
      titleCase = loadedCase
    }
    editorialInstructions = data.editorial_instructions ?? ""
    clientContext = data.client_context ?? ""
    metaMaxLength = data.meta_max_length ?? 160
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
      instructions: data.imaging_generation_instructions ?? "",
    }
    accountLoaded = true
  })

  // --- Poids par défaut par catégorie (champ default_weight_kg de la table
  // catégorie Xano, éditable ici — « comme la marque », décision Marc). ---
  type CategoryWeightRow = { id: number; title: string; value: string }
  let categoryWeights = $state<CategoryWeightRow[]>([])
  let categoryWeightsLoaded = $state(false)
  let savingWeights = $state(false)
  const initialWeights = new Map<number, string>()

  $effect(() => {
    if (categoryWeightsLoaded) return
    catalogGetFilters().then(({ data }) => {
      if (!data) return
      categoryWeights = (data.categories ?? []).map((c) => ({
        id: c.id,
        title: c.title,
        value:
          c.default_weight_kg && c.default_weight_kg > 0
            ? String(c.default_weight_kg)
            : "",
      }))
      for (const row of categoryWeights) initialWeights.set(row.id, row.value)
      categoryWeightsLoaded = true
    })
  })

  async function saveCategoryWeights() {
    if (savingWeights) return
    savingWeights = true
    let saved = 0
    let failed = 0
    for (const row of categoryWeights) {
      if ((initialWeights.get(row.id) ?? "") === row.value) continue
      const weight = Number(row.value.trim().replace(",", "."))
      const { error } = await catalogSetCategoryDefaultWeight({
        path: { category_id: row.id },
        body: {
          default_weight_kg:
            row.value.trim() === "" || !Number.isFinite(weight) ? 0 : weight,
        },
      })
      if (error) failed += 1
      else {
        saved += 1
        initialWeights.set(row.id, row.value)
      }
    }
    savingWeights = false
    if (failed > 0) toast.error(`${failed} catégorie(s) non enregistrée(s).`)
    else if (saved > 0) toast.success("Poids par défaut enregistrés")
  }

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
      title_template: templateTokens.length > 0 ? titleTemplate : null,
      title_case: titleCase,
      editorial_instructions: editorialInstructions.trim() || null,
      client_context: clientContext.trim() || null,
      meta_max_length: metaMax,
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
    })
    savingAccount = false
    if (!ok) {
      toast.error("Enregistrement impossible.")
      return
    }
    queryClient.invalidateQueries({ queryKey: ["settings", "account"] })
    toast.success("Réglages d'enrichissement enregistrés")
  }
</script>

<!-- Bouton Enregistrer commun aux trois onglets (le PUT envoie l'ensemble
     des défauts d'enrichissement, quel que soit l'onglet actif). -->
{#snippet saveAccountRow()}
  <div class="flex justify-end">
    <Button disabled={!accountLoaded || savingAccount} onclick={saveAccount}>
      {savingAccount ? "Enregistrement…" : "Enregistrer"}
    </Button>
  </div>
{/snippet}

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Réglages d'enrichissement" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <h1 class="font-title text-lg font-bold">Réglages d'enrichissement</h1>

        <TabBar tabs={TABS} bind:value={tab} label="Sections de l'enrichissement" />

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

          {@render saveAccountRow()}
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
              {/if}
            </CardContent>
          </Card>

          {@render saveAccountRow()}
        </div>

        <!-- Onglet Modèle de titre (tokens + séparateur) -->
        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "title"}>
          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">Modèle de titre</CardTitle>
              <CardDescription class="text-muted-foreground text-xs">
                Structure des titres générés pour les nouveaux jobs.
              </CardDescription>
            </CardHeader>
            <CardContent class="flex flex-col gap-4">
              {#if !accountLoaded}
                <Skeleton class="h-9 w-full" />
                <Skeleton class="h-9 w-full" />
              {:else}
                <TitleTemplateBuilder
                  bind:tokens={templateTokens}
                  bind:separator={templateSeparator}
                  bind:titleCase
                />
              {/if}
            </CardContent>
          </Card>

          {@render saveAccountRow()}
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

          {@render saveAccountRow()}
        </div>

        <!-- Onglet Poids par défaut (par catégorie, stocké dans Tillin) -->
        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "weights"}>
          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">
                Poids par défaut par catégorie
              </CardTitle>
              <CardDescription class="text-muted-foreground text-xs">
                Appliqué quand ni la page de la marque ni le fichier
                fournisseur ne donnent de poids (enrichissements et imports).
                Stocké dans la catégorie Tillin — vide = pas de poids par
                défaut.
              </CardDescription>
            </CardHeader>
            <CardContent class="flex flex-col gap-3">
              {#if !categoryWeightsLoaded}
                <Skeleton class="h-24 w-full" />
              {:else if categoryWeights.length === 0}
                <p class="text-muted-foreground text-xs italic">
                  Aucune catégorie dans le référentiel Tillin.
                </p>
              {:else}
                <div class="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
                  {#each categoryWeights as row (row.id)}
                    <label
                      class="flex items-center justify-between gap-2 text-xs"
                    >
                      <span class="min-w-0 truncate" title={row.title}>
                        {row.title}
                      </span>
                      <span class="flex shrink-0 items-center gap-1">
                        <input
                          type="text"
                          inputmode="decimal"
                          placeholder="—"
                          class="border-input bg-card h-7 w-16 rounded-md border px-2 text-right font-mono text-xs tabular-nums"
                          bind:value={row.value}
                        />
                        <span class="text-muted-foreground">kg</span>
                      </span>
                    </label>
                  {/each}
                </div>
                <div class="flex justify-end">
                  <Button size="sm" disabled={savingWeights} onclick={saveCategoryWeights}>
                    {savingWeights ? "Enregistrement…" : "Enregistrer les poids"}
                  </Button>
                </div>
              {/if}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
