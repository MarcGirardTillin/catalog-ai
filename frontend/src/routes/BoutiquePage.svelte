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
  import TitleTemplateBuilder, {
    parseTemplate,
  } from "@/lib/components/enrichment/TitleTemplateBuilder.svelte"
  import { saveAccountSettingsPartial } from "@/lib/accountSettings.svelte"

  let { appName }: { appName: string } = $props()

  // Onglets (état local ; les panneaux restent montés pour conserver les
  // saisies en cours — même pattern que les autres pages de réglages).
  const TABS = [
    { key: "title", label: "Modèle de titre" },
    { key: "brands", label: "Sites des marques" },
    { key: "weights", label: "Poids par défaut" },
  ] as const
  type TabKey = (typeof TABS)[number]["key"]
  let tab = $state<TabKey>("title")

  // --- Modèle de titre du compte (utilisé par l'enrichissement ET par les
  // imports quand le profil active « appliquer le modèle de titre »). ---
  let accountLoaded = $state(false)
  let savingTitle = $state(false)
  let templateTokens = $state<string[]>(["title"])
  let templateSeparator = $state(" ")
  let titleCase = $state<"none" | "upper" | "capitalize" | "title">("none")

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
      loadedCase === "title"
    ) {
      titleCase = loadedCase
    }
    accountLoaded = true
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
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Réglages" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <h1 class="font-title text-lg font-bold">Réglages</h1>
        <p class="text-muted-foreground text-sm">
          Conventions de la boutique, partagées par les imports et les
          enrichissements.
        </p>

        <TabBar tabs={TABS} bind:value={tab} label="Sections des réglages" />

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
              <div class="flex justify-end">
                <Button size="sm" disabled={savingTitle} onclick={saveTitleTemplate}>
                  {savingTitle ? "Enregistrement…" : "Enregistrer"}
                </Button>
              </div>
            {/if}
          </CardContent>
        </Card>
        </div>

        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "brands"}>
          <BrandWebsites />
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
