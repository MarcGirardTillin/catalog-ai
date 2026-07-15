<script lang="ts">
  // Console admin — Coûts : grille des prix d'achat providers (CRUD) et
  // re-figement d'un mois facturé. C'est la vue COÛT RÉEL de l'opérateur —
  // la tarification vendue aux clients (packs de crédits, grille de
  // consommation) vit sur la page « Tarification » (/admin/billing).
  import { createQuery, useQueryClient } from "@tanstack/svelte-query"
  import ChartColumn from "@lucide/svelte/icons/chart-column"
  import Plus from "@lucide/svelte/icons/plus"
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert"
  import { toast } from "svelte-sonner"

  import { listAdminUsageMetrics, type AdminUsageMetric } from "@/lib/api/admin"
  import {
    createUsagePrice,
    deleteUsagePrice,
    listUsagePrices,
    refreezeUsageMonth,
    updateUsagePrice,
  } from "@/lib/api/usage"
  import type { UsagePrice } from "@/lib/api/usage"
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
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAdmin from "@/lib/components/app/RequireAdmin.svelte"
  import { prefs } from "@/lib/preferences.svelte"

  let { appName }: { appName: string } = $props()

  const queryClient = useQueryClient()
  const cellPad = $derived(prefs.density === "compact" ? "py-1" : "py-2.5")

  /** Les métriques *_tokens sont tarifées à l'unité mais lues par million. */
  function isTokenMetric(metric: string): boolean {
    return metric.trim().endsWith("_tokens")
  }

  /** Prix unitaire affiché : « 3,00 € / M » pour les tokens, sinon par unité. */
  function formatUnitPrice(metric: string, unitPrice: string | null): string {
    if (unitPrice == null) return "—"
    const n = Number(unitPrice)
    if (!Number.isFinite(n)) return "—"
    if (isTokenMetric(metric)) {
      return `${(n * 1_000_000).toLocaleString("fr-FR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })} € / M`
    }
    return `${n.toLocaleString("fr-FR", { maximumFractionDigits: 6 })} € / unité`
  }

  /** Chaîne décimale sans notation scientifique (ex. 3e-7 → "0.0000003"). */
  function toDecimalString(value: number): string {
    if (!Number.isFinite(value)) return "0"
    const fixed = value.toFixed(12)
    return fixed.includes(".") ? fixed.replace(/\.?0+$/, "") : fixed
  }

  // --- Grille de coûts ---
  const pricesQuery = createQuery(() => ({
    queryKey: ["admin", "prices"],
    queryFn: async () => {
      const { data, error } = await listUsagePrices()
      if (error || data === undefined) throw new Error("prices_load_failed")
      return data
    },
  }))
  // En erreur : grille vide (comme avant), avec le toast d'origine.
  const prices = $derived<UsagePrice[] | null>(
    pricesQuery.isError ? [] : (pricesQuery.data ?? null),
  )
  $effect(() => {
    if (pricesQuery.isError) {
      toast.error("Impossible de charger la grille de coûts.")
    }
  })

  // --- Consommations réellement enregistrées (source du sélecteur) ---
  // Le rapprochement tarif ↔ conso est une égalité stricte : proposer les
  // combos réels évite les tarifs « orphelins » (métrique mal orthographiée).
  const usageMetricsQuery = createQuery(() => ({
    queryKey: ["admin", "usage-metrics"],
    queryFn: async () => {
      const { data } = await listAdminUsageMetrics()
      return data ?? []
    },
  }))
  const usageMetrics = $derived<AdminUsageMetric[] | null>(
    usageMetricsQuery.data ?? null,
  )

  /** Rafraîchit grille et combos après une mutation (création, édition,
   *  suppression de tarif). */
  function invalidatePricing() {
    queryClient.invalidateQueries({ queryKey: ["admin", "prices"] })
    queryClient.invalidateQueries({ queryKey: ["admin", "usage-metrics"] })
  }

  const unpricedMetrics = $derived(
    (usageMetrics ?? []).filter((m) => !m.priced),
  )

  function comboLabel(m: AdminUsageMetric): string {
    return `${m.provider} · ${m.model ?? "tous les modèles"} · ${m.metric}`
  }

  // Formulaire inline créer/modifier : editingId === null → création.
  let formOpen = $state(false)
  let editingId = $state<number | null>(null)
  let formProvider = $state("")
  let formModel = $state("")
  let formMetric = $state("")
  // Pour les métriques tokens, la saisie est en € par million de tokens.
  let formPrice = $state("")
  let formError = $state<string | null>(null)
  let savingPrice = $state(false)

  // Sélection dans le picker : index dans usageMetrics, ou "manual" pour la
  // saisie libre (pré-provisionner une métrique pas encore consommée).
  let formSelection = $state("")
  const formIsManual = $derived(formSelection === "manual")

  function applySelection(value: string) {
    formSelection = value
    if (value === "manual") {
      formProvider = ""
      formModel = ""
      formMetric = ""
      return
    }
    const combo = (usageMetrics ?? [])[Number(value)]
    if (!combo) return
    formProvider = combo.provider
    formModel = combo.model ?? ""
    formMetric = combo.metric
  }

  const formIsTokenMetric = $derived(isTokenMetric(formMetric))

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

  /** « Tarifer » depuis la liste des consommations sans tarif : formulaire
   *  pré-rempli avec le combo exact, il ne reste que le prix à saisir. */
  function openCreateFor(combo: AdminUsageMetric) {
    openCreate()
    const index = (usageMetrics ?? []).indexOf(combo)
    applySelection(index >= 0 ? String(index) : "manual")
    if (index < 0) {
      formProvider = combo.provider
      formModel = combo.model ?? ""
      formMetric = combo.metric
    }
  }

  function openEdit(price: UsagePrice) {
    editingId = price.id
    // En modification les clés restent éditables (saisie libre) : c'est le
    // chemin de réparation d'un tarif orphelin existant.
    formSelection = "manual"
    formProvider = price.provider
    formModel = price.model ?? ""
    formMetric = price.metric
    const unit = Number(price.unit_price)
    formPrice = Number.isFinite(unit)
      ? String(isTokenMetric(price.metric) ? unit * 1_000_000 : unit)
      : ""
    formError = null
    formOpen = true
  }

  function closeForm() {
    formOpen = false
    editingId = null
    formError = null
  }

  async function submitPriceForm(event: SubmitEvent) {
    event.preventDefault()
    formError = null
    const provider = formProvider.trim()
    const metric = formMetric.trim()
    const priceValue = Number(String(formPrice).replace(",", "."))
    if (!provider || !metric) {
      formError = "Le provider et la métrique sont obligatoires."
      return
    }
    if (!Number.isFinite(priceValue) || priceValue < 0) {
      formError = "Le prix doit être un nombre positif."
      return
    }
    const body = {
      provider,
      model: formModel.trim() || null,
      metric,
      unit_price: toDecimalString(
        isTokenMetric(metric) ? priceValue / 1_000_000 : priceValue,
      ),
      currency: "EUR",
    }
    savingPrice = true
    if (editingId === null) {
      const { data, error } = await createUsagePrice(body)
      savingPrice = false
      if (error || data === undefined) {
        toast.error("Création du coût impossible.")
        return
      }
      toast.success("Coût enregistré")
    } else {
      const { data, error } = await updateUsagePrice(editingId, body)
      savingPrice = false
      if (error || data === undefined) {
        toast.error("Enregistrement du coût impossible.")
        return
      }
      toast.success("Coût mis à jour")
    }
    closeForm()
    invalidatePricing()
  }

  async function deletePrice(id: number) {
    const { error } = await deleteUsagePrice(id)
    if (error !== undefined) {
      toast.error("Suppression impossible.")
      return
    }
    if (editingId === id) closeForm()
    toast.success("Coût supprimé")
    invalidatePricing()
  }

  // --- Re-figement d'un mois facturé ---
  function monthOf(date: Date): string {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`
  }
  const currentMonth = monthOf(new Date())
  let refreezeMonth = $state("")
  let refreezing = $state(false)

  async function refreeze() {
    if (refreezeMonth === "") {
      toast.error("Choisissez le mois à re-figer.")
      return
    }
    refreezing = true
    const { data, error } = await refreezeUsageMonth(refreezeMonth)
    refreezing = false
    if (error || data === undefined) {
      const code = (error as { code?: string } | null)?.code
      toast.error(
        code === "not_frozen"
          ? "Ce mois n'est pas encore facturé — rien à re-figer."
          : "Re-figement impossible.",
      )
      return
    }
    toast.success(`Mois ${refreezeMonth} re-figé avec les tarifs actuels`)
  }
</script>

<RequireAdmin>
  {#snippet children(user)}
    <AppShell
      {appName}
      {user}
      breadcrumbs={[{ label: "Admin", href: "/admin" }, { label: "Coûts" }]}
    >
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <div class="flex flex-col gap-1">
          <h1 class="font-title text-lg font-bold">Coûts</h1>
          <p class="text-muted-foreground text-xs">
            Prix d'achat providers utilisés pour calculer les coûts réels —
            la tarification vendue aux clients vit sur la page « Tarification ».
          </p>
        </div>

        <!-- Consommations enregistrées qu'aucun tarif ne couvre -->
        {#if unpricedMetrics.length > 0}
          <div
            class="border-warning-dot/40 bg-warning flex flex-col gap-2 rounded-md border p-3"
            role="alert"
          >
            <span class="flex items-center gap-2 text-sm font-medium">
              <TriangleAlert size={15} class="text-warning-foreground shrink-0" aria-hidden="true" />
              {unpricedMetrics.length} consommation{unpricedMetrics.length > 1 ? "s" : ""}
              sans coût renseigné — comptées à zéro dans les coûts réels.
            </span>
            <ul class="flex flex-col gap-1.5">
              {#each unpricedMetrics as combo (comboLabel(combo))}
                <li class="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span class="font-mono">{comboLabel(combo)}</span>
                  <span class="flex items-center gap-2">
                    <span class="text-muted-foreground tabular-nums">
                      {combo.quantity.toLocaleString("fr-FR")} unités enregistrées
                    </span>
                    <Button size="sm" variant="outline" onclick={() => openCreateFor(combo)}>
                      Renseigner le coût
                    </Button>
                  </span>
                </li>
              {/each}
            </ul>
          </div>
        {/if}

        <!-- Grille de coûts -->
        <Card size="sm">
          <CardHeader>
            <CardTitle class="font-title flex items-center gap-2 text-sm">
              <ChartColumn size={14} aria-hidden="true" />
              Grille de coûts
            </CardTitle>
            <CardDescription class="text-muted-foreground text-xs">
              Prix d'achat appliqués pour calculer les coûts. Pour les métriques en
              tokens, le prix se saisit et s'affiche en € par million. Les
              modifications n'affectent que les mois non encore facturés.
            </CardDescription>
          </CardHeader>
          <CardContent class="flex flex-col gap-3">
            {#if prices === null}
              <Skeleton class="h-10 w-full" />
              <Skeleton class="h-10 w-full" />
            {:else}
              {#if prices.length === 0 && !formOpen}
                <p class="text-muted-foreground py-2 text-center text-sm">
                  Aucun coût pour l'instant — ajoutez par exemple le prix des
                  tokens d'entrée de votre modèle.
                </p>
              {:else if prices.length > 0}
                <div class="overflow-x-auto">
                  <table class="w-full min-w-xl text-sm">
                    <thead>
                      <tr class="border-border border-b">
                        <th class="text-muted-foreground px-3 py-2 text-left text-xs font-medium">Provider</th>
                        <th class="text-muted-foreground px-3 py-2 text-left text-xs font-medium">Modèle</th>
                        <th class="text-muted-foreground px-3 py-2 text-left text-xs font-medium">Métrique</th>
                        <th class="text-muted-foreground px-3 py-2 text-right text-xs font-medium">Prix</th>
                        <th class="px-3 py-2 text-right">
                          <span class="sr-only">Actions</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each prices as price (price.id)}
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
                          <td class="px-3 {cellPad} text-right whitespace-nowrap tabular-nums">
                            {formatUnitPrice(price.metric, price.unit_price)}
                          </td>
                          <td class="px-3 {cellPad} text-right whitespace-nowrap">
                            <div class="flex items-center justify-end gap-1">
                              <Button variant="ghost" size="sm" onclick={() => openEdit(price)}>
                                Modifier
                              </Button>
                              <ConfirmButton
                                label="Supprimer"
                                onconfirm={() => deletePrice(price.id)}
                              />
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
                  onsubmit={submitPriceForm}
                >
                  <span class="text-sm font-medium">
                    {editingId === null ? "Nouveau coût" : "Modifier le coût"}
                  </span>
                  <div class="grid gap-3 sm:grid-cols-2">
                    {#if editingId === null}
                      <!-- Le picker propose uniquement les combos réellement
                           enregistrés : le coût créé correspond forcément à
                           une consommation existante. -->
                      <div class="flex flex-col gap-1.5 sm:col-span-2">
                        <Label for="price-combo">Consommation</Label>
                        <Select
                          id="price-combo"
                          value={formSelection}
                          onchange={(e) => applySelection(e.currentTarget.value)}
                        >
                          <option value="" disabled>Choisir une consommation enregistrée…</option>
                          {#each usageMetrics ?? [] as combo, index (comboLabel(combo))}
                            <option value={String(index)}>
                              {comboLabel(combo)}{combo.priced ? "" : " — sans coût"}
                            </option>
                          {/each}
                          <option value="manual">Autre (saisie manuelle)…</option>
                        </Select>
                      </div>
                    {/if}
                    {#if formIsManual || editingId !== null}
                      <div class="flex flex-col gap-1.5">
                        <Label for="price-provider">Provider</Label>
                        <Input
                          id="price-provider"
                          placeholder="Ex. claude"
                          bind:value={formProvider}
                        />
                      </div>
                      <div class="flex flex-col gap-1.5">
                        <Label for="price-model">Modèle</Label>
                        <Input
                          id="price-model"
                          placeholder="Vide = tous les modèles"
                          bind:value={formModel}
                        />
                      </div>
                      <div class="flex flex-col gap-1.5">
                        <Label for="price-metric">Métrique</Label>
                        <Input
                          id="price-metric"
                          placeholder="Ex. input_tokens"
                          bind:value={formMetric}
                        />
                      </div>
                      <p class="text-muted-foreground text-xs sm:col-span-2">
                        Attention : provider et métrique doivent correspondre
                        exactement aux identifiants techniques enregistrés
                        (ex. <code>photoroom</code> / <code>images</code>),
                        sinon le coût ne s'appliquera pas.
                      </p>
                    {:else if formMetric}
                      <p class="text-muted-foreground text-xs sm:col-span-2">
                        Coût pour <span class="font-mono">{formProvider}
                          · {formModel || "tous les modèles"} · {formMetric}</span>
                      </p>
                    {/if}
                    <div class="flex flex-col gap-1.5">
                      <Label for="price-value">
                        {formIsTokenMetric ? "Prix (€ / million de tokens)" : "Prix (€ / unité)"}
                      </Label>
                      <Input
                        id="price-value"
                        type="number"
                        min="0"
                        step="any"
                        inputmode="decimal"
                        placeholder={formIsTokenMetric ? "Ex. 3,00" : "Ex. 0,01"}
                        bind:value={formPrice}
                      />
                      <p class="text-muted-foreground text-xs">
                        Pour les tokens, saisis le prix par million — il est
                        converti en prix unitaire à l'enregistrement.
                      </p>
                    </div>
                  </div>
                  {#if formError}
                    <p class="text-destructive text-xs" role="alert">{formError}</p>
                  {/if}
                  <div class="flex items-center justify-end gap-2">
                    <Button variant="ghost" size="sm" onclick={closeForm}>Annuler</Button>
                    <Button type="submit" size="sm" disabled={savingPrice}>
                      {savingPrice ? "Enregistrement…" : "Enregistrer"}
                    </Button>
                  </div>
                </form>
              {:else}
                <div>
                  <Button variant="outline" size="sm" onclick={openCreate}>
                    <Plus size={14} aria-hidden="true" data-icon="inline-start" />
                    Nouveau coût
                  </Button>
                </div>
              {/if}
            {/if}
          </CardContent>
        </Card>

        <!-- Re-figement d'un mois facturé -->
        <Card size="sm">
          <CardHeader>
            <CardTitle class="font-title text-sm">Re-figer un mois facturé</CardTitle>
            <CardDescription class="text-muted-foreground text-xs">
              Filet de sécurité : si un coût manquait à la clôture, corrigez la
              grille ci-dessus puis re-figez le mois avec les tarifs actuels.
            </CardDescription>
          </CardHeader>
          <CardContent class="flex flex-wrap items-end gap-3">
            <div class="flex flex-col gap-1.5">
              <Label for="refreeze-month">Mois</Label>
              <input
                id="refreeze-month"
                type="month"
                max={currentMonth}
                class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                bind:value={refreezeMonth}
              />
            </div>
            <ConfirmButton
              variant="outline"
              disabled={refreezing}
              label={refreezing ? "Re-figement…" : "Re-figer avec les coûts actuels"}
              confirmLabel="Confirmer le re-figement ?"
              onconfirm={refreeze}
            />
          </CardContent>
        </Card>
      </div>
    </AppShell>
  {/snippet}
</RequireAdmin>
