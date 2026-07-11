<script lang="ts">
  // Page Profils : gestion des profils d'import (règles de transformation
  // vers le CSV Tillin). Avec ~30 fournisseurs, la liste est filtrable par
  // nom ou fournisseur détecté. Le formulaire est partagé avec la page
  // d'import (ImportProfileForm).
  import Plus from "@lucide/svelte/icons/plus"
  import Search from "@lucide/svelte/icons/search"
  import { onMount } from "svelte"
  import { toast } from "svelte-sonner"

  import {
    deleteImportProfile,
    listImportProfiles,
    type ImportProfileConfig,
    type ImportProfilePublic,
  } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Separator } from "@/lib/components/ui/separator"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import ImportProfileForm from "@/lib/components/app/ImportProfileForm.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"

  let { appName }: { appName: string } = $props()

  let profiles = $state<ImportProfilePublic[] | null>(null)
  let loadFailed = $state(false)

  // Formulaire : null = fermé, "new" = création, sinon id du profil édité.
  type FormTarget = null | "new" | number
  let formTarget = $state<FormTarget>(null)
  // Suppression en deux temps : premier clic arme la confirmation.
  let confirmingDeleteId = $state<number | null>(null)
  let deletingId = $state<number | null>(null)

  let search = $state("")

  async function load() {
    profiles = null
    loadFailed = false
    const { data, error } = await listImportProfiles()
    if (error || data === undefined) {
      loadFailed = true
      profiles = []
      return
    }
    profiles = data
  }

  onMount(load)

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

  function onSaved(saved: ImportProfilePublic, isNew: boolean) {
    if (isNew) {
      profiles = [...(profiles ?? []), saved]
    } else {
      profiles = (profiles ?? []).map((p) => (p.id === saved.id ? saved : p))
    }
    formTarget = null
  }

  async function remove(profile: ImportProfilePublic) {
    deletingId = profile.id
    const { error } = await deleteImportProfile(profile.id)
    deletingId = null
    confirmingDeleteId = null
    if (error) {
      toast.error("Suppression impossible.")
      return
    }
    profiles = (profiles ?? []).filter((p) => p.id !== profile.id)
    if (formTarget === profile.id) formTarget = null
    toast.success("Profil supprimé")
  }

  /** Résumé lisible de la règle de prix d'un profil. */
  function priceSummary(config: ImportProfileConfig): string {
    if (config.price_mode === "coefficient") {
      return `Prix de gros × ${config.coefficient ?? "?"}, arrondi au multiple de ${config.round_up_to}`
    }
    return "Prix conseillé repris tel quel"
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Profils d'import" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <div class="flex items-center justify-between gap-2">
          <h1 class="font-title text-lg font-bold">Profils d'import</h1>
          <Button
            size="sm"
            onclick={() => {
              formTarget = "new"
              confirmingDeleteId = null
            }}
          >
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

            {#if profiles === null}
              <Skeleton class="h-12 w-full" />
              <Skeleton class="h-12 w-full" />
            {:else if loadFailed}
              <div class="flex flex-col items-start gap-2">
                <p class="text-destructive text-xs" role="alert">
                  Impossible de charger les profils d'import.
                </p>
                <Button variant="secondary" size="sm" onclick={load}>
                  Réessayer
                </Button>
              </div>
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
              <ul class="flex flex-col">
                {#each filtered as profile, index (profile.id)}
                  {#if index > 0}
                    <Separator />
                  {/if}
                  <li class="flex flex-wrap items-center justify-between gap-2 py-2.5">
                    <div class="flex min-w-0 flex-col gap-0.5">
                      <span class="text-sm font-medium">{profile.name}</span>
                      <span class="text-muted-foreground text-xs">
                        {#if profile.config.supplier_label || profile.supplier_match}
                          Fournisseur : « {profile.config.supplier_label ||
                            profile.supplier_match} » ·
                        {/if}
                        {priceSummary(profile.config)}
                      </span>
                    </div>
                    <div class="flex shrink-0 items-center gap-2">
                      {#if confirmingDeleteId === profile.id}
                        <span class="text-destructive text-xs">Supprimer ?</span>
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={deletingId === profile.id}
                          onclick={() => remove(profile)}
                        >
                          {deletingId === profile.id ? "…" : "Oui, supprimer"}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onclick={() => (confirmingDeleteId = null)}
                        >
                          Annuler
                        </Button>
                      {:else}
                        <Button
                          variant="outline"
                          size="sm"
                          onclick={() => {
                            formTarget = profile.id
                            confirmingDeleteId = null
                          }}
                        >
                          Modifier
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Supprimer le profil ${profile.name}`}
                          onclick={() => (confirmingDeleteId = profile.id)}
                        >
                          Supprimer
                        </Button>
                      {/if}
                    </div>
                  </li>
                {/each}
              </ul>
            {/if}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
