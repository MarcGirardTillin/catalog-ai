<script lang="ts">
  // Console admin — Tarification : la politique commerciale GLOBALE (tous
  // les clients). Les packs de crédits sont la tarification vendue ; la
  // grille par action explique comment les crédits se consomment. Les prix
  // d'achat providers (coûts réels) vivent sur la page « Coûts ».
  import { createQuery, useQueryClient } from "@tanstack/svelte-query"
  import Coins from "@lucide/svelte/icons/coins"
  import { toast } from "svelte-sonner"

  import {
    getOperatorSettings,
    putOperatorSettings,
    type OperatorSettings,
  } from "@/lib/api/admin"
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
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAdmin from "@/lib/components/app/RequireAdmin.svelte"

  let { appName }: { appName: string } = $props()

  const queryClient = useQueryClient()

  // Le formulaire édite une copie locale hydratée une fois depuis la query.
  let settings = $state<OperatorSettings | null>(null)
  let saving = $state(false)

  const settingsQuery = createQuery(() => ({
    queryKey: ["admin", "operator-settings"],
    queryFn: async () => {
      const { data, error } = await getOperatorSettings()
      if (error || !data) throw new Error("operator_settings_load_failed")
      return data
    },
  }))
  $effect(() => {
    const data = settingsQuery.data
    if (data) settings = { ...data, credit_packs: [...(data.credit_packs ?? [])] }
  })
  $effect(() => {
    if (settingsQuery.isError) {
      toast.error("Impossible de charger la tarification.")
    }
  })

  function addPack() {
    if (!settings) return
    settings.credit_packs = [
      ...(settings.credit_packs ?? []),
      { credits: 100, price_eur: 10 },
    ]
  }
  function removePack(index: number) {
    if (!settings) return
    settings.credit_packs = (settings.credit_packs ?? []).filter(
      (_, i) => i !== index,
    )
  }

  async function save() {
    if (!settings || saving) return
    const ints = {
      credit_cost_import_product: settings.credit_cost_import_product,
      credit_cost_enrich_item: settings.credit_cost_enrich_item,
      credit_cost_image_process: settings.credit_cost_image_process,
      credit_cost_image_generate: settings.credit_cost_image_generate,
      monthly_free_credits: settings.monthly_free_credits,
      low_credit_threshold: settings.low_credit_threshold,
      minutes_saved_per_import_product: settings.minutes_saved_per_import_product,
      minutes_saved_per_enriched_product: settings.minutes_saved_per_enriched_product,
    }
    const normalized: Record<string, number> = {}
    for (const [key, raw] of Object.entries(ints)) {
      const value = Math.round(Number(raw))
      if (!Number.isFinite(value) || value < 0) {
        toast.error("Les valeurs doivent être des entiers positifs.")
        return
      }
      normalized[key] = value
    }
    const billingDay = Math.round(Number(settings.billing_day))
    if (!Number.isFinite(billingDay) || billingDay < 1 || billingDay > 28) {
      toast.error("Le jour de facturation doit être compris entre 1 et 28.")
      return
    }
    normalized.billing_day = billingDay
    const packs = (settings.credit_packs ?? [])
      .map((pack) => ({
        credits: Math.round(Number(pack.credits)),
        price_eur: Number(pack.price_eur),
      }))
      .filter((pack) => Number.isFinite(pack.credits) && pack.credits > 0)
    if (packs.some((pack) => !Number.isFinite(pack.price_eur) || pack.price_eur < 0)) {
      toast.error("Chaque pack doit avoir un prix positif ou nul.")
      return
    }
    saving = true
    const { data, error } = await putOperatorSettings({
      ...settings,
      ...normalized,
      credit_packs: packs,
    })
    saving = false
    if (error || !data) {
      toast.error("Enregistrement de la tarification impossible.")
      return
    }
    settings = { ...data, credit_packs: [...(data.credit_packs ?? [])] }
    toast.success("Tarification enregistrée pour tous les clients")
    queryClient.invalidateQueries({ queryKey: ["admin", "operator-settings"] })
    // Le seuil/quota changent l'affichage des crédits partout.
    queryClient.invalidateQueries({ queryKey: ["credits"] })
    queryClient.invalidateQueries({ queryKey: ["stats", "dashboard"] })
  }

  /** Valeur d'un pack en € par crédit (contrôle visuel de cohérence). */
  function packUnitPrice(pack: { credits: number; price_eur: number }): string {
    const credits = Number(pack.credits)
    const price = Number(pack.price_eur)
    if (!Number.isFinite(credits) || credits <= 0 || !Number.isFinite(price))
      return "—"
    return `${(price / credits).toLocaleString("fr-FR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 3,
    })} € / crédit`
  }
</script>

<RequireAdmin>
  {#snippet children(user)}
    <AppShell
      {appName}
      {user}
      breadcrumbs={[{ label: "Admin", href: "/admin" }, { label: "Tarification" }]}
    >
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <div class="flex flex-col gap-1">
          <h1 class="font-title text-lg font-bold">Tarification</h1>
          <p class="text-muted-foreground text-xs">
            Politique commerciale appliquée à TOUS les clients. Les coûts
            d'achat providers vivent sur la page « Coûts ».
          </p>
        </div>

        {#if settings === null}
          <Skeleton class="h-40 w-full" />
          <Skeleton class="h-40 w-full" />
        {:else}
          <!-- Packs de crédits = la tarification vendue au client -->
          <Card size="sm">
            <CardHeader>
              <div class="flex items-center justify-between gap-2">
                <div class="flex flex-col gap-1.5">
                  <CardTitle class="font-title flex items-center gap-2 text-sm">
                    <Coins size={14} aria-hidden="true" />
                    Packs de crédits
                  </CardTitle>
                  <CardDescription class="text-muted-foreground text-xs">
                    La tarification affichée aux clients sur leur page
                    Consommation. Les achats sont enregistrés manuellement
                    depuis la fiche client.
                  </CardDescription>
                </div>
                <Button size="sm" variant="outline" onclick={addPack}>
                  Ajouter un pack
                </Button>
              </div>
            </CardHeader>
            <CardContent class="flex flex-col gap-2">
              {#if (settings.credit_packs ?? []).length === 0}
                <p class="text-muted-foreground text-xs">
                  Aucun pack — les clients ne voient aucune offre de recharge.
                </p>
              {:else}
                {#each settings.credit_packs ?? [] as pack, index (index)}
                  <div class="grid grid-cols-[1fr_1fr_auto_auto] items-end gap-3">
                    <div class="flex flex-col gap-1.5">
                      <Label for={`pack-credits-${index}`}>Crédits</Label>
                      <Input
                        id={`pack-credits-${index}`}
                        type="number"
                        min="1"
                        step="1"
                        inputmode="numeric"
                        bind:value={pack.credits}
                      />
                    </div>
                    <div class="flex flex-col gap-1.5">
                      <Label for={`pack-price-${index}`}>Prix €</Label>
                      <Input
                        id={`pack-price-${index}`}
                        type="number"
                        min="0"
                        step="0.01"
                        bind:value={pack.price_eur}
                      />
                    </div>
                    <span class="text-muted-foreground pb-2 text-xs whitespace-nowrap tabular-nums">
                      {packUnitPrice(pack)}
                    </span>
                    <Button
                      size="sm"
                      variant="ghost"
                      class="text-destructive"
                      onclick={() => removePack(index)}
                    >
                      Retirer
                    </Button>
                  </div>
                {/each}
              {/if}
            </CardContent>
          </Card>

          <!-- Grille de consommation : combien coûte chaque action, en crédits -->
          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">
                Consommation des crédits par action
              </CardTitle>
              <CardDescription class="text-muted-foreground text-xs">
                Combien chaque action débite du solde. Le re-render
                (repositionnement) d'une image reste gratuit ; un traitement
                échoué ne consomme rien.
              </CardDescription>
            </CardHeader>
            <CardContent class="grid gap-3 sm:grid-cols-4">
              <div class="flex flex-col gap-1.5">
                <Label for="op-cr-import">Produit importé</Label>
                <Input
                  id="op-cr-import"
                  type="number"
                  min="0"
                  step="1"
                  inputmode="numeric"
                  bind:value={settings.credit_cost_import_product}
                />
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for="op-cr-enrich">Fiche enrichie</Label>
                <Input
                  id="op-cr-enrich"
                  type="number"
                  min="0"
                  step="1"
                  inputmode="numeric"
                  bind:value={settings.credit_cost_enrich_item}
                />
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for="op-cr-image">Image traitée</Label>
                <Input
                  id="op-cr-image"
                  type="number"
                  min="0"
                  step="1"
                  inputmode="numeric"
                  bind:value={settings.credit_cost_image_process}
                />
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for="op-cr-generate">Visuel généré</Label>
                <Input
                  id="op-cr-generate"
                  type="number"
                  min="0"
                  step="1"
                  inputmode="numeric"
                  bind:value={settings.credit_cost_image_generate}
                />
              </div>
            </CardContent>
          </Card>

          <!-- Abonnement + alerte + facturation (déplacé des paramètres
               client 2026-07-16 : politique opérateur, pas réglage boutique) -->
          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">Abonnement & facturation</CardTitle>
            </CardHeader>
            <CardContent class="grid gap-3 sm:grid-cols-3">
              <div class="flex flex-col gap-1.5">
                <Label for="op-monthly">Crédits mensuels inclus</Label>
                <Input
                  id="op-monthly"
                  type="number"
                  min="0"
                  step="1"
                  inputmode="numeric"
                  bind:value={settings.monthly_free_credits}
                />
                <p class="text-muted-foreground text-xs">
                  Octroyés automatiquement une fois par mois (0 = aucun).
                </p>
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for="op-threshold">Seuil d'alerte solde bas</Label>
                <Input
                  id="op-threshold"
                  type="number"
                  min="0"
                  step="1"
                  inputmode="numeric"
                  bind:value={settings.low_credit_threshold}
                />
                <p class="text-muted-foreground text-xs">
                  Sous ce solde, pastille ambre et bandeau d'alerte côté client.
                </p>
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for="op-billing-day">Jour de facturation</Label>
                <Input
                  id="op-billing-day"
                  type="number"
                  min="1"
                  max="28"
                  step="1"
                  inputmode="numeric"
                  bind:value={settings.billing_day}
                />
                <p class="text-muted-foreground text-xs">
                  Entre 1 et 28 : la consommation d'un mois est facturée (et ses
                  coûts figés) ce jour du mois suivant.
                </p>
              </div>
            </CardContent>
          </Card>

          <!-- Minutes « temps gagné » du tableau de bord client -->
          <Card size="sm">
            <CardHeader>
              <CardTitle class="font-title text-sm">Temps gagné (tableau de bord)</CardTitle>
              <CardDescription class="text-muted-foreground text-xs">
                Minutes créditées au compteur « temps gagné » du tableau de
                bord client, par fiche créée et par fiche enrichie.
              </CardDescription>
            </CardHeader>
            <CardContent class="grid gap-3 sm:grid-cols-2">
              <div class="flex flex-col gap-1.5">
                <Label for="op-min-import">Min. gagnées / fiche créée</Label>
                <Input
                  id="op-min-import"
                  type="number"
                  min="0"
                  max="120"
                  step="1"
                  inputmode="numeric"
                  bind:value={settings.minutes_saved_per_import_product}
                />
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for="op-min-enrich">Min. gagnées / fiche enrichie</Label>
                <Input
                  id="op-min-enrich"
                  type="number"
                  min="0"
                  max="120"
                  step="1"
                  inputmode="numeric"
                  bind:value={settings.minutes_saved_per_enriched_product}
                />
              </div>
            </CardContent>
          </Card>

          <div class="flex justify-end">
            <Button disabled={saving} onclick={save}>
              {saving ? "Enregistrement…" : "Enregistrer pour tous les clients"}
            </Button>
          </div>
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAdmin>
