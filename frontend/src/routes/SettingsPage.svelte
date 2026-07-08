<script lang="ts">
  import { toast } from "svelte-sonner"

  import {
    authUpdatePassword,
    settingsReadAccountSettings,
    settingsReadConnectionStatus,
    settingsUpdateAccountSettings,
  } from "@/client"
  import type { ConnectionStatus } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Separator } from "@/lib/components/ui/separator"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import { prefs, savePreferences } from "@/lib/preferences.svelte"

  let { appName }: { appName: string } = $props()

  // --- Réglages de compte (Enrichissement + Notifications : un seul objet,
  // un seul bouton Enregistrer — le PUT envoie l'AccountSettings complet). ---
  let accountLoaded = $state(false)
  let savingAccount = $state(false)
  let editorialInstructions = $state("")
  let metaMaxLength = $state(160)
  let notifyOnJobDone = $state(false)
  let notifyEmail = $state("")

  // --- Constructeur de modèle de titre (tokens cliquables, pas de saisie
  // libre : évite les fautes de frappe dans les {tokens}). ---
  const TITLE_TOKENS = [
    { key: "title", label: "Titre" },
    { key: "brand", label: "Marque" },
    { key: "season", label: "Saison" },
    { key: "reference", label: "Référence" },
    { key: "color", label: "Couleur" },
    { key: "category", label: "Catégorie" },
    { key: "department", label: "Rayon" },
  ] as const

  const SEPARATORS = [
    { value: " ", label: "Espace" },
    { value: " - ", label: "Tiret (-)" },
    { value: " · ", label: "Point médian (·)" },
    { value: " | ", label: "Barre (|)" },
    { value: " / ", label: "Barre oblique (/)" },
  ]

  // Sample values for the live preview of the template.
  const TOKEN_SAMPLE: Record<string, string> = {
    title: "Polo rayé en coton bio",
    brand: "ARMEDANGELS",
    season: "H26",
    reference: "30008362",
    color: "Vert",
    category: "T-shirts",
    department: "Homme",
  }

  // App default is {title}; the builder starts there.
  let templateTokens = $state<string[]>(["title"])
  let templateSeparator = $state(" ")

  const titleTemplate = $derived(
    templateTokens.map((key) => `{${key}}`).join(templateSeparator),
  )
  const templatePreview = $derived(
    templateTokens.map((key) => TOKEN_SAMPLE[key] ?? "").join(templateSeparator),
  )
  const availableTokens = $derived(
    TITLE_TOKENS.filter((token) => !templateTokens.includes(token.key)),
  )

  function parseTemplate(template: string) {
    const keys = [...template.matchAll(/\{(\w+)\}/g)]
      .map((match) => match[1])
      .filter((key) => TITLE_TOKENS.some((token) => token.key === key))
    if (keys.length === 0) return
    templateTokens = keys
    // Infer the separator from the text between the first two tokens.
    const between = template.match(/\}([^{}]*)\{/)?.[1]
    if (between !== undefined && SEPARATORS.some((s) => s.value === between)) {
      templateSeparator = between
    }
  }

  function addToken(key: string) {
    if (!templateTokens.includes(key)) templateTokens = [...templateTokens, key]
  }

  function removeToken(key: string) {
    templateTokens = templateTokens.filter((k) => k !== key)
  }

  // --- Connexion Tillin (lecture seule) ---
  let connection = $state<ConnectionStatus | null>(null)

  // --- Changement de mot de passe ---
  let currentPassword = $state("")
  let newPassword = $state("")
  let confirmPassword = $state("")
  let passwordError = $state<string | null>(null)
  let changingPassword = $state(false)

  $effect(() => {
    settingsReadAccountSettings().then(({ data, error }) => {
      if (error || !data) {
        toast.error("Impossible de charger les réglages du compte.")
        return
      }
      if (data.title_template) parseTemplate(data.title_template)
      editorialInstructions = data.editorial_instructions ?? ""
      metaMaxLength = data.meta_max_length ?? 160
      notifyOnJobDone = data.notify_on_job_done ?? false
      notifyEmail = data.notify_email ?? ""
      accountLoaded = true
    })
    settingsReadConnectionStatus().then(({ data }) => {
      connection = data ?? null
    })
  })

  async function saveAccount() {
    const metaMax = Number(metaMaxLength)
    if (!Number.isFinite(metaMax) || metaMax < 50 || metaMax > 320) {
      toast.error("La longueur max de la meta doit être entre 50 et 320.")
      return
    }
    savingAccount = true
    const { error } = await settingsUpdateAccountSettings({
      body: {
        title_template: templateTokens.length > 0 ? titleTemplate : null,
        editorial_instructions: editorialInstructions.trim() || null,
        meta_max_length: metaMax,
        notify_on_job_done: notifyOnJobDone,
        notify_email: notifyEmail.trim() || null,
      },
    })
    savingAccount = false
    if (error) {
      toast.error("Enregistrement impossible.")
      return
    }
    toast.success("Réglages enregistrés")
  }

  async function updatePassword(event: SubmitEvent) {
    event.preventDefault()
    passwordError = null
    if (newPassword.length < 8) {
      passwordError = "Le nouveau mot de passe doit contenir au moins 8 caractères."
      return
    }
    if (newPassword !== confirmPassword) {
      passwordError = "La confirmation ne correspond pas au nouveau mot de passe."
      return
    }
    changingPassword = true
    const result = await authUpdatePassword({
      body: { current_password: currentPassword, new_password: newPassword },
    })
    changingPassword = false
    if (result.error !== undefined) {
      const status = result.response?.status
      if (status === 400) toast.error("Mot de passe actuel incorrect")
      else if (status === 422)
        toast.error("Le nouveau mot de passe doit contenir au moins 8 caractères.")
      else toast.error("Changement de mot de passe impossible.")
      return
    }
    toast.success("Mot de passe mis à jour")
    currentPassword = newPassword = confirmPassword = ""
  }
</script>

<!-- Toggle accessible maison (pas de primitive switch dans ui/). -->
{#snippet toggleRow(options: {
  label: string
  description?: string
  checked: boolean
  onToggle: () => void
  disabled?: boolean
})}
  <div class="flex items-start justify-between gap-4">
    <div class="flex min-w-0 flex-col gap-0.5">
      <span class="text-sm font-medium">{options.label}</span>
      {#if options.description}
        <span class="text-muted-foreground text-xs">{options.description}</span>
      {/if}
    </div>
    <button
      type="button"
      role="switch"
      aria-checked={options.checked}
      aria-label={options.label}
      disabled={options.disabled}
      class="relative h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors disabled:cursor-default disabled:opacity-50 {options.checked
        ? 'bg-primary'
        : 'bg-muted-foreground/25'}"
      onclick={options.onToggle}
    >
      <span
        class="bg-card absolute top-0.5 left-0.5 size-4 rounded-full shadow-sm transition-transform {options.checked
          ? 'translate-x-4'
          : ''}"
        aria-hidden="true"
      ></span>
    </button>
  </div>
{/snippet}

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Paramètres" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <h1 class="font-title text-lg font-bold">Paramètres</h1>

        <!-- Préférences d'interface (par utilisateur, sauvegarde immédiate) -->
        <Card size="sm">
          <CardHeader>
            <CardTitle class="font-title text-sm">Interface</CardTitle>
            <CardDescription class="text-muted-foreground text-xs">
              Préférences personnelles, enregistrées à chaque changement.
            </CardDescription>
          </CardHeader>
          <CardContent class="flex flex-col gap-4">
            {@render toggleRow({
              label: "Raccourcis clavier dans la review",
              description: "V valider · R rejeter · A appliquer · ←/→ naviguer",
              checked: prefs.shortcuts_enabled,
              onToggle: () => {
                prefs.shortcuts_enabled = !prefs.shortcuts_enabled
                savePreferences()
              },
            })}
            {@render toggleRow({
              label: "Enchaîner vers l'item suivant après une décision",
              checked: prefs.auto_advance,
              onToggle: () => {
                prefs.auto_advance = !prefs.auto_advance
                savePreferences()
              },
            })}
            <div class="grid gap-4 sm:grid-cols-2">
              <div class="flex flex-col gap-1.5">
                <Label for="pref-density">Densité des tables</Label>
                <select
                  id="pref-density"
                  class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                  bind:value={prefs.density}
                  onchange={() => savePreferences()}
                >
                  <option value="comfortable">Confortable</option>
                  <option value="compact">Compact</option>
                </select>
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for="pref-per-page">Produits par page</Label>
                <select
                  id="pref-per-page"
                  class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                  bind:value={prefs.products_per_page}
                  onchange={() => savePreferences()}
                >
                  <option value={20}>20</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- Défauts d'enrichissement (niveau compte) -->
        <Card size="sm">
          <CardHeader>
            <CardTitle class="font-title text-sm">Enrichissement (compte)</CardTitle>
            <CardDescription class="text-muted-foreground text-xs">
              Ces défauts s'appliquent aux nouveaux jobs ; chaque job peut les surcharger.
            </CardDescription>
          </CardHeader>
          <CardContent class="flex flex-col gap-4">
            {#if !accountLoaded}
              <Skeleton class="h-9 w-full" />
              <Skeleton class="h-20 w-full" />
            {:else}
              <div class="flex flex-col gap-2">
                <Label>Modèle de titre par défaut</Label>

                <!-- Ordered, removable selected tokens. -->
                <div class="flex flex-wrap items-center gap-1.5">
                  {#if templateTokens.length === 0}
                    <span class="text-muted-foreground text-xs italic">
                      Aucun token — le modèle par défaut {"{title}"} sera utilisé.
                    </span>
                  {/if}
                  {#each templateTokens as key, index (key)}
                    {#if index > 0}
                      <span class="text-muted-foreground font-mono text-xs">
                        {templateSeparator.trim() || "␣"}
                      </span>
                    {/if}
                    <span
                      class="bg-primary/10 text-primary inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium"
                    >
                      {TITLE_TOKENS.find((t) => t.key === key)?.label ?? key}
                      <button
                        type="button"
                        class="hover:bg-primary/20 -mr-1 cursor-pointer rounded-full p-0.5"
                        aria-label={`Retirer le token ${key}`}
                        onclick={() => removeToken(key)}
                      >
                        <svg
                          width="10"
                          height="10"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2.5"
                          aria-hidden="true"
                          ><path d="M18 6 6 18M6 6l12 12" /></svg
                        >
                      </button>
                    </span>
                  {/each}
                </div>

                <!-- Remaining tokens: click to append (no free typing = no typos). -->
                {#if availableTokens.length > 0}
                  <div class="flex flex-wrap items-center gap-1.5">
                    <span class="text-muted-foreground text-xs">Ajouter :</span>
                    {#each availableTokens as token (token.key)}
                      <button
                        type="button"
                        class="text-muted-foreground hover:text-foreground hover:bg-muted/50 cursor-pointer rounded-full border border-dashed px-2.5 py-0.5 text-xs transition-colors"
                        onclick={() => addToken(token.key)}
                      >
                        + {token.label}
                      </button>
                    {/each}
                  </div>
                {/if}

                <div class="flex flex-col gap-1.5 sm:max-w-56">
                  <Label for="template-separator">Séparateur entre tokens</Label>
                  <select
                    id="template-separator"
                    class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                    bind:value={templateSeparator}
                  >
                    {#each SEPARATORS as separator (separator.value)}
                      <option value={separator.value}>{separator.label}</option>
                    {/each}
                  </select>
                </div>

                {#if templateTokens.length > 0}
                  <p class="text-muted-foreground text-xs">
                    Modèle : <code class="font-mono">{titleTemplate}</code>
                    <br />
                    Aperçu : <span class="text-foreground">{templatePreview}</span>
                  </p>
                {/if}
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for="editorial-instructions">Instructions éditoriales par défaut</Label>
                <textarea
                  id="editorial-instructions"
                  rows="3"
                  class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                  placeholder="Ex. Ton chaleureux, vouvoiement, mettre en avant la durabilité…"
                  bind:value={editorialInstructions}
                ></textarea>
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

        <!-- Notifications (même objet AccountSettings, même bouton Enregistrer) -->
        <Card size="sm">
          <CardHeader>
            <CardTitle class="font-title flex items-center gap-2 text-sm">
              Notifications
              <span
                class="text-muted-foreground rounded-full border px-2 py-0.5 text-[10px] font-normal"
              >
                Bientôt actif
              </span>
            </CardTitle>
            <CardDescription class="text-muted-foreground text-xs">
              Le réglage est sauvegardé, mais l'envoi d'emails n'est pas encore branché.
            </CardDescription>
          </CardHeader>
          <CardContent class="flex flex-col gap-4">
            {#if !accountLoaded}
              <Skeleton class="h-9 w-full" />
            {:else}
              {@render toggleRow({
                label: "M'avertir par email en fin de job",
                checked: notifyOnJobDone,
                onToggle: () => (notifyOnJobDone = !notifyOnJobDone),
              })}
              <div class="flex flex-col gap-1.5 sm:max-w-80">
                <Label for="notify-email">Email de notification</Label>
                <Input
                  id="notify-email"
                  type="email"
                  placeholder={user.email}
                  disabled={!notifyOnJobDone}
                  bind:value={notifyEmail}
                />
              </div>
            {/if}
          </CardContent>
        </Card>

        <div class="flex justify-end">
          <Button disabled={!accountLoaded || savingAccount} onclick={saveAccount}>
            {savingAccount ? "Enregistrement…" : "Enregistrer"}
          </Button>
        </div>

        <!-- Compte -->
        <Card size="sm">
          <CardHeader>
            <CardTitle class="font-title text-sm">Compte</CardTitle>
          </CardHeader>
          <CardContent class="flex flex-col gap-4">
            <div class="flex flex-col gap-1 text-sm">
              {#if user.full_name}
                <span class="font-medium">{user.full_name}</span>
              {/if}
              <span class="text-muted-foreground">{user.email}</span>
            </div>

            <div class="flex items-center gap-2 text-xs">
              {#if connection?.configured}
                <span class="size-2 shrink-0 rounded-full bg-emerald-500" aria-hidden="true"
                ></span>
                <span class="text-muted-foreground">
                  Connecté à {connection.host ?? "Tillin"}
                  {#if connection.data_source}
                    · source de données : {connection.data_source}
                  {/if}
                </span>
              {:else}
                <span
                  class="bg-muted-foreground/40 size-2 shrink-0 rounded-full"
                  aria-hidden="true"
                ></span>
                <span class="text-muted-foreground">Connexion Tillin non configurée</span>
              {/if}
            </div>

            <Separator />

            <form class="flex flex-col gap-3" onsubmit={updatePassword}>
              <span class="text-sm font-medium">Changer le mot de passe</span>
              <div class="grid gap-3 sm:grid-cols-3">
                <div class="flex flex-col gap-1.5">
                  <Label for="current-password">Mot de passe actuel</Label>
                  <Input
                    id="current-password"
                    type="password"
                    autocomplete="current-password"
                    required
                    bind:value={currentPassword}
                  />
                </div>
                <div class="flex flex-col gap-1.5">
                  <Label for="new-password">Nouveau mot de passe</Label>
                  <Input
                    id="new-password"
                    type="password"
                    autocomplete="new-password"
                    required
                    bind:value={newPassword}
                  />
                </div>
                <div class="flex flex-col gap-1.5">
                  <Label for="confirm-password">Confirmation</Label>
                  <Input
                    id="confirm-password"
                    type="password"
                    autocomplete="new-password"
                    required
                    bind:value={confirmPassword}
                  />
                </div>
              </div>
              {#if passwordError}
                <p class="text-destructive text-xs" role="alert">{passwordError}</p>
              {/if}
              <div class="flex items-center justify-between gap-3">
                <p class="text-muted-foreground text-xs">
                  Compte connecté via Tillin ? Le mot de passe se gère côté Tillin.
                </p>
                <Button
                  type="submit"
                  variant="secondary"
                  size="sm"
                  class="shrink-0"
                  disabled={changingPassword}
                >
                  {changingPassword ? "…" : "Mettre à jour"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
