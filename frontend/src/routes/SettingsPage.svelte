<script lang="ts">
  import { toast } from "svelte-sonner"

  import {
    authUpdatePassword,
    settingsReadAccountSettings,
    settingsReadConnectionStatus,
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
  import { Select } from "@/lib/components/ui/select"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import { Switch } from "@/lib/components/ui/switch"
  import { TabBar } from "@/lib/components/ui/tabs"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import BrandWebsites from "@/lib/components/settings/BrandWebsites.svelte"
  import type { AccountSettingsExtended } from "@/lib/accountSettings.svelte"
  import { saveAccountSettingsPartial } from "@/lib/accountSettings.svelte"
  import { prefs, savePreferences } from "@/lib/preferences.svelte"

  let { appName }: { appName: string } = $props()

  // --- Onglets (état local ; les panneaux restent montés pour conserver
  // les saisies en cours quand on change d'onglet). ---
  // L'enrichissement (instructions, contexte boutique, modèle de titre)
  // a sa propre page : /enrichment.
  const TABS = [
    { key: "preferences", label: "Préférences" },
    { key: "brands", label: "Marques" },
    { key: "account", label: "Compte" },
  ] as const
  type TabKey = (typeof TABS)[number]["key"]
  let tab = $state<TabKey>("preferences")

  // L'onglet Marques charge des listes : montage paresseux à la première
  // ouverture (puis le composant reste monté).
  // Les profils d'import ont leur propre page (/profiles).
  let brandsOpened = $state(false)
  $effect(() => {
    if (tab === "brands") brandsOpened = true
  })

  // --- Connexion Tillin (lecture seule) ---
  let connection = $state<ConnectionStatus | null>(null)

  // --- Changement de mot de passe ---
  let currentPassword = $state("")
  let newPassword = $state("")
  let confirmPassword = $state("")
  let passwordError = $state<string | null>(null)
  let changingPassword = $state(false)

  $effect(() => {
    settingsReadConnectionStatus().then(({ data }) => {
      connection = data ?? null
    })
  })

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

<!-- Ligne de réglage booléen (label + description + interrupteur ui/). -->
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
    <Switch
      checked={options.checked}
      disabled={options.disabled}
      aria-label={options.label}
      onchange={options.onToggle}
    />
  </div>
{/snippet}

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Paramètres" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <h1 class="font-title text-lg font-bold">Paramètres</h1>

        <TabBar tabs={TABS} bind:value={tab} label="Sections des paramètres" />

        <!-- Onglet Préférences (perso, sauvegarde immédiate) -->
        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "preferences"}>
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
                  <Select
                    id="pref-density"
                    bind:value={prefs.density}
                    onchange={() => savePreferences()}
                  >
                    <option value="comfortable">Confortable</option>
                    <option value="compact">Compact</option>
                  </Select>
                </div>
                <div class="flex flex-col gap-1.5">
                  <Label for="pref-per-page">Produits par page</Label>
                  <Select
                    id="pref-per-page"
                    bind:value={prefs.products_per_page}
                    onchange={() => savePreferences()}
                  >
                    <option value={20}>20</option>
                    <option value={50}>50</option>
                    <option value={100}>100</option>
                  </Select>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <!-- Onglet Marques (sites web de référence par marque) -->
        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "brands"}>
          {#if brandsOpened}
            <BrandWebsites />
          {/if}
        </div>

        <!-- Onglet Compte (Tillin + notifications + mot de passe) -->
        <div class="flex flex-col gap-3" role="tabpanel" hidden={tab !== "account"}>
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
                {#if user.account_name}
                  <span class="text-muted-foreground">
                    Entreprise :
                    <span class="text-foreground font-medium">{user.account_name}</span>
                  </span>
                {/if}
              </div>

              <div class="flex items-center gap-2 text-xs">
                {#if connection?.configured}
                  <span
                    class="size-2 shrink-0 rounded-full bg-emerald-500"
                    aria-hidden="true"
                  ></span>
                  <!-- Hôte et source de données : détail d'infrastructure,
                       sans valeur pour le client (marque blanche). -->
                  <span class="text-muted-foreground">Connecté avec Tillin</span>
                {:else}
                  <span
                    class="bg-muted-foreground/40 size-2 shrink-0 rounded-full"
                    aria-hidden="true"
                  ></span>
                  <span class="text-muted-foreground">Connexion Tillin non configurée</span>
                {/if}
              </div>
            </CardContent>
          </Card>

          <!-- Le jour de facturation est un réglage opérateur GLOBAL : il vit
               dans Admin > Tarification, pas dans les paramètres du client. -->

          <!-- Notifications e-mail : abandonnées (2026-07-12) au profit des
               pastilles d'état de la sidebar (menus Imports / Enrichissements). -->


          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">Mot de passe</CardTitle>
            </CardHeader>
            <CardContent class="flex flex-col gap-4">
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
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
