<script lang="ts">
  // Console admin — exceptions de coûts d'UN compte (remises négociées).
  // Une exception prime sur la grille commune (/admin/pricing) pour ce compte
  // uniquement ; la supprimer ramène le compte au prix commun. Chaque ligne
  // rappelle le prix commun qu'elle remplace.
  import { createQuery, useQueryClient } from "@tanstack/svelte-query"
  import Plus from "@lucide/svelte/icons/plus"
  import { toast } from "svelte-sonner"

  import {
    createAccountPriceOverride,
    deleteAccountPriceOverride,
    listAccountPriceOverrides,
    updateAccountPriceOverride,
    type UsagePriceOverridePublic,
  } from "@/lib/api/admin"
  import { listUsagePrices, type UsagePrice } from "@/lib/api/usage"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { ConfirmButton } from "@/lib/components/ui/confirm-button"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Select } from "@/lib/components/ui/select"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import { prefs } from "@/lib/preferences.svelte"
  import {
    apiErrorCode,
    formatUnitPrice,
    isTokenMetric,
    priceInputValue,
    unitPriceFromInput,
  } from "@/lib/usagePricing"

  let { accountId }: { accountId: number } = $props()

  const queryClient = useQueryClient()
  const cellPad = $derived(prefs.density === "compact" ? "py-1" : "py-2.5")

  const overridesQuery = createQuery(() => ({
    queryKey: ["admin", "account", accountId, "prices"],
    queryFn: async () => {
      const { data, error } = await listAccountPriceOverrides(accountId)
      if (error || data === undefined) throw new Error("overrides_load_failed")
      return data
    },
  }))
  // La grille commune alimente le sélecteur « coût à remplacer ».
  const commonQuery = createQuery(() => ({
    queryKey: ["admin", "prices"],
    queryFn: async () => {
      const { data, error } = await listUsagePrices()
      if (error || data === undefined) throw new Error("prices_load_failed")
      return data
    },
  }))
  const commonPrices = $derived<UsagePrice[]>(commonQuery.data ?? [])

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["admin", "account", accountId] })
  }

  function keyLabel(p: { provider: string; model?: string | null; metric: string }) {
    return `${p.provider} · ${p.model ?? "tous les modèles"} · ${p.metric}`
  }

  // Formulaire inline : editingId === null → création.
  let formOpen = $state(false)
  let editingId = $state<number | null>(null)
  let formSelection = $state("")
  let formProvider = $state("")
  let formModel = $state("")
  let formMetric = $state("")
  let formPrice = $state("")
  let formError = $state<string | null>(null)
  let saving = $state(false)
  const formIsManual = $derived(formSelection === "manual")
  const formIsTokenMetric = $derived(isTokenMetric(formMetric))

  function applySelection(value: string) {
    formSelection = value
    if (value === "manual") {
      formProvider = ""
      formModel = ""
      formMetric = ""
      return
    }
    const common = commonPrices[Number(value)]
    if (!common) return
    formProvider = common.provider
    formModel = common.model ?? ""
    formMetric = common.metric
  }

  function openCreate() {
    editingId = null
    formSelection = ""
    formProvider = ""
    formModel = ""
    formMetric = ""
    formPrice = ""
    formError = null
    formOpen = true
  }

  function openEdit(price: UsagePriceOverridePublic) {
    editingId = price.id
    formSelection = "manual"
    formProvider = price.provider
    formModel = price.model ?? ""
    formMetric = price.metric
    formPrice = priceInputValue(price.metric, price.unit_price)
    formError = null
    formOpen = true
  }

  function closeForm() {
    formOpen = false
    editingId = null
    formError = null
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault()
    formError = null
    const provider = formProvider.trim()
    const metric = formMetric.trim()
    if (!provider || !metric) {
      formError = "Le provider et la métrique sont obligatoires."
      return
    }
    const unitPrice = unitPriceFromInput(metric, formPrice)
    if (unitPrice === null) {
      formError = "Le prix doit être un nombre positif."
      return
    }
    const body = {
      provider,
      model: formModel.trim() || null,
      metric,
      unit_price: unitPrice,
      currency: "EUR",
    }
    saving = true
    const { data, error } =
      editingId === null
        ? await createAccountPriceOverride(accountId, body)
        : await updateAccountPriceOverride(accountId, editingId, body)
    saving = false
    if (error || data === undefined) {
      toast.error(
        apiErrorCode(error) === "duplicate_price"
          ? "Ce compte a déjà une exception pour ce provider, ce modèle et cette métrique."
          : "Enregistrement de l'exception impossible.",
      )
      return
    }
    toast.success(editingId === null ? "Exception ajoutée" : "Exception mise à jour")
    closeForm()
    invalidate()
  }

  async function remove(id: number) {
    const { error } = await deleteAccountPriceOverride(accountId, id)
    if (error !== undefined) {
      toast.error("Suppression impossible.")
      return
    }
    if (editingId === id) closeForm()
    toast.success("Exception supprimée — le compte revient au coût commun")
    invalidate()
  }
</script>

<Card size="sm">
  <CardHeader>
    <CardTitle class="font-title text-sm">Exceptions de coûts</CardTitle>
    <CardDescription class="text-muted-foreground text-xs">
      Coûts fournisseurs propres à ce compte (remise négociée…) : ils
      remplacent la grille commune pour ce compte uniquement. Sans exception,
      le compte utilise la grille commune de la page « Coûts ».
    </CardDescription>
  </CardHeader>
  <CardContent class="flex flex-col gap-3">
    {#if overridesQuery.isError}
      <p class="text-destructive text-xs" role="alert">
        Impossible de charger les exceptions de coûts.
      </p>
    {:else if !overridesQuery.data}
      <Skeleton class="h-10 w-full" />
    {:else}
      {#if overridesQuery.data.length === 0 && !formOpen}
        <p class="text-muted-foreground py-2 text-center text-sm">
          Aucune exception — ce compte suit la grille commune.
        </p>
      {:else if overridesQuery.data.length > 0}
        <div class="overflow-x-auto">
          <table class="w-full min-w-xl text-sm">
            <thead>
              <tr class="border-border border-b">
                <th class="text-muted-foreground px-3 py-2 text-left text-xs font-medium">Provider</th>
                <th class="text-muted-foreground px-3 py-2 text-left text-xs font-medium">Modèle</th>
                <th class="text-muted-foreground px-3 py-2 text-left text-xs font-medium">Métrique</th>
                <th class="text-muted-foreground px-3 py-2 text-right text-xs font-medium">Prix du compte</th>
                <th class="text-muted-foreground px-3 py-2 text-right text-xs font-medium">Prix commun remplacé</th>
                <th class="px-3 py-2 text-right"><span class="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {#each overridesQuery.data as price (price.id)}
                <tr class="border-border border-b last:border-b-0">
                  <td class="px-3 {cellPad} whitespace-nowrap">{price.provider}</td>
                  <td class="max-w-52 truncate px-3 {cellPad}" title={price.model ?? undefined}>
                    {#if price.model}
                      {price.model}
                    {:else}
                      <span class="text-muted-foreground italic">Tous les modèles</span>
                    {/if}
                  </td>
                  <td class="text-muted-foreground px-3 {cellPad} whitespace-nowrap text-xs">
                    {price.metric}
                  </td>
                  <td class="px-3 {cellPad} text-right whitespace-nowrap tabular-nums font-medium">
                    {formatUnitPrice(price.metric, price.unit_price)}
                  </td>
                  <td class="text-muted-foreground px-3 {cellPad} text-right whitespace-nowrap tabular-nums">
                    {price.common_unit_price == null
                      ? "aucun"
                      : formatUnitPrice(price.metric, price.common_unit_price)}
                  </td>
                  <td class="px-3 {cellPad} text-right whitespace-nowrap">
                    <div class="flex items-center justify-end gap-1">
                      <Button variant="ghost" size="sm" onclick={() => openEdit(price)}>
                        Modifier
                      </Button>
                      <ConfirmButton label="Supprimer" onconfirm={() => remove(price.id)} />
                    </div>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}

      {#if formOpen}
        <form
          class="border-border flex flex-col gap-3 rounded-md border border-dashed p-3"
          onsubmit={submit}
        >
          <span class="text-sm font-medium">
            {editingId === null ? "Nouvelle exception" : "Modifier l'exception"}
          </span>
          <div class="grid gap-3 sm:grid-cols-2">
            {#if editingId === null}
              <div class="flex flex-col gap-1.5 sm:col-span-2">
                <Label for="override-combo-{accountId}">Coût commun à remplacer</Label>
                <Select
                  id="override-combo-{accountId}"
                  value={formSelection}
                  onchange={(e) => applySelection(e.currentTarget.value)}
                >
                  <option value="" disabled>Choisir une ligne de la grille commune…</option>
                  {#each commonPrices as common, index (common.id)}
                    <option value={String(index)}>
                      {keyLabel(common)} — {formatUnitPrice(common.metric, common.unit_price)}
                    </option>
                  {/each}
                  <option value="manual">Autre (saisie manuelle)…</option>
                </Select>
              </div>
            {/if}
            {#if formIsManual || editingId !== null}
              <div class="flex flex-col gap-1.5">
                <Label for="override-provider-{accountId}">Provider</Label>
                <Input id="override-provider-{accountId}" placeholder="Ex. claude" bind:value={formProvider} />
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for="override-model-{accountId}">Modèle</Label>
                <Input
                  id="override-model-{accountId}"
                  placeholder="Vide = tous les modèles"
                  bind:value={formModel}
                />
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for="override-metric-{accountId}">Métrique</Label>
                <Input id="override-metric-{accountId}" placeholder="Ex. input_tokens" bind:value={formMetric} />
              </div>
              <p class="text-muted-foreground text-xs sm:col-span-2">
                Provider et métrique doivent correspondre exactement aux
                identifiants techniques enregistrés, sinon l'exception ne
                s'appliquera pas.
              </p>
            {:else if formMetric}
              <p class="text-muted-foreground text-xs sm:col-span-2">
                Exception pour <span class="font-mono">{formProvider}
                  · {formModel || "tous les modèles"} · {formMetric}</span>
              </p>
            {/if}
            <div class="flex flex-col gap-1.5">
              <Label for="override-price-{accountId}">
                {formIsTokenMetric ? "Prix (€ / million de tokens)" : "Prix (€ / unité)"}
              </Label>
              <Input
                id="override-price-{accountId}"
                type="number"
                min="0"
                step="any"
                inputmode="decimal"
                placeholder={formIsTokenMetric ? "Ex. 2,50" : "Ex. 0,05"}
                bind:value={formPrice}
              />
            </div>
          </div>
          {#if formError}
            <p class="text-destructive text-xs" role="alert">{formError}</p>
          {/if}
          <div class="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onclick={closeForm}>Annuler</Button>
            <Button type="submit" size="sm" disabled={saving}>
              {saving ? "Enregistrement…" : "Enregistrer"}
            </Button>
          </div>
        </form>
      {:else}
        <div>
          <Button variant="outline" size="sm" onclick={openCreate}>
            <Plus size={14} aria-hidden="true" data-icon="inline-start" />
            Nouvelle exception
          </Button>
        </div>
      {/if}
    {/if}
  </CardContent>
</Card>
