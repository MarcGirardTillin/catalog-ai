<script lang="ts">
  // Page Profils : gestion des profils d'import (règles de transformation
  // vers le CSV Tillin). Avec ~30 fournisseurs, la liste est filtrable par
  // nom ou fournisseur détecté. Le formulaire est partagé avec la page
  // d'import (ImportProfileForm).
  import Plus from "@lucide/svelte/icons/plus"
  import Search from "@lucide/svelte/icons/search"
  import { createQuery, useQueryClient } from "@tanstack/svelte-query"
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import { statsDashboardStats } from "@/client"

  import {
    bulkUpdateImportProfiles,
    deleteImportProfile,
    listImportProfiles,
    type ImportProfileConfig,
    type ImportProfilePublic,
  } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
  import { ConfirmButton } from "@/lib/components/ui/confirm-button"
  import { Dialog } from "@/lib/components/ui/dialog"
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
  import { Separator } from "@/lib/components/ui/separator"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import LocalPagination from "@/lib/components/app/LocalPagination.svelte"
  import ImportProfileForm from "@/lib/components/app/ImportProfileForm.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"

  let { appName }: { appName: string } = $props()

  const queryClient = useQueryClient()

  // Module Import : la nav masque déjà la page, mais elle reste accessible
  // par URL directe — écran « non souscrit » plutôt que des 403 en cascade.
  const featureStatsQuery = createQuery(() => ({
    queryKey: ["stats", "dashboard"],
    queryFn: async () => {
      const { data, error } = await statsDashboardStats()
      if (error || !data) throw new Error("stats_load_failed")
      return data
    },
  }))

  const profilesQuery = createQuery(() => ({
    queryKey: ["profiles", "list"],
    queryFn: async () => {
      const { data, error } = await listImportProfiles()
      if (error || data === undefined) throw new Error("profiles_load_failed")
      return data
    },
  }))
  const profiles = $derived(profilesQuery.data ?? null)
  const loadFailed = $derived(profilesQuery.isError)

  // Formulaire : null = fermé, "new" = création, sinon id du profil édité.
  type FormTarget = null | "new" | number
  let formTarget = $state<FormTarget>(null)
  let deletingId = $state<number | null>(null)

  let search = $state("")

  const editedProfile = $derived(
    typeof formTarget === "number"
      ? ((profiles ?? []).find((p) => p.id === formTarget) ?? null)
      : null,
  )

  // Recherche par nom ou fournisseur détecté (insensible à la casse).
  const filtered = $derived.by(() => {
    const needle = search.trim().toLowerCase()
    const all = profiles ?? []
    if (needle === "") return all
    return all.filter(
      (p) =>
        p.name.toLowerCase().includes(needle) ||
        p.supplier_match.toLowerCase().includes(needle),
    )
  })

  function onSaved(_saved: ImportProfilePublic, _isNew: boolean) {
    queryClient.invalidateQueries({ queryKey: ["profiles", "list"] })
    formTarget = null
  }

  async function remove(profile: ImportProfilePublic) {
    deletingId = profile.id
    const { error } = await deleteImportProfile(profile.id)
    deletingId = null
    if (error) {
      toast.error("Suppression impossible.")
      return
    }
    if (formTarget === profile.id) formTarget = null
    queryClient.invalidateQueries({ queryKey: ["profiles", "list"] })
    toast.success("Profil supprimé")
  }

  // --- Édition groupée (harmonisation catalogue) ---
  // Mode explicite (demande Marc 2026-07-30) : le bouton « Édition groupée »
  // active la sélection ; « Modifier la sélection » ouvre un popup avec les
  // trois conventions boutique (saison, modèle de titre, séparation par
  // couleur). « Ne pas modifier » laisse le champ intact profil par profil.
  let bulkMode = $state(false)
  let bulkDialogOpen = $state(false)
  let selected = $state<Set<number>>(new Set())
  let bulkSeason = $state("")
  let bulkSeasonEnabled = $state(false)
  let bulkTitleTemplate = $state<"keep" | "on" | "off">("keep")
  let bulkSplit = $state<"keep" | "on" | "off">("keep")
  let bulkSaving = $state(false)

  function toggleSelected(id: number) {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    selected = next
  }
  const allFilteredSelected = $derived(
    filtered.length > 0 && filtered.every((p) => selected.has(p.id)),
  )
  function toggleAllFiltered() {
    selected = allFilteredSelected
      ? new Set()
      : new Set(filtered.map((p) => p.id))
  }

  async function applyBulk() {
    if (bulkSaving || selected.size === 0) return
    const body: Parameters<typeof bulkUpdateImportProfiles>[0] = {
      profile_ids: [...selected],
    }
    if (bulkSeasonEnabled) body.season_label = bulkSeason.trim()
    if (bulkTitleTemplate !== "keep")
      body.apply_title_template = bulkTitleTemplate === "on"
    if (bulkSplit !== "keep") body.split_by_color = bulkSplit === "on"
    if (
      body.season_label === undefined &&
      body.apply_title_template === undefined &&
      body.split_by_color === undefined
    ) {
      toast.error("Choisissez au moins un réglage à appliquer.")
      return
    }
    bulkSaving = true
    const { data, error } = await bulkUpdateImportProfiles(body)
    bulkSaving = false
    if (error || !data) {
      toast.error("Modification groupée impossible.")
      return
    }
    toast.success(`${data.length} profil${data.length > 1 ? "s" : ""} mis à jour`)
    selected = new Set()
    bulkSeasonEnabled = false
    bulkSeason = ""
    bulkTitleTemplate = "keep"
    bulkSplit = "keep"
    bulkDialogOpen = false
    bulkMode = false
    queryClient.invalidateQueries({ queryKey: ["profiles", "list"] })
  }

  function exitBulkMode() {
    bulkMode = false
    bulkDialogOpen = false
    selected = new Set()
  }

  /** Résumé lisible de la règle de prix d'un profil. */
  function priceSummary(config: ImportProfileConfig): string {
    if (config.price_mode === "coefficient") {
      return `Prix d'achat HT × ${config.coefficient ?? "?"}, arrondi au multiple de ${config.round_up_to}`
    }
    return "Prix conseillé repris tel quel"
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Profils d'import" }]}>
      {#if featureStatsQuery.data?.feature_import === false}
        <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
          <Card>
            <CardContent class="flex flex-col items-start gap-3 py-6">
              <p class="text-sm">
                Le module d'import n'est pas activé pour votre compte.
              </p>
              <Button variant="secondary" onclick={() => navigate("/")}>
                Retour au tableau de bord
              </Button>
            </CardContent>
          </Card>
        </div>
      {:else}
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <div class="flex items-center justify-between gap-2">
          <h1 class="font-title text-lg font-bold">Profils d'import</h1>
          <Button size="sm" onclick={() => (formTarget = "new")}>
            <Plus size={14} aria-hidden="true" />
            Nouveau profil
          </Button>
        </div>
        <p class="text-muted-foreground text-sm">
          Un profil définit comment transformer un import fournisseur en CSV
          Tillin : règle de prix, codes-barres, marque, libellés et valeurs par
          défaut. Il est réutilisé automatiquement à chaque import du même
          fournisseur.
        </p>

        {#if formTarget !== null}
          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">
                {formTarget === "new" ? "Nouveau profil" : "Modifier le profil"}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {#key formTarget}
                <ImportProfileForm
                  profile={editedProfile}
                  {onSaved}
                  onCancel={() => (formTarget = null)}
                />
              {/key}
            </CardContent>
          </Card>
        {/if}

        <Card size="sm">
          <CardHeader>
            <CardTitle class="font-title text-sm">
              Profils
              {#if profiles !== null && profiles.length > 0}
                <span class="text-muted-foreground font-normal">
                  ({profiles.length})
                </span>
              {/if}
            </CardTitle>
            <CardDescription class="text-muted-foreground text-xs">
              Recherchez par nom de profil ou fournisseur détecté.
            </CardDescription>
          </CardHeader>
          <CardContent class="flex flex-col gap-3">
            <div class="relative sm:max-w-80">
              <Search
                size={14}
                class="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2"
                aria-hidden="true"
              />
              <Input
                type="search"
                class="pl-8"
                placeholder="Rechercher un profil ou un fournisseur…"
                aria-label="Rechercher un profil par nom ou fournisseur"
                bind:value={search}
              />
            </div>

            {#if loadFailed}
              <div class="flex flex-col items-start gap-2">
                <p class="text-destructive text-xs" role="alert">
                  Impossible de charger les profils d'import.
                </p>
                <Button
                  variant="secondary"
                  size="sm"
                  onclick={() => profilesQuery.refetch()}
                >
                  Réessayer
                </Button>
              </div>
            {:else if profiles === null}
              <Skeleton class="h-12 w-full" />
              <Skeleton class="h-12 w-full" />
            {:else if profiles.length === 0}
              <p class="text-muted-foreground text-sm">
                Aucun profil pour l'instant. Créez-en un pour automatiser vos
                exports.
              </p>
            {:else if filtered.length === 0}
              <p class="text-muted-foreground text-sm">
                Aucun profil ne correspond à « {search.trim()} ».
              </p>
            {:else}
              <!-- Édition groupée : mode explicite — le bouton active la
                   sélection, « Modifier la sélection » ouvre le popup. -->
              {#if !bulkMode}
                <div>
                  <Button variant="outline" size="sm" onclick={() => (bulkMode = true)}>
                    Édition groupée
                  </Button>
                </div>
              {:else}
                <div class="flex flex-wrap items-center gap-2">
                  <label class="text-muted-foreground flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      class="size-4"
                      checked={allFilteredSelected}
                      onchange={toggleAllFiltered}
                    />
                    Tout sélectionner ({filtered.length})
                  </label>
                  <Button
                    size="sm"
                    disabled={selected.size === 0}
                    onclick={() => (bulkDialogOpen = true)}
                  >
                    Modifier la sélection ({selected.size})
                  </Button>
                  <Button variant="ghost" size="sm" onclick={exitBulkMode}>
                    Terminer
                  </Button>
                </div>
              {/if}

              <LocalPagination items={filtered} pageSize={10}>
                {#snippet children(visibleProfiles)}
              <ul class="flex flex-col">
                {#each visibleProfiles as profile, index (profile.id)}
                  {#if index > 0}
                    <Separator />
                  {/if}
                  <li class="flex flex-wrap items-center justify-between gap-2 py-2.5">
                    {#if bulkMode}
                      <input
                        type="checkbox"
                        class="size-4 shrink-0"
                        aria-label={`Sélectionner ${profile.name}`}
                        checked={selected.has(profile.id)}
                        onchange={() => toggleSelected(profile.id)}
                      />
                    {/if}
                    <div class="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span class="text-sm font-medium">{profile.name}</span>
                      <span class="text-muted-foreground text-xs">
                        {#if profile.config.supplier_label || profile.supplier_match}
                          Fournisseur : « {profile.config.supplier_label ||
                            profile.supplier_match} » ·
                        {/if}
                        {priceSummary(profile.config)}
                        {#if profile.config.season_label}
                          · Saison {profile.config.season_label}
                        {/if}
                        {#if profile.config.split_by_color}
                          · 1 fiche/couleur
                        {/if}
                        {#if profile.config.apply_title_template}
                          · Modèle de titre
                        {/if}
                      </span>
                    </div>
                    <div class="flex shrink-0 items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onclick={() => (formTarget = profile.id)}
                      >
                        Modifier
                      </Button>
                      <ConfirmButton
                        label="Supprimer"
                        confirmLabel="Confirmer ?"
                        disabled={deletingId === profile.id}
                        onconfirm={() => remove(profile)}
                      />
                    </div>
                  </li>
                {/each}
              </ul>
                {/snippet}
              </LocalPagination>
            {/if}
          </CardContent>
        </Card>
      </div>

      {#if bulkDialogOpen}
        <Dialog
          title={`Modifier ${selected.size} profil${selected.size > 1 ? "s" : ""}`}
          dismissable={!bulkSaving}
          onClose={() => (bulkDialogOpen = false)}
        >
          <div class="flex flex-col gap-3">
            <div class="flex flex-col gap-1.5">
              <Label for="bulk-season">Saison</Label>
              <div class="flex items-center gap-2">
                <input
                  type="checkbox"
                  class="size-4 shrink-0"
                  aria-label="Modifier la saison"
                  bind:checked={bulkSeasonEnabled}
                />
                <Input
                  id="bulk-season"
                  placeholder="Ex. FW26 (vide = saison extraite)"
                  disabled={!bulkSeasonEnabled}
                  bind:value={bulkSeason}
                />
              </div>
            </div>
            <div class="flex flex-col gap-1.5">
              <Label for="bulk-title">Modèle de titre à l'import</Label>
              <Select id="bulk-title" bind:value={bulkTitleTemplate}>
                <option value="keep">Ne pas modifier</option>
                <option value="on">Activer</option>
                <option value="off">Désactiver</option>
              </Select>
            </div>
            <div class="flex flex-col gap-1.5">
              <Label for="bulk-split">Une fiche par couleur</Label>
              <Select id="bulk-split" bind:value={bulkSplit}>
                <option value="keep">Ne pas modifier</option>
                <option value="on">Activer</option>
                <option value="off">Désactiver</option>
              </Select>
            </div>
            <p class="text-muted-foreground text-xs">
              « Ne pas modifier » laisse le réglage intact profil par profil.
            </p>
            <div class="flex justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                disabled={bulkSaving}
                onclick={() => (bulkDialogOpen = false)}
              >
                Annuler
              </Button>
              <Button size="sm" disabled={bulkSaving} onclick={applyBulk}>
                {bulkSaving ? "Application…" : "Appliquer à la sélection"}
              </Button>
            </div>
          </div>
        </Dialog>
      {/if}
      {/if}
    </AppShell>
  {/snippet}
</RequireAuth>
