<script lang="ts">
  // Page Consommation (vue CLIENT, marque blanche) : modèle CRÉDITS prépayés.
  // Solde, consommation du mois par action, courbe quotidienne en crédits,
  // packs disponibles, mouvements du mois et historique des générations.
  // Les montants € (coûts, marge, grille) restent réservés à la section
  // /admin — seul le prix des packs est visible ici.
  import { createQuery } from "@tanstack/svelte-query"
  import Coins from "@lucide/svelte/icons/coins"
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert"
  import { navigate } from "svelte5-router"

  import {
    getCredits,
    getCreditTimeseries,
    type CreditEntryPublic,
  } from "@/lib/api/credits"
  import { listAssets } from "@/lib/api/imaging"
  import type { UsageTimeseries } from "@/lib/api/usage"
  import { Card, CardContent, CardHeader, CardTitle } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import AssetThumb from "@/lib/components/imaging/AssetThumb.svelte"
  import UsageChart from "@/lib/components/usage/UsageChart.svelte"

  let { appName }: { appName: string } = $props()

  // --- Mois sélectionné (AAAA-MM, borné au mois courant) ---
  function monthOf(date: Date): string {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`
  }
  const currentMonth = monthOf(new Date())
  let month = $state(monthOf(new Date()))

  // --- Solde + agrégats du mois (le mois est dans la clé de query) ---
  const creditsQuery = createQuery(() => ({
    queryKey: ["credits", month],
    queryFn: async () => {
      const { data, error } = await getCredits(month)
      if (error || !data) throw new Error("credits_load_failed")
      return data
    },
  }))
  const credits = $derived(creditsQuery.data ?? null)
  const loadFailed = $derived(creditsQuery.isError)

  // --- Série quotidienne en crédits, adaptée à la forme UsageChart ---
  const timeseriesQuery = createQuery(() => ({
    queryKey: ["credits", "timeseries", month],
    queryFn: async () => {
      const { data, error } = await getCreditTimeseries(month)
      if (error || !data) throw new Error("credit_timeseries_load_failed")
      return data
    },
  }))
  const timeseries = $derived.by<UsageTimeseries | null>(() => {
    const ts = timeseriesQuery.data
    if (!ts) return null
    return {
      month: ts.month,
      group_by: "action",
      currency: "EUR", // ignoré : le graphique est rendu avec unit="credits"
      series: ts.series.map((s) => ({
        key: s.key,
        points: s.points.map((p) => ({
          date: p.date,
          amount: String(p.credits ?? 0),
          quantity: p.credits ?? 0,
        })),
      })),
    }
  })
  const tsFailed = $derived(timeseriesQuery.isError)

  // --- Tuiles de consommation par action ---
  const ACTION_TILES: { key: string; label: string }[] = [
    { key: "import_product", label: "Produits importés" },
    { key: "enrich_item", label: "Fiches enrichies" },
    { key: "image_process", label: "Images traitées" },
    { key: "image_generate", label: "Visuels générés" },
  ]

  // Alerte de solde : rouge à 0, ambre sous le seuil.
  const balanceTone = $derived.by(() => {
    if (!credits) return "text-foreground"
    if (credits.balance <= 0) return "text-destructive"
    if (credits.balance < credits.low_credit_threshold)
      return "text-amber-600 dark:text-amber-400"
    return "text-foreground"
  })

  const CREDIT_KIND_LABELS: Record<string, string> = {
    purchase: "Achat de pack",
    grant: "Crédits offerts",
    subscription: "Crédits mensuels",
    adjustment: "Ajustement",
  }
  function creditKindLabel(entry: CreditEntryPublic): string {
    return CREDIT_KIND_LABELS[entry.kind] ?? entry.kind
  }

  // --- Historique des générations mannequin du mois (revenir dessus) ---
  const generationsQuery = createQuery(() => ({
    queryKey: ["imaging", "assets", "generations", month],
    queryFn: async () => {
      const { data, error } = await listAssets({ verb: "generate_model", month })
      if (error || !data) throw new Error("generations_load_failed")
      return data
    },
  }))
  const generations = $derived(generationsQuery.data ?? null)

  const GENERATION_STATUS: Record<string, { label: string; tone: string }> = {
    completed: {
      label: "À vérifier",
      tone: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
    },
    saved: {
      label: "Enregistrée",
      tone: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
    },
    discarded: { label: "Écartée", tone: "bg-muted text-muted-foreground" },
    failed: { label: "Échec", tone: "bg-destructive/15 text-destructive" },
    pending: { label: "En cours", tone: "bg-muted text-muted-foreground" },
    processing: { label: "En cours", tone: "bg-muted text-muted-foreground" },
  }

  function generationStatus(asset: {
    status: string
    saved?: boolean
  }): { label: string; tone: string } {
    if (asset.saved) return GENERATION_STATUS.saved
    return GENERATION_STATUS[asset.status] ?? GENERATION_STATUS.pending
  }

  /** "12 juil. 2026, 14:02" depuis un ISO datetime. */
  function formatDateTime(iso: string): string {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleDateString("fr-FR", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  function formatInt(n: number): string {
    return n.toLocaleString("fr-FR")
  }

  function formatEur(n: number): string {
    return n.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Consommation" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h1 class="font-title text-lg font-bold">Consommation</h1>
          <div class="flex items-center gap-2">
            <label class="sr-only" for="usage-month">Mois</label>
            <input
              id="usage-month"
              type="month"
              max={currentMonth}
              class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
              bind:value={month}
            />
          </div>
        </div>

        {#if loadFailed}
          <p class="text-destructive text-xs" role="alert">
            Impossible de charger la consommation du mois.
          </p>
        {:else if credits === null}
          <div class="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
          </div>
          <Skeleton class="h-32 w-full" />
          <Skeleton class="h-32 w-full" />
        {:else}
          <!-- Alerte solde épuisé / bas -->
          {#if credits.balance <= 0}
            <div
              class="border-destructive/40 bg-destructive/10 flex items-start gap-2.5 rounded-md border p-3 text-sm"
              role="alert"
            >
              <TriangleAlert size={16} class="text-destructive mt-0.5 shrink-0" aria-hidden="true" />
              <span class="font-medium">
                Crédits épuisés — les nouveaux traitements sont bloqués.
                Contactez-nous pour recharger votre compte.
              </span>
            </div>
          {:else if credits.balance < credits.low_credit_threshold}
            <div
              class="flex items-start gap-2.5 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm"
            >
              <TriangleAlert
                size={16}
                class="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400"
                aria-hidden="true"
              />
              <span>
                Solde bas : il vous reste {formatInt(credits.balance)} crédits.
              </span>
            </div>
          {/if}

          <!-- Solde + consommation du mois par action -->
          <div class="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Card size="sm">
              <CardContent class="flex flex-col gap-1 py-4">
                <span class="text-muted-foreground flex items-center gap-1.5 text-xs">
                  <Coins size={13} aria-hidden="true" />
                  Solde de crédits
                </span>
                <span class="text-2xl font-semibold tabular-nums sm:text-3xl {balanceTone}">
                  {formatInt(credits.balance)}
                </span>
              </CardContent>
            </Card>
            {#each ACTION_TILES as tile (tile.key)}
              <Card size="sm">
                <CardContent class="flex flex-col gap-1 py-4">
                  <span class="text-muted-foreground text-xs">{tile.label}</span>
                  <span class="text-foreground text-2xl font-semibold tabular-nums sm:text-3xl">
                    {formatInt(credits.month.by_action?.[tile.key] ?? 0)}
                  </span>
                </CardContent>
              </Card>
            {/each}
          </div>

          <!-- Évolution quotidienne des crédits consommés -->
          <Card size="sm" class="mt-1">
            <CardHeader>
              <div class="flex flex-wrap items-baseline justify-between gap-2">
                <CardTitle class="font-title text-sm">Évolution quotidienne</CardTitle>
                <span class="text-muted-foreground text-xs">
                  {formatInt(credits.month.consumed_total ?? 0)} crédits consommés ce mois
                </span>
              </div>
            </CardHeader>
            <CardContent class="flex flex-col gap-3">
              <UsageChart {timeseries} failed={tsFailed} {month} unit="credits" />
            </CardContent>
          </Card>

          <!-- Packs de crédits disponibles -->
          {#if (credits.packs ?? []).length > 0}
            <Card size="sm" class="mt-1">
              <CardHeader>
                <CardTitle class="font-title text-sm">Packs de crédits</CardTitle>
              </CardHeader>
              <CardContent>
                <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                  {#each credits.packs ?? [] as pack, index (index)}
                    <div class="border-border flex flex-col gap-0.5 rounded-md border p-3">
                      <span class="text-foreground text-lg font-semibold tabular-nums">
                        {formatInt(pack.credits)} crédits
                      </span>
                      <span class="text-muted-foreground text-xs tabular-nums">
                        {formatEur(pack.price_eur)}
                      </span>
                    </div>
                  {/each}
                </div>
                <p class="text-muted-foreground mt-2 text-xs">
                  Pour recharger votre compte, contactez votre interlocuteur —
                  les crédits sont ajoutés à réception.
                </p>
              </CardContent>
            </Card>
          {/if}

          <!-- Mouvements du mois (achats, octrois, allocation mensuelle) -->
          {#if (credits.entries ?? []).length > 0}
            <Card size="sm" class="mt-1">
              <CardHeader>
                <CardTitle class="font-title text-sm">Mouvements du mois</CardTitle>
              </CardHeader>
              <CardContent class="px-0">
                <div class="overflow-x-auto">
                  <table class="w-full min-w-md text-sm">
                    <thead>
                      <tr class="border-border border-b">
                        <th class="text-muted-foreground px-4 py-2 text-left text-xs font-medium">Date</th>
                        <th class="text-muted-foreground px-4 py-2 text-left text-xs font-medium">Type</th>
                        <th class="text-muted-foreground px-4 py-2 text-left text-xs font-medium">Libellé</th>
                        <th class="text-muted-foreground px-4 py-2 text-right text-xs font-medium">Crédits</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each credits.entries ?? [] as entry (entry.id)}
                        <tr class="border-border border-b last:border-b-0">
                          <td class="text-muted-foreground px-4 py-1.5 text-xs whitespace-nowrap tabular-nums">
                            {formatDateTime(entry.created_at)}
                          </td>
                          <td class="px-4 py-1.5 text-xs whitespace-nowrap">
                            {creditKindLabel(entry)}
                          </td>
                          <td class="text-muted-foreground max-w-60 truncate px-4 py-1.5 text-xs">
                            {entry.label ?? "—"}
                          </td>
                          <td class="px-4 py-1.5 text-right font-medium whitespace-nowrap tabular-nums {entry.credits < 0 ? 'text-destructive' : 'text-emerald-600 dark:text-emerald-400'}">
                            {entry.credits > 0 ? `+${formatInt(entry.credits)}` : formatInt(entry.credits)}
                          </td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          {/if}

          <!-- Historique des générations mannequin (revenir sur un visuel) -->
          <Card size="sm" class="mt-1">
            <CardHeader>
              <CardTitle class="font-title text-sm">Générations mannequin</CardTitle>
            </CardHeader>
            <CardContent class="px-0">
              {#if generationsQuery.isError}
                <p class="text-destructive px-6 text-xs" role="alert">
                  Impossible de charger l'historique des générations.
                </p>
              {:else if generations === null}
                <div class="flex flex-col gap-2 px-6">
                  <Skeleton class="h-8 w-full" />
                  <Skeleton class="h-8 w-full" />
                </div>
              {:else if generations.length === 0}
                <p class="text-muted-foreground px-6 text-sm">
                  Aucun visuel généré ce mois-ci.
                </p>
              {:else}
                <div class="overflow-x-auto">
                  <table class="w-full min-w-lg text-sm">
                    <thead>
                      <tr class="border-border border-b">
                        <th class="text-muted-foreground px-4 py-2 text-left text-xs font-medium" colspan="2">Visuel</th>
                        <th class="text-muted-foreground px-4 py-2 text-left text-xs font-medium">Produit</th>
                        <th class="text-muted-foreground px-4 py-2 text-left text-xs font-medium">Statut</th>
                        <th class="text-muted-foreground px-4 py-2 text-right text-xs font-medium">Visuels</th>
                        <th class="text-muted-foreground px-4 py-2 text-right text-xs font-medium">Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each generations as asset (asset.id)}
                        {@const status = generationStatus(asset)}
                        <tr
                          class="border-border hover:bg-muted/50 cursor-pointer border-b transition-colors last:border-b-0"
                          role="link"
                          tabindex="0"
                          aria-label={`Ouvrir le studio du produit #${asset.product_id}`}
                          onclick={() => navigate(`/products/${asset.product_id}/images`)}
                          onkeydown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault()
                              navigate(`/products/${asset.product_id}/images`)
                            }
                          }}
                        >
                          <td class="py-1.5 pl-4">
                            <AssetThumb {asset} />
                          </td>
                          <td class="text-muted-foreground px-4 py-1.5 text-xs">
                            #{asset.id}
                          </td>
                          <td class="px-4 py-1.5 whitespace-nowrap">
                            Produit #{asset.product_id}
                          </td>
                          <td class="px-4 py-1.5">
                            <span
                              class="rounded-full px-2 py-0.5 text-[11px] whitespace-nowrap {status.tone}"
                            >
                              {status.label}
                            </span>
                          </td>
                          <td class="px-4 py-1.5 text-right tabular-nums">
                            {asset.files?.length || asset.preview_urls?.length || 1}
                          </td>
                          <td class="text-muted-foreground px-4 py-1.5 text-right text-xs whitespace-nowrap tabular-nums">
                            {formatDateTime(asset.created_at)}
                          </td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              {/if}
            </CardContent>
          </Card>
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
