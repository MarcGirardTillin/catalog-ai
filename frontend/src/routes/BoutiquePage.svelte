<script lang="ts">
  // Réglages boutique : les conventions transverses aux deux pipelines
  // (import ET enrichissement) sortent des réglages d'enrichissement —
  // modèle de titre, sites des marques, poids par défaut par catégorie.
  import { createQuery, useQueryClient } from "@tanstack/svelte-query"
  import { toast } from "svelte-sonner"

  import {
    catalogGetFilters,
    catalogSetCategoryDefaultWeight,
    settingsReadAccountSettings,
    statsDashboardStats,
  } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import { TabBar } from "@/lib/components/ui/tabs"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import BrandWebsites from "@/lib/components/settings/BrandWebsites.svelte"
  import FaceLibrary from "@/lib/components/settings/FaceLibrary.svelte"
  import TitleTemplateBuilder, {
    parseTemplate,
  } from "@/lib/components/enrichment/TitleTemplateBuilder.svelte"
  import { saveAccountSettingsPartial } from "@/lib/accountSettings.svelte"

  let { appName }: { appName: string } = $props()

  // Onglets (état local ; les panneaux restent montés pour conserver les
  // saisies en cours — même pattern que les autres pages de réglages).
  // Chaque onglet n'a de sens que si son module est souscrit : modèle de
  // titre et poids servent l'import ET l'enrichissement, les sites des
  // marques l'enrichissement (résolution de la page source), les visages le
  // studio (l'API /faces est d'ailleurs gardée côté serveur).
  const TABS = [
    { key: "title", label: "Modèle de titre" },
    { key: "brands", label: "Sites des marques" },
    { key: "weights", label: "Poids par défaut" },
    { key: "faces", label: "Visages mannequins" },
  ] as const
  type TabKey = (typeof TABS)[number]["key"]
  let tab = $state<TabKey>("title")

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
    const canImport = stats?.feature_import !== false
    const canEnrich = stats?.feature_enrich !== false
    const canStudio = stats?.feature_studio !== false
    const allowed: Record<TabKey, boolean> = {
      title: canImport || canEnrich,
      brands: canEnrich,
      weights: canImport || canEnrich,
      faces: canStudio,
    }
    return TABS.filter((t) => allowed[t.key])
  })
  // Si l'onglet actif disparaît (flags chargés après le rendu initial),
  // on retombe sur le premier onglet visible.
  $effect(() => {
    if (visibleTabs.length > 0 && !visibleTabs.some((t) => t.key === tab)) {
      tab = visibleTabs[0].key
    }
  })

  // --- Modèle de titre du compte (utilisé par l'enrichissement ET par les
  // imports quand le profil active « appliquer le modèle de titre »). ---
  let accountLoaded = $state(false)
  let savingTitle = $state(false)
  let templateTokens = $state<string[]>(["title"])
  let templateSeparator = $state(" ")
  let titleCase = $state<"none" | "upper" | "capitalize" | "title" | "sentence">(
    "none",
  )

  const titleTemplate = $derived(
    templateTokens.map((key) => `{${key}}`).join(templateSeparator),
  )

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
      toast.error("Impossible de charger les réglages.")
    }
  })

  // Les valeurs chargées sont copiées UNE FOIS dans l'état local : un
  // refetch ne doit pas écraser une saisie en cours.
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
      loadedCase === "title" ||
      loadedCase === "sentence"
    ) {
      titleCase = loadedCase
    }
    accountLoaded = true
    savedTitleSig = titleSignature()
  })

  async function saveTitleTemplate() {
    if (savingTitle) return
    savingTitle = true
    const ok = await saveAccountSettingsPartial({
      title_template: templateTokens.length > 0 ? titleTemplate : null,
      title_case: titleCase,
    })
    savingTitle = false
    if (!ok) {
      toast.error("Enregistrement impossible.")
      return
    }
    queryClient.invalidateQueries({ queryKey: ["settings", "account"] })
    savedTitleSig = titleSignature()
    toast.success("Modèle de titre enregistré")
  }

  // --- Poids par défaut par catégorie (champ default_weight_kg de la table
  // catégorie Xano — « comme la marque », décision Marc). ---
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
      savedWeightsSig = weightsSignature()
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
    // La signature « enregistrée » reflète ce qui a RÉELLEMENT été écrit
    // (échec partiel = la barre reste visible pour les lignes restantes).
    savedWeightsSig = JSON.stringify(
      categoryWeights.map((row) => [row.id, initialWeights.get(row.id) ?? ""]),
    )
    if (failed > 0) toast.error(`${failed} catégorie(s) non enregistrée(s).`)
    else if (saved > 0) toast.success("Poids par défaut enregistrés")
  }

  // --- Barre « modifications non enregistrées » (même pattern que les
  // Réglages d'enrichissement, généralisé sur demande Marc 2026-08-22). ---
  function titleSignature(): string {
    return JSON.stringify({ templateTokens, templateSeparator, titleCase })
  }
  function weightsSignature(): string {
    return JSON.stringify(categoryWeights.map((row) => [row.id, row.value]))
  }
  let savedTitleSig = $state("")
  let savedWeightsSig = $state("")
  const dirty = $derived(
    (accountLoaded && titleSignature() !== savedTitleSig) ||
      (categoryWeightsLoaded && weightsSignature() !== savedWeightsSig),
  )
  const savingAny = $derived(savingTitle || savingWeights)

  async function saveDirty() {
    if (accountLoaded && titleSignature() !== savedTitleSig) {
      await saveTitleTemplate()
    }
    if (categoryWeightsLoaded && weightsSignature() !== savedWeightsSig) {
      await saveCategoryWeights()
    }
  }

  function onBeforeUnload(event: BeforeUnloadEvent) {
    if (dirty) event.preventDefault()
  }
</script>

<svelte:window onbeforeunload={onBeforeUnload} />

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Réglages" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <h1 class="font-title text-lg font-bold">Réglages</h1>
        <p class="text-muted-foreground text-sm">
          Conventions de la boutique, partagées par les imports et les
          enrichissements.
        </p>

        <TabBar tabs={visibleTabs} bind:value={tab} label="Sections des réglages" />

        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "title"}>
        <Card size="sm">
          <CardHeader>
            <CardTitle class="font-title text-sm">Modèle de titre</CardTitle>
            <CardDescription class="text-muted-foreground text-xs">
              Structure des titres générés — appliquée aux enrichissements et,
              quand le profil l'active, dès l'import.
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
        </div>

        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "brands"}>
          <BrandWebsites />
        </div>

        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "faces"}>
          <FaceLibrary />
        </div>

        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "weights"}>
        <Card size="sm">
          <CardHeader>
            <CardTitle class="font-title text-sm">
              Poids par défaut par catégorie
            </CardTitle>
            <CardDescription class="text-muted-foreground text-xs">
              Appliqué quand ni la page de la marque ni le fichier fournisseur
              ne donnent de poids (enrichissements et imports). Stocké dans la
              catégorie Tillin — vide = pas de poids par défaut.
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
                  <label class="flex items-center justify-between gap-2 text-xs">
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
            {/if}
          </CardContent>
        </Card>
        </div>

        {#if dirty}
          <div class="h-14" aria-hidden="true"></div>
        {/if}
      </div>

      <!-- Barre collante « modifications non enregistrées » : enregistre ce
           qui a changé (modèle de titre et/ou poids), quel que soit l'onglet. -->
      {#if dirty}
        <div class="border-border bg-card fixed inset-x-0 bottom-0 z-10 border-t p-3 sm:left-60">
          <div class="mx-auto flex max-w-4xl items-center justify-between gap-3">
            <p class="text-muted-foreground text-xs">
              Modifications non enregistrées.
            </p>
            <Button size="sm" disabled={savingAny} onclick={saveDirty}>
              {savingAny ? "Enregistrement…" : "Enregistrer"}
            </Button>
          </div>
        </div>
      {/if}
    </AppShell>
  {/snippet}
</RequireAuth>
