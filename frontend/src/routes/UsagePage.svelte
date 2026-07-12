<script lang="ts">
  // Page Consommation (vue CLIENT, marque blanche) : montants facturables du
  // mois, courbe quotidienne totale, détail par service et par job, export CSV.
  // Tout ce qui est opérateur (grille tarifaire, coefficient, re-figement,
  // vues par modèle/provider) vit dans la section /admin — et le backend
  // expurge de toute façon les réponses des non-admins.
  import ChartColumn from "@lucide/svelte/icons/chart-column"
  import Download from "@lucide/svelte/icons/download"
  import Lock from "@lucide/svelte/icons/lock"
  import { toast } from "svelte-sonner"

  import {
    getUsageExport,
    getUsageSummary,
    getUsageTimeseries,
  } from "@/lib/api/usage"
  import type { UsageSummary, UsageTimeseries } from "@/lib/api/usage"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent, CardHeader, CardTitle } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import UsageChart from "@/lib/components/usage/UsageChart.svelte"
  import { IMAGE_SERVICE_LABEL } from "@/lib/usageLabels"

  let { appName }: { appName: string } = $props()

  // --- Mois sélectionné (AAAA-MM, borné au mois courant) ---
  function monthOf(date: Date): string {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`
  }
  const currentMonth = monthOf(new Date())
  let month = $state(monthOf(new Date()))

  // --- Données du mois ---
  let summary = $state<UsageSummary | null>(null)
  let loadFailed = $state(false)

  async function loadMonth() {
    summary = null
    loadFailed = false
    const target = month
    const { data, error } = await getUsageSummary(target)
    if (target !== month) return // le mois a changé entre-temps
    if (error || data === undefined) {
      loadFailed = true
      toast.error("Impossible de charger la consommation du mois.")
      return
    }
    summary = data
  }

  $effect(() => {
    void month // recharge à chaque changement de mois
    loadMonth()
  })

  // --- Série temporelle quotidienne (courbe totale uniquement) ---
  let timeseries = $state<UsageTimeseries | null>(null)
  let tsFailed = $state(false)

  async function loadTimeseries() {
    const targetMonth = month
    timeseries = null
    tsFailed = false
    const { data, error } = await getUsageTimeseries(targetMonth, "none")
    if (targetMonth !== month) return // rechangé
    if (error || data === undefined) {
      tsFailed = true
      return
    }
    timeseries = data
  }

  $effect(() => {
    void month
    loadTimeseries()
  })

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
  // traitées ». Le pivot est le libellé de service neutre renvoyé par le
  // backend expurgé (line.provider = service).
  const imagesTotal = $derived(
    summary?.lines
      .filter((l) => l.provider === IMAGE_SERVICE_LABEL)
      .reduce((acc, l) => acc + l.quantity, 0) ?? null,
  )
  const creditsTotal = $derived(
    summary?.lines
      .filter((l) => l.provider !== IMAGE_SERVICE_LABEL)
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

        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
