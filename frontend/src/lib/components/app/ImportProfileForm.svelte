<script lang="ts" module>
  // Ids uniques par instance : le formulaire peut être monté sur la page
  // Profils et sur la page d'import (labels + datalists sans collision).
  let instanceCounter = 0
</script>

<script lang="ts">
  // Formulaire partagé de création/édition d'un profil d'import (règles de
  // transformation vers le CSV Tillin). Utilisé par la page Profils et par le
  // panneau inline de la page d'import. Le composant fait lui-même l'appel
  // create/update et remonte le profil sauvegardé via `onSaved`.
  import { onMount } from "svelte"
  import { toast } from "svelte-sonner"

  import {
    loadCatalogFilters,
    optionTitles,
    type CatalogFiltersData,
  } from "@/lib/api/catalogFilters"
  import ReferenceSelect from "@/lib/components/app/ReferenceSelect.svelte"
  import {
    createImportProfile,
    updateImportProfile,
    type ImportProfileConfig,
    type ImportProfilePublic,
  } from "@/lib/api/imports"
  import { Button } from "@/lib/components/ui/button"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Separator } from "@/lib/components/ui/separator"

  let {
    profile = null,
    prefill,
    onSaved,
    onCancel,
  }: {
    /** Profil à éditer, ou null pour une création. */
    profile?: ImportProfilePublic | null
    /** Pré-remplissage en création (ex. fournisseur détecté sur le job). */
    prefill?: { supplier_match?: string; supplier_label?: string }
    /** Appelé après sauvegarde réussie (toast déjà affiché). */
    onSaved: (saved: ImportProfilePublic, isNew: boolean) => void
    onCancel: () => void
  } = $props()

  const uid = `ipf-${++instanceCounter}`

  const selectClass =
    "border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"

  // Référentiel de classification pour les datalists (échec silencieux →
  // simples champs texte, la saisie libre reste toujours possible).
  let filters = $state<CatalogFiltersData | null>(null)
  onMount(() => {
    loadCatalogFilters().then((data) => {
      filters = data
    })
  })

  let saving = $state(false)

  // Tous les champs en chaînes (les décimaux voyagent en chaînes JSON).
  let form = $state(initialForm())

  function initialForm() {
    if (profile) {
      const c = profile.config
      return {
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
        tax_rate: c.tax_rate,
        status: c.status,
      }
    }
    return {
      name: "",
      supplier_match: prefill?.supplier_match ?? "",
      price_mode: "retail_as_is" as ImportProfileConfig["price_mode"],
      coefficient: "",
      round_up_to: "5",
      barcode_mode: "ean" as ImportProfileConfig["barcode_mode"],
      brand_mode: "as_extracted" as ImportProfileConfig["brand_mode"],
      brand_value: "",
      supplier_label: prefill?.supplier_label ?? "",
      season_label: "",
      tax_rate: "20",
      status: "active",
    }
  }

  async function save(event: SubmitEvent) {
    event.preventDefault()
    if (saving) return
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
      tax_rate: form.tax_rate.trim(),
      status: form.status.trim(),
    }
    const body = { name, supplier_match: form.supplier_match.trim(), config }
    saving = true
    if (profile === null) {
      const { data, error } = await createImportProfile(body)
      saving = false
      if (error || data === undefined) {
        toast.error("Création du profil impossible.")
        return
      }
      toast.success("Profil créé")
      onSaved(data, true)
    } else {
      const { data, error } = await updateImportProfile(profile.id, body)
      saving = false
      if (error || data === undefined) {
        toast.error("Enregistrement du profil impossible.")
        return
      }
      toast.success("Profil enregistré")
      onSaved(data, false)
    }
  }
</script>

<form class="flex flex-col gap-4" onsubmit={save}>
  <div class="grid gap-3 sm:grid-cols-2">
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-name">Nom du profil</Label>
      <Input
        id="{uid}-name"
        placeholder="Ex. L'Espion — Bambinoh"
        required
        bind:value={form.name}
      />
    </div>
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-supplier-match">Fournisseur détecté</Label>
      <Input
        id="{uid}-supplier-match"
        placeholder="Ex. l'espion"
        bind:value={form.supplier_match}
      />
      <p class="text-muted-foreground text-xs">
        Sert à pré-sélectionner ce profil quand le fournisseur du document
        correspond (comparaison en minuscules).
      </p>
    </div>
  </div>

  <Separator />

  <div class="grid gap-3 sm:grid-cols-2">
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-price-mode">Mode de prix</Label>
      <select id="{uid}-price-mode" class={selectClass} bind:value={form.price_mode}>
        <option value="retail_as_is">Prix conseillé tel quel</option>
        <option value="coefficient">Coefficient sur le prix de gros</option>
      </select>
      <p class="text-muted-foreground text-xs">
        Coefficient : prix de vente = prix de gros × coefficient, arrondi au
        multiple supérieur.
      </p>
    </div>
    {#if form.price_mode === "coefficient"}
      <div class="grid grid-cols-2 gap-3">
        <div class="flex flex-col gap-1.5">
          <Label for="{uid}-coefficient">Coefficient</Label>
          <Input
            id="{uid}-coefficient"
            inputmode="decimal"
            placeholder="Ex. 2.5"
            bind:value={form.coefficient}
          />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="{uid}-round-up">Arrondi (multiple)</Label>
          <Input
            id="{uid}-round-up"
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
      <Label for="{uid}-barcode-mode">Codes-barres</Label>
      <select id="{uid}-barcode-mode" class={selectClass} bind:value={form.barcode_mode}>
        <option value="ean">EAN du fournisseur</option>
        <option value="constructed">Construits automatiquement</option>
      </select>
      <p class="text-muted-foreground text-xs">
        « Construits » : un code est généré quand l'EAN manque.
      </p>
    </div>
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-brand-mode">Marque</Label>
      <select id="{uid}-brand-mode" class={selectClass} bind:value={form.brand_mode}>
        <option value="as_extracted">Telle qu'extraite du document</option>
        <option value="fixed">Valeur fixe</option>
      </select>
      {#if form.brand_mode === "fixed"}
        <ReferenceSelect
          ariaLabel="Marque fixe"
          placeholder="Ex. Garcia"
          options={optionTitles(filters?.brands ?? [])}
          emptyLabel="Choisir une marque…"
          bind:value={form.brand_value}
        />
      {/if}
    </div>
  </div>

  <Separator />

  <div class="grid gap-3 sm:grid-cols-2">
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-supplier-label">Libellé fournisseur</Label>
      <ReferenceSelect
        id="{uid}-supplier-label"
        placeholder="Ex. L'Espion"
        options={optionTitles(filters?.suppliers ?? [])}
        emptyLabel="Fournisseur du document"
        bind:value={form.supplier_label}
      />
      <p class="text-muted-foreground text-xs">
        Valeur écrite dans la colonne fournisseur du CSV.
      </p>
    </div>
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-season-label">Libellé saison</Label>
      <ReferenceSelect
        id="{uid}-season-label"
        placeholder="Ex. H26"
        options={optionTitles(filters?.seasons ?? [])}
        emptyLabel="Saison du document"
        bind:value={form.season_label}
      />
    </div>
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-tax-rate">TVA (%)</Label>
      <Input
        id="{uid}-tax-rate"
        inputmode="decimal"
        placeholder="Ex. 20"
        bind:value={form.tax_rate}
      />
    </div>
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-status">Statut des produits</Label>
      <Input id="{uid}-status" placeholder="Ex. active" bind:value={form.status} />
      <p class="text-muted-foreground text-xs">
        Statut appliqué aux produits créés dans Tillin.
      </p>
    </div>
  </div>

  <div class="flex items-center justify-end gap-2">
    <Button type="button" variant="ghost" size="sm" onclick={onCancel}>
      Annuler
    </Button>
    <Button type="submit" size="sm" disabled={saving}>
      {saving ? "Enregistrement…" : profile === null ? "Créer" : "Enregistrer"}
    </Button>
  </div>
</form>
