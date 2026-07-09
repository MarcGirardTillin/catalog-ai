<script lang="ts">
  // Workspace Enrichissement : la bibliothèque d'instructions, le contexte
  // boutique et le modèle de titre sortent des Paramètres pour devenir une
  // section à part entière (comme les Profils d'import).
  import { toast } from "svelte-sonner"

  import { settingsReadAccountSettings } from "@/client"
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
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import InstructionLibrary from "@/lib/components/enrichment/InstructionLibrary.svelte"
  import TitleTemplateBuilder, {
    parseTemplate,
  } from "@/lib/components/enrichment/TitleTemplateBuilder.svelte"
  import { saveAccountSettingsPartial } from "@/lib/accountSettings.svelte"

  let { appName }: { appName: string } = $props()

  // --- Onglets (état local ; les panneaux restent montés pour conserver
  // les saisies en cours quand on change d'onglet — même pattern que les
  // Paramètres). ---
  const TABS = [
    { key: "instructions", label: "Instructions" },
    { key: "context", label: "Contexte boutique" },
    { key: "title", label: "Modèle de titre" },
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
  let titleCase = $state<"none" | "upper" | "capitalize">("none")

  const titleTemplate = $derived(
    templateTokens.map((key) => `{${key}}`).join(templateSeparator),
  )

  $effect(() => {
    settingsReadAccountSettings().then(({ data, error }) => {
      if (error || !data) {
        toast.error("Impossible de charger les réglages d'enrichissement.")
        return
      }
      if (data.title_template) {
        const parsed = parseTemplate(data.title_template)
        if (parsed) {
          templateTokens = parsed.tokens
          templateSeparator = parsed.separator
        }
      }
      const loadedCase = (data as { title_case?: string }).title_case
      if (loadedCase === "upper" || loadedCase === "capitalize") {
        titleCase = loadedCase
      }
      editorialInstructions = data.editorial_instructions ?? ""
      clientContext = data.client_context ?? ""
      metaMaxLength = data.meta_max_length ?? 160
      accountLoaded = true
    })
  })

  async function saveAccount() {
    const metaMax = Number(metaMaxLength)
    if (!Number.isFinite(metaMax) || metaMax < 50 || metaMax > 320) {
      toast.error("La longueur max de la meta doit être entre 50 et 320.")
      return
    }
    savingAccount = true
    const ok = await saveAccountSettingsPartial({
      title_template: templateTokens.length > 0 ? titleTemplate : null,
      title_case: titleCase,
      editorial_instructions: editorialInstructions.trim() || null,
      client_context: clientContext.trim() || null,
      meta_max_length: metaMax,
    })
    savingAccount = false
    if (!ok) {
      toast.error("Enregistrement impossible.")
      return
    }
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
    <AppShell {appName} {user} breadcrumbs={[{ label: "Instructions" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <h1 class="font-title text-lg font-bold">Instructions</h1>

        <!-- Barre d'onglets sobre (pas de composant tabs dans ui/). -->
        <div
          class="border-border flex gap-4 border-b"
          role="tablist"
          aria-label="Sections de l'enrichissement"
        >
          {#each TABS as t (t.key)}
            <button
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              class="-mb-px cursor-pointer border-b-2 px-1 pb-2 text-sm font-medium transition-colors {tab ===
              t.key
                ? 'border-primary text-foreground'
                : 'text-muted-foreground hover:text-foreground border-transparent'}"
              onclick={() => (tab = t.key)}
            >
              {t.label}
            </button>
          {/each}
        </div>

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
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
