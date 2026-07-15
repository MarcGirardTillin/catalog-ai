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
  import { onMount, untrack } from "svelte"
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
  import { Select } from "@/lib/components/ui/select"
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

  // Référentiel de classification pour les datalists (échec silencieux →
  // simples champs texte, la saisie libre reste toujours possible).
  let filters = $state<CatalogFiltersData | null>(null)
  onMount(() => {
    loadCatalogFilters().then((data) => {
      filters = data
    })
  })

  let saving = $state(false)
  // En création, le nom suit le fournisseur tant que l'utilisateur n'y a pas
  // touché ; en édition on ne réécrit jamais le nom saisi.
  let nameEdited = $state(untrack(() => profile !== null))

  let form = $state(initialForm())

  function initialForm() {
    if (profile) {
      const c = profile.config
      return {
        name: profile.name,
        // Un seul champ fournisseur (fusion de supplier_match + supplier_label).
        supplier: c.supplier_label || profile.supplier_match,
        // Marque vide = « telle qu'extraite » ; sinon valeur fixe.
        brand: c.brand_mode === "fixed" ? c.brand_value : "",
        season_label: c.season_label,
        wholesale_tax_rate: c.wholesale_tax_rate ?? "20",
        price_mode: c.price_mode,
        coefficient: c.coefficient ?? "",
        round_up_to: c.round_up_to,
        barcode_mode: c.barcode_mode,
        tax_rate: c.tax_rate,
        apply_title_template: c.apply_title_template ?? false,
        split_by_color: c.split_by_color ?? false,
      }
    }
    const supplier = prefill?.supplier_label ?? prefill?.supplier_match ?? ""
    return {
      name: supplier,
      supplier,
      // La marque est à ~95% le fournisseur : pré-remplie, modifiable.
      brand: supplier,
      season_label: "",
      wholesale_tax_rate: "20",
      price_mode: "retail_as_is" as ImportProfileConfig["price_mode"],
      coefficient: "",
      round_up_to: "5",
      barcode_mode: "ean" as ImportProfileConfig["barcode_mode"],
      tax_rate: "20",
      apply_title_template: false,
      split_by_color: false,
    }
  }

  // Nom auto = fournisseur, tant qu'il n'a pas été édité (création seulement).
  $effect(() => {
    const supplier = form.supplier
    if (!nameEdited) untrack(() => (form.name = supplier))
  })

  async function save(event: SubmitEvent) {
    event.preventDefault()
    if (saving) return
    const supplier = form.supplier.trim()
    const name = form.name.trim() || supplier
    if (name === "") {
      toast.error("Le nom du profil (ou le fournisseur) est requis.")
      return
    }
    if (form.price_mode === "coefficient" && form.coefficient.trim() === "") {
      toast.error("Le coefficient est requis en mode coefficient.")
      return
    }
    const brand = form.brand.trim()
    const config: ImportProfileConfig = {
      price_mode: form.price_mode,
      coefficient:
        form.price_mode === "coefficient" ? form.coefficient.trim() : null,
      round_up_to: form.round_up_to.trim(),
      barcode_mode: form.barcode_mode,
      // Marque renseignée → valeur fixe ; vide → telle qu'extraite du document.
      brand_mode: brand === "" ? "as_extracted" : "fixed",
      brand_value: brand,
      supplier_label: supplier,
      season_label: form.season_label.trim(),
      tax_rate: form.tax_rate.trim(),
      wholesale_tax_rate: form.wholesale_tax_rate.trim(),
      // Statut retiré du formulaire : toujours « active » à la création.
      status: "active",
      apply_title_template: form.apply_title_template,
      split_by_color: form.split_by_color,
    }
    // Le fournisseur sert aussi de clé d'auto-sélection (comparaison minuscule).
    const body = { name, supplier_match: supplier.toLowerCase(), config }
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
  <div class="flex flex-col gap-1.5 sm:max-w-96">
    <Label for="{uid}-name">Nom du profil</Label>
    <Input
      id="{uid}-name"
      placeholder="Ex. L'Espion"
      required
      bind:value={form.name}
      oninput={() => (nameEdited = true)}
    />
    <p class="text-muted-foreground text-xs">
      Pré-rempli avec le fournisseur — modifiable librement.
    </p>
  </div>

  <Separator />

  <!-- Fournisseur, marque, saison et taxe d'achat sur une même ligne. -->
  <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-supplier">Fournisseur</Label>
      <ReferenceSelect
        id="{uid}-supplier"
        placeholder="Ex. L'Espion"
        options={optionTitles(filters?.suppliers ?? [])}
        emptyLabel="Fournisseur du document"
        bind:value={form.supplier}
      />
    </div>
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-brand">Marque</Label>
      <ReferenceSelect
        id="{uid}-brand"
        placeholder="Vide = telle qu'extraite"
        options={optionTitles(filters?.brands ?? [])}
        emptyLabel="Telle qu'extraite"
        bind:value={form.brand}
      />
    </div>
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-season">Saison</Label>
      <ReferenceSelect
        id="{uid}-season"
        placeholder="Ex. H26"
        options={optionTitles(filters?.seasons ?? [])}
        emptyLabel="Saison du document"
        bind:value={form.season_label}
      />
    </div>
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-wholesale-tax">Taxe achat (%)</Label>
      <Input
        id="{uid}-wholesale-tax"
        inputmode="decimal"
        placeholder="Ex. 0"
        bind:value={form.wholesale_tax_rate}
      />
      <p class="text-muted-foreground text-xs">0 pour un fournisseur étranger.</p>
    </div>
  </div>

  <Separator />

  <!-- Prix de vente + TVA vente. -->
  <div class="grid gap-3 sm:grid-cols-2">
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-price-mode">Mode de prix (vente)</Label>
      <Select id="{uid}-price-mode" bind:value={form.price_mode}>
        <option value="retail_as_is">Prix conseillé tel quel</option>
        <option value="coefficient">Coefficient sur le prix de gros</option>
      </Select>
      <p class="text-muted-foreground text-xs">
        Coefficient : prix de vente = prix de gros × coefficient, arrondi au
        multiple supérieur.
      </p>
    </div>
    <div class="flex flex-col gap-1.5">
      <Label for="{uid}-tax-rate">TVA vente (%)</Label>
      <Input
        id="{uid}-tax-rate"
        inputmode="decimal"
        placeholder="Ex. 20"
        bind:value={form.tax_rate}
      />
    </div>
    {#if form.price_mode === "coefficient"}
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
    {/if}
  </div>

  <div class="flex flex-col gap-1.5 sm:max-w-96">
    <Label for="{uid}-barcode-mode">Codes-barres</Label>
    <Select id="{uid}-barcode-mode" bind:value={form.barcode_mode}>
      <option value="ean">EAN du fournisseur</option>
      <option value="constructed">Construits automatiquement</option>
    </Select>
    <p class="text-muted-foreground text-xs">
      « Construits » : un code REF-COULEUR-TAILLE est généré quand l'EAN manque.
    </p>
  </div>

  <Separator />

  <div class="flex flex-col gap-1.5">
    <label class="flex items-start gap-2 text-sm">
      <input
        type="checkbox"
        class="mt-0.5 size-4"
        bind:checked={form.apply_title_template}
      />
      <span>
        Appliquer le modèle de titre dès l'import
        <span class="text-muted-foreground block text-xs font-normal">
          Le titre du CSV est reconstruit depuis le modèle de titre du compte
          (Réglages) au lieu du titre brut du fournisseur. Désactivé par défaut.
        </span>
      </span>
    </label>
  </div>

  <div class="flex flex-col gap-1.5">
    <label class="flex items-start gap-2 text-sm">
      <input
        type="checkbox"
        class="mt-0.5 size-4"
        bind:checked={form.split_by_color}
      />
      <span>
        Une fiche produit par couleur
        <span class="text-muted-foreground block text-xs font-normal">
          À l'analyse du document, un produit décliné en plusieurs couleurs est
          séparé en une fiche par couleur (référence suffixée par la couleur).
          Appliqué à l'extraction — sans effet sur les imports déjà analysés.
        </span>
      </span>
    </label>
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
