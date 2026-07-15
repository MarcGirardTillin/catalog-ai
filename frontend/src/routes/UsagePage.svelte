<script lang="ts">
  // Page Consommation (vue CLIENT, marque blanche) : montants facturables du
  // mois, courbe quotidienne totale, détail par service et par job, export CSV.
  // Tout ce qui est opérateur (grille tarifaire, coefficient, re-figement,
  // vues par modèle/provider) vit dans la section /admin — et le backend
  // expurge de toute façon les réponses des non-admins.
  import { createQuery } from "@tanstack/svelte-query"
  import ChartColumn from "@lucide/svelte/icons/chart-column"
  import Download from "@lucide/svelte/icons/download"
  import Lock from "@lucide/svelte/icons/lock"
  import { toast } from "svelte-sonner"

  import { navigate } from "svelte5-router"

  import { listAssets } from "@/lib/api/imaging"
  import {
    getUsageExport,
    getUsageSummary,
    getUsageTimeseries,
  } from "@/lib/api/usage"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent, CardHeader, CardTitle } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import AssetThumb from "@/lib/components/imaging/AssetThumb.svelte"
  import UsageChart from "@/lib/components/usage/UsageChart.svelte"
  import { IMAGE_SERVICE_LABEL, toServiceLabel } from "@/lib/usageLabels"

  let { appName }: { appName: string } = $props()

  // --- Mois sélectionné (AAAA-MM, borné au mois courant) ---
  function monthOf(date: Date): string {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`
  }
  const currentMonth = monthOf(new Date())
  let month = $state(monthOf(new Date()))

  // --- Données du mois (TanStack Query : le mois est dans la clé, changer
  // de mois refetch automatiquement) ---
  const summaryQuery = createQuery(() => ({
    queryKey: ["usage", "summary", month],
    queryFn: async () => {
      const { data, error } = await getUsageSummary(month)
      if (error || data === undefined) throw new Error("usage_summary_load_failed")
      return data
    },
  }))
  const summary = $derived(summaryQuery.data ?? null)
  const loadFailed = $derived(summaryQuery.isError)

  // --- Série temporelle quotidienne (courbe totale uniquement) ---
  const timeseriesQuery = createQuery(() => ({
    queryKey: ["usage", "timeseries", month, "none"],
    queryFn: async () => {
      const { data, error } = await getUsageTimeseries(month, "none")
      if (error || data === undefined) throw new Error("usage_timeseries_load_failed")
      return data
    },
  }))
  const timeseries = $derived(timeseriesQuery.data ?? null)
  const tsFailed = $derived(timeseriesQuery.isError)

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

  /** Étiquette de date longue fr-FR depuis "YYYY-MM-DD". */
  function formatLongDate(iso: string): string {
    const d = new Date(`${iso}T00:00:00`)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleDateString("fr-FR", {
      day: "numeric",
      month: "long",
      year: "numeric",
    })
  }

  // --- Formatage fr-FR ---
  const currency = $derived(summary?.currency ?? "EUR")

  /** "12,34 €" depuis une chaîne décimale JSON, "—" si null/invalide. */
  function formatAmount(value: string | null): string {
    if (value == null) return "—"
    const n = Number(value)
    if (!Number.isFinite(n)) return "—"
    return n.toLocaleString("fr-FR", { style: "currency", currency })
  }

  function formatInt(n: number): string {
    return n.toLocaleString("fr-FR")
  }

  // Deux compteurs client, sans vocabulaire technique : « Crédits de
  // génération » (texte + recherches, en unités opaques) et « Images
  // traitées ». Le pivot est le libellé de service — normalisé, car un admin
  // reçoit ici le payload complet (providers bruts) là où un client reçoit
  // les libellés déjà expurgés.
  const imagesTotal = $derived(
    summary?.lines
      .filter((l) => toServiceLabel(l.provider) === IMAGE_SERVICE_LABEL)
      .reduce((acc, l) => acc + l.quantity, 0) ?? null,
  )
  const creditsTotal = $derived(
    summary?.lines
      .filter((l) => toServiceLabel(l.provider) !== IMAGE_SERVICE_LABEL)
      .reduce((acc, l) => acc + l.quantity, 0) ?? null,
  )

  // --- Export CSV (blob → ancre de téléchargement) ---
  let exporting = $state(false)

  async function exportCsv() {
    exporting = true
    const { data, error } = await getUsageExport(month)
    exporting = false
    if (error || !(data instanceof Blob)) {
      toast.error("Export du CSV impossible.")
      return
    }
    const url = URL.createObjectURL(data)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `consommation_${month}.csv`
    anchor.click()
    URL.revokeObjectURL(url)
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
            <Button
              variant="outline"
              size="sm"
              disabled={exporting || summary === null}
              onclick={exportCsv}
            >
              <Download size={14} aria-hidden="true" data-icon="inline-start" />
              {exporting ? "Export…" : "Exporter le CSV"}
            </Button>
          </div>
        </div>

        {#if loadFailed}
          <p class="text-destructive text-xs" role="alert">
            Impossible de charger la consommation du mois.
          </p>
        {:else if summary === null}
          <div class="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
          </div>
          <Skeleton class="h-32 w-full" />
          <Skeleton class="h-32 w-full" />
        {:else}
          <!-- Bandeau de statut du mois (facturé ou à venir) -->
          {#if summary.frozen}
            <div
              class="border-border bg-muted/40 flex items-start gap-2.5 rounded-md border p-3 text-sm"
            >
              <Lock
                size={16}
                class="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-500"
                aria-hidden="true"
              />
              <span class="font-medium">
                Mois facturé le {formatLongDate(summary.billing_date)}.
              </span>
            </div>
          {:else}
            <div
              class="border-border bg-muted/40 flex items-start gap-2.5 rounded-md border p-3 text-sm"
            >
              <ChartColumn
                size={16}
                class="text-muted-foreground mt-0.5 shrink-0"
                aria-hidden="true"
              />
              <span>Sera facturé le {formatLongDate(summary.billing_date)}.</span>
            </div>
          {/if}

          <!-- Cartes de synthèse -->
          <div class="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <Card size="sm">
              <CardContent class="flex flex-col gap-1 py-4">
                <span class="text-muted-foreground text-xs">Consommation du mois</span>
                <span class="text-foreground text-2xl font-semibold tabular-nums sm:text-3xl">
                  {formatAmount(summary.totals.billable)}
                </span>
              </CardContent>
            </Card>
            <Card size="sm">
              <CardContent class="flex flex-col gap-1 py-4">
                <span class="text-muted-foreground text-xs">Crédits de génération</span>
                <span class="text-foreground text-2xl font-semibold tabular-nums sm:text-3xl">
                  {creditsTotal != null ? formatInt(creditsTotal) : "—"}
                </span>
              </CardContent>
            </Card>
            <Card size="sm">
              <CardContent class="flex flex-col gap-1 py-4">
                <span class="text-muted-foreground text-xs">Images traitées</span>
                <span class="text-foreground text-2xl font-semibold tabular-nums sm:text-3xl">
                  {imagesTotal != null ? formatInt(imagesTotal) : "—"}
                </span>
              </CardContent>
            </Card>
          </div>

          <!-- Évolution quotidienne (graphique SVG inline, total) -->
          <Card size="sm" class="mt-1">
            <CardHeader>
              <CardTitle class="font-title text-sm">Évolution quotidienne</CardTitle>
            </CardHeader>
            <CardContent class="flex flex-col gap-3">
              <UsageChart {timeseries} failed={tsFailed} {month} />
            </CardContent>
          </Card>

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
