<script lang="ts">
  // Profils d'import : règles de transformation d'un import fournisseur vers
  // le CSV Tillin (prix, code-barres, marque, libellés, défauts). Monté
  // paresseusement à la première ouverture de l'onglet.
  import { onMount } from "svelte"
  import { toast } from "svelte-sonner"

  import {
    createImportProfile,
    deleteImportProfile,
    listImportProfiles,
    updateImportProfile,
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
  import { Label } from "@/lib/components/ui/label"
  import { Separator } from "@/lib/components/ui/separator"
  import { Skeleton } from "@/lib/components/ui/skeleton"

  const selectClass =
    "border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"

  let profiles = $state<ImportProfilePublic[] | null>(null)
  let loadFailed = $state(false)

  // Formulaire : null = fermé, "new" = création, sinon id du profil édité.
  type FormTarget = null | "new" | number
  let formTarget = $state<FormTarget>(null)
  let saving = $state(false)
  // Suppression en deux temps : premier clic arme la confirmation.
  let confirmingDeleteId = $state<number | null>(null)
  let deletingId = $state<number | null>(null)

  // Tous les champs du formulaire en chaînes (les décimaux voyagent en
  // chaînes JSON côté API).
  let form = $state(emptyForm())

  function emptyForm() {
    return {
      name: "",
      supplier_match: "",
      price_mode: "retail_as_is" as ImportProfileConfig["price_mode"],
      coefficient: "",
      round_up_to: "5",
      barcode_mode: "ean" as ImportProfileConfig["barcode_mode"],
      brand_mode: "as_extracted" as ImportProfileConfig["brand_mode"],
      brand_value: "",
      supplier_label: "",
      season_label: "",
      gender_default: "",
      category_default: "",
      tax_rate: "20",
      status: "active",
    }
  }

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

  function openCreate() {
    form = emptyForm()
    formTarget = "new"
    confirmingDeleteId = null
  }

  function openEdit(profile: ImportProfilePublic) {
    const c = profile.config
    form = {
      name: profile.name,
      supplier_match: profile.supplier_match,
      price_mode: c.price_mode,
      coefficient: c.coefficient ?? "",
      round_up_to: c.round_up_to,
      barcode_mode: c.barcode_mode,
      brand_mode: c.brand_mode,
      brand_value: c.brand_value,
      supplier_label: c.supplier_label,
      season_label: c.season_label,
      gender_default: c.gender_default,
      category_default: c.category_default,
      tax_rate: c.tax_rate,
      status: c.status,
    }
    formTarget = profile.id
    confirmingDeleteId = null
  }

  function closeForm() {
    formTarget = null
  }

  async function save(event: SubmitEvent) {
    event.preventDefault()
    const name = form.name.trim()
    if (name === "") {
      toast.error("Le nom du profil est requis.")
      return
    }
    if (form.price_mode === "coefficient" && form.coefficient.trim() === "") {
      toast.error("Le coefficient est requis en mode coefficient.")
      return
    }
    const config: ImportProfileConfig = {
      price_mode: form.price_mode,
      coefficient:
        form.price_mode === "coefficient" ? form.coefficient.trim() : null,
      round_up_to: form.round_up_to.trim(),
      barcode_mode: form.barcode_mode,
      brand_mode: form.brand_mode,
      brand_value: form.brand_mode === "fixed" ? form.brand_value.trim() : "",
      supplier_label: form.supplier_label.trim(),
      season_label: form.season_label.trim(),
      gender_default: form.gender_default.trim(),
      category_default: form.category_default.trim(),
      tax_rate: form.tax_rate.trim(),
      status: form.status.trim(),
    }
    const body = { name, supplier_match: form.supplier_match.trim(), config }
    saving = true
    if (formTarget === "new") {
      const { data, error } = await createImportProfile(body)
      saving = false
      if (error || data === undefined) {
        toast.error("Création du profil impossible.")
        return
      }
      profiles = [...(profiles ?? []), data]
      toast.success("Profil créé")
    } else if (typeof formTarget === "number") {
      const { data, error } = await updateImportProfile(formTarget, body)
      saving = false
      if (error || data === undefined) {
        toast.error("Enregistrement du profil impossible.")
        return
      }
      profiles = (profiles ?? []).map((p) => (p.id === data.id ? data : p))
      toast.success("Profil enregistré")
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

<Card size="sm">
  <CardHeader>
    <CardTitle class="font-title text-sm">Profils d'import</CardTitle>
    <CardDescription class="text-muted-foreground text-xs">
      Un profil définit comment transformer un import fournisseur en CSV Tillin :
      règle de prix, codes-barres, marque, libellés et valeurs par défaut.
    </CardDescription>
  </CardHeader>
  <CardContent class="flex flex-col gap-3">
    {#if profiles === null}
      <Skeleton class="h-12 w-full" />
      <Skeleton class="h-12 w-full" />
    {:else if loadFailed}
      <div class="flex flex-col items-start gap-2">
        <p class="text-destructive text-xs" role="alert">
          Impossible de charger les profils d'import.
        </p>
        <Button variant="secondary" size="sm" onclick={load}>Réessayer</Button>
      </div>
    {:else}
      {#if profiles.length === 0}
        <p class="text-muted-foreground text-sm">
          Aucun profil pour l'instant. Créez-en un pour automatiser vos exports.
        </p>
      {:else}
        <ul class="flex flex-col">
          {#each profiles as profile, index (profile.id)}
            {#if index > 0}
              <Separator />
            {/if}
            <li class="flex flex-wrap items-center justify-between gap-2 py-2.5">
              <div class="flex min-w-0 flex-col gap-0.5">
                <span class="text-sm font-medium">{profile.name}</span>
                <span class="text-muted-foreground text-xs">
                  {#if profile.supplier_match}
                    Fournisseur détecté : « {profile.supplier_match} » ·
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
                  <Button variant="outline" size="sm" onclick={() => openEdit(profile)}>
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

      {#if formTarget === null}
        <div>
          <Button size="sm" onclick={openCreate}>Nouveau profil</Button>
        </div>
      {:else}
        <form
          class="border-border flex flex-col gap-4 rounded-md border p-3"
          onsubmit={save}
        >
          <p class="text-sm font-medium">
            {formTarget === "new" ? "Nouveau profil" : "Modifier le profil"}
          </p>

          <div class="grid gap-3 sm:grid-cols-2">
            <div class="flex flex-col gap-1.5">
              <Label for="profile-name">Nom du profil</Label>
              <Input
                id="profile-name"
                placeholder="Ex. L'Espion — Bambinoh"
                required
                bind:value={form.name}
              />
            </div>
            <div class="flex flex-col gap-1.5">
              <Label for="profile-supplier-match">Fournisseur détecté</Label>
              <Input
                id="profile-supplier-match"
                placeholder="Ex. l'espion"
                bind:value={form.supplier_match}
              />
              <p class="text-muted-foreground text-xs">
                Sert à pré-sélectionner ce profil quand le fournisseur du
                document correspond (comparaison en minuscules).
              </p>
            </div>
          </div>

          <Separator />

          <div class="grid gap-3 sm:grid-cols-2">
            <div class="flex flex-col gap-1.5">
              <Label for="profile-price-mode">Mode de prix</Label>
              <select
                id="profile-price-mode"
                class={selectClass}
                bind:value={form.price_mode}
              >
                <option value="retail_as_is">Prix conseillé tel quel</option>
                <option value="coefficient">Coefficient sur le prix de gros</option>
              </select>
              <p class="text-muted-foreground text-xs">
                Coefficient : prix de vente = prix de gros × coefficient,
                arrondi au multiple supérieur.
              </p>
            </div>
            {#if form.price_mode === "coefficient"}
              <div class="grid grid-cols-2 gap-3">
                <div class="flex flex-col gap-1.5">
                  <Label for="profile-coefficient">Coefficient</Label>
                  <Input
                    id="profile-coefficient"
                    inputmode="decimal"
                    placeholder="Ex. 2.5"
                    bind:value={form.coefficient}
                  />
                </div>
                <div class="flex flex-col gap-1.5">
                  <Label for="profile-round-up">Arrondi (multiple)</Label>
                  <Input
                    id="profile-round-up"
                    inputmode="decimal"
                    placeholder="Ex. 5"
                    bind:value={form.round_up_to}
                  />
                </div>
              </div>
            {/if}
          </div>

          <div class="grid gap-3 sm:grid-cols-2">
            <div class="flex flex-col gap-1.5">
              <Label for="profile-barcode-mode">Codes-barres</Label>
              <select
                id="profile-barcode-mode"
                class={selectClass}
                bind:value={form.barcode_mode}
              >
                <option value="ean">EAN du fournisseur</option>
                <option value="constructed">Construits automatiquement</option>
              </select>
              <p class="text-muted-foreground text-xs">
                « Construits » : un code est généré quand l'EAN manque.
              </p>
            </div>
            <div class="flex flex-col gap-1.5">
              <Label for="profile-brand-mode">Marque</Label>
              <select
                id="profile-brand-mode"
                class={selectClass}
                bind:value={form.brand_mode}
              >
                <option value="as_extracted">Telle qu'extraite du document</option>
                <option value="fixed">Valeur fixe</option>
              </select>
              {#if form.brand_mode === "fixed"}
                <Input
                  aria-label="Marque fixe"
                  placeholder="Ex. Garcia"
                  bind:value={form.brand_value}
                />
              {/if}
            </div>
          </div>

          <Separator />

          <div class="grid gap-3 sm:grid-cols-2">
            <div class="flex flex-col gap-1.5">
              <Label for="profile-supplier-label">Libellé fournisseur</Label>
              <Input
                id="profile-supplier-label"
                placeholder="Ex. L'Espion"
                bind:value={form.supplier_label}
              />
              <p class="text-muted-foreground text-xs">
                Valeur écrite dans la colonne fournisseur du CSV.
              </p>
            </div>
            <div class="flex flex-col gap-1.5">
              <Label for="profile-season-label">Libellé saison</Label>
              <Input
                id="profile-season-label"
                placeholder="Ex. H26"
                bind:value={form.season_label}
              />
            </div>
            <div class="flex flex-col gap-1.5">
              <Label for="profile-gender-default">Genre par défaut</Label>
              <Input
                id="profile-gender-default"
                placeholder="Ex. Mixte"
                bind:value={form.gender_default}
              />
              <p class="text-muted-foreground text-xs">
                Utilisé quand le genre n'a pas été extrait du document.
              </p>
            </div>
            <div class="flex flex-col gap-1.5">
              <Label for="profile-category-default">Catégorie par défaut</Label>
              <Input
                id="profile-category-default"
                placeholder="Ex. Vêtements"
                bind:value={form.category_default}
              />
            </div>
            <div class="flex flex-col gap-1.5">
              <Label for="profile-tax-rate">TVA (%)</Label>
              <Input
                id="profile-tax-rate"
                inputmode="decimal"
                placeholder="Ex. 20"
                bind:value={form.tax_rate}
              />
            </div>
            <div class="flex flex-col gap-1.5">
              <Label for="profile-status">Statut des produits</Label>
              <Input
                id="profile-status"
                placeholder="Ex. active"
                bind:value={form.status}
              />
              <p class="text-muted-foreground text-xs">
                Statut appliqué aux produits créés dans Tillin.
              </p>
            </div>
          </div>

          <div class="flex items-center justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onclick={closeForm}>
              Annuler
            </Button>
            <Button type="submit" size="sm" disabled={saving}>
              {saving ? "Enregistrement…" : formTarget === "new" ? "Créer" : "Enregistrer"}
            </Button>
          </div>
        </form>
      {/if}
    {/if}
  </CardContent>
</Card>
