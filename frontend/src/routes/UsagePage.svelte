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
  import { navigate } from "svelte5-router"

  import {
    getUsageByJob,
    getUsageExport,
    getUsageSummary,
    getUsageTimeseries,
  } from "@/lib/api/usage"
  import type { UsageByJob, UsageSummary, UsageTimeseries } from "@/lib/api/usage"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent, CardHeader, CardTitle } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import { formatRelativeDate } from "@/lib/format"
  import { prefs } from "@/lib/preferences.svelte"

  let { appName }: { appName: string } = $props()

  // Densité des tables : padding vertical des cellules selon la préférence.
  const cellPad = $derived(prefs.density === "compact" ? "py-1" : "py-2.5")

  // --- Mois sélectionné (AAAA-MM, borné au mois courant) ---
  function monthOf(date: Date): string {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`
  }
  const currentMonth = monthOf(new Date())
  let month = $state(monthOf(new Date()))

  // --- Données du mois ---
  let summary = $state<UsageSummary | null>(null)
  let byJob = $state<UsageByJob | null>(null)
  let loadFailed = $state(false)

  async function loadMonth() {
    summary = null
    byJob = null
    loadFailed = false
    const target = month
    const [summaryResult, byJobResult] = await Promise.all([
      getUsageSummary(target),
      getUsageByJob(target),
    ])
    if (target !== month) return // le mois a changé entre-temps
    if (
      summaryResult.error ||
      summaryResult.data === undefined ||
      byJobResult.error ||
      byJobResult.data === undefined
    ) {
      loadFailed = true
      toast.error("Impossible de charger la consommation du mois.")
      return
    }
    summary = summaryResult.data
    byJob = byJobResult.data
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

  // --- Géométrie du graphique SVG (viewBox fixe, rendu responsive 100%) ---
  const CW = 720
  const CH = 220
  const PAD = { l: 46, r: 14, t: 12, b: 26 }
  const PLOT_W = CW - PAD.l - PAD.r
  const PLOT_H = CH - PAD.t - PAD.b
  const BAR_COLOR = "#6366f1"

  const daysInMonth = $derived.by(() => {
    const [y, m] = month.split("-").map(Number)
    if (!y || !m) return 30
    return new Date(y, m, 0).getDate()
  })

  function xForDay(day: number, n: number): number {
    if (n <= 1) return PAD.l + PLOT_W / 2
    return PAD.l + ((day - 1) / (n - 1)) * PLOT_W
  }

  /** Arrondi « joli » de la borne haute de l'axe Y (1, 2, 5 × 10ⁿ). */
  function niceCeil(value: number): number {
    if (value <= 0) return 1
    const exp = Math.floor(Math.log10(value))
    const base = Math.pow(10, exp)
    const frac = value / base
    const nice = frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 5 ? 5 : 10
    return nice * base
  }

  // Modèle de graphique dérivé de la série temporelle courante (série totale).
  const chart = $derived.by(() => {
    const ts = timeseries
    if (!ts) return null
    const n = daysInMonth
    const byDay = new Map<number, number>()
    for (const s of ts.series) {
      for (const p of s.points) {
        const day = Number(p.date.slice(8, 10))
        const amt = Number(p.amount)
        if (Number.isFinite(day) && Number.isFinite(amt)) {
          byDay.set(day, (byDay.get(day) ?? 0) + amt)
        }
      }
    }
    let maxY = 0
    for (const v of byDay.values()) if (v > maxY) maxY = v
    const yMax = niceCeil(maxY)
    const yFor = (amount: number) => PAD.t + (1 - amount / yMax) * PLOT_H
    const xTicks: number[] = []
    for (let d = 1; d <= n; d += 5) xTicks.push(d)
    if (xTicks[xTicks.length - 1] !== n) xTicks.push(n)
    const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax)
    const barWidth = Math.max(2, (PLOT_W / n) * 0.6)
    return { n, byDay, maxY, yMax, yFor, xTicks, yTicks, barWidth }
  })

  const chartIsEmpty = $derived(chart != null && chart.maxY <= 0)

  /** Montant court pour l'axe Y : « 12 € », « 1,2 k€ ». */
  function formatShortEur(n: number): string {
    if (!Number.isFinite(n)) return ""
    if (n >= 1000) {
      return `${(n / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} k€`
    }
    return `${n.toLocaleString("fr-FR", { maximumFractionDigits: n < 10 ? 1 : 0 })} €`
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

  /** Jour du mois "YYYY-MM-DD" en libellé court "3 juil." pour les tooltips. */
  function formatDayLabel(day: number): string {
    const [y, m] = month.split("-").map(Number)
    const d = new Date(y, (m ?? 1) - 1, day)
    return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" })
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

  // Libellés fr des métriques techniques (repli : nom brut).
  const METRIC_LABELS: Record<string, string> = {
    input_tokens: "Unités de texte (entrée)",
    output_tokens: "Unités de texte (sortie)",
    images: "Images traitées",
    credits: "Crédits de génération",
    web_searches: "Recherches web",
    search_credits: "Recherches produit",
    extract_credits: "Extractions de page",
  }
  function metricLabel(metric: string): string {
    return METRIC_LABELS[metric] ?? metric
  }

  const inputTokensTotal = $derived(
    summary?.lines
      .filter((l) => l.metric === "input_tokens")
      .reduce((acc, l) => acc + l.quantity, 0) ?? null,
  )
  const outputTokensTotal = $derived(
    summary?.lines
      .filter((l) => l.metric === "output_tokens")
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

  // --- Lien vers le job (import ou enrichissement) ---
  function jobHref(jobType: string | null, jobId: number | null): string | null {
    if (jobId == null) return null
    if (jobType === "import") return `/imports/${jobId}`
    if (jobType === "enrichment") return `/jobs/${jobId}`
    return null
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
        {:else if summary === null || byJob === null}
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
                <span class="text-muted-foreground text-xs">Unités de texte (entrée)</span>
                <span class="text-foreground text-2xl font-semibold tabular-nums sm:text-3xl">
                  {inputTokensTotal != null ? formatInt(inputTokensTotal) : "—"}
                </span>
              </CardContent>
            </Card>
            <Card size="sm">
              <CardContent class="flex flex-col gap-1 py-4">
                <span class="text-muted-foreground text-xs">Unités de texte (sortie)</span>
                <span class="text-foreground text-2xl font-semibold tabular-nums sm:text-3xl">
                  {outputTokensTotal != null ? formatInt(outputTokensTotal) : "—"}
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
              {#if tsFailed}
                <p class="text-destructive py-4 text-center text-xs" role="alert">
                  Impossible de charger l'évolution quotidienne.
                </p>
              {:else if chart === null}
                <Skeleton class="h-48 w-full" />
              {:else if chartIsEmpty}
                <p class="text-muted-foreground py-10 text-center text-sm">
                  Aucune consommation ce mois-ci.
                </p>
              {:else}
                {@const c = chart}
                <svg
                  viewBox="0 0 {CW} {CH}"
                  class="text-muted-foreground h-auto w-full"
                  style="max-width:100%"
                  role="img"
                  aria-label="Évolution quotidienne du montant en euros pour {month}"
                >
                  <!-- Graduations et axe Y -->
                  {#each c.yTicks as ty (ty)}
                    {@const y = c.yFor(ty)}
                    <line
                      x1={PAD.l}
                      x2={CW - PAD.r}
                      y1={y}
                      y2={y}
                      stroke="currentColor"
                      stroke-opacity="0.15"
                    />
                    <text
                      x={PAD.l - 6}
                      y={y + 3}
                      text-anchor="end"
                      font-size="10"
                      fill="currentColor"
                    >
                      {formatShortEur(ty)}
                    </text>
                  {/each}

                  <!-- Étiquettes X -->
                  {#each c.xTicks as tx (tx)}
                    <text
                      x={xForDay(tx, c.n)}
                      y={CH - PAD.b + 16}
                      text-anchor="middle"
                      font-size="10"
                      fill="currentColor"
                    >
                      {tx}
                    </text>
                  {/each}

                  <!-- Barres par jour -->
                  {#each [...c.byDay.entries()] as [day, amount] (day)}
                    {@const x = xForDay(day, c.n)}
                    {@const y = c.yFor(amount)}
                    <rect
                      x={x - c.barWidth / 2}
                      y={y}
                      width={c.barWidth}
                      height={Math.max(0, CH - PAD.b - y)}
                      rx="1.5"
                      fill={BAR_COLOR}
                    >
                      <title>{formatDayLabel(day)} : {formatAmount(String(amount))}</title>
                    </rect>
                  {/each}
                </svg>
              {/if}
            </CardContent>
          </Card>

          <!-- Table Par service -->
          <h2 class="font-title mt-1 text-sm font-bold">Par service</h2>
          {#if summary.lines.length === 0}
            <Card size="sm">
              <CardContent class="text-muted-foreground py-4 text-center text-xs">
                Aucune consommation sur ce mois.
              </CardContent>
            </Card>
          {:else}
            <Card class="py-0">
              <CardContent class="overflow-x-auto px-0">
                <table class="w-full min-w-xl text-sm">
                  <thead>
                    <tr class="border-border border-b">
                      <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Service</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Type</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Quantité</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Montant</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each summary.lines as line, index (index)}
                      <tr class="border-border border-b last:border-b-0">
                        <td class="px-4 {cellPad} whitespace-nowrap">{line.provider}</td>
                        <td class="text-muted-foreground px-4 {cellPad} whitespace-nowrap text-xs">
                          {metricLabel(line.metric)}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatInt(line.quantity)}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatAmount(line.billable)}
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          {/if}

          <!-- Table Par job -->
          <h2 class="font-title mt-1 text-sm font-bold">Par traitement</h2>
          {#if byJob.jobs.length === 0}
            <Card size="sm">
              <CardContent class="text-muted-foreground py-4 text-center text-xs">
                Aucun traitement sur ce mois.
              </CardContent>
            </Card>
          {:else}
            <Card class="py-0">
              <CardContent class="overflow-x-auto px-0">
                <table class="w-full min-w-2xl text-sm">
                  <thead>
                    <tr class="border-border border-b">
                      <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Traitement</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Date</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Texte (entrée)</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Texte (sortie)</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Autres</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Montant</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each byJob.jobs as job, index (index)}
                      {@const href = jobHref(job.job_type, job.job_id)}
                      <tr class="border-border border-b last:border-b-0">
                        <td class="max-w-60 px-4 {cellPad}">
                          {#if href}
                            <a
                              {href}
                              class="text-primary block truncate font-medium underline-offset-2 hover:underline"
                              title={job.label}
                              onclick={(e) => {
                                e.preventDefault()
                                navigate(href)
                              }}
                            >
                              {job.label}
                            </a>
                          {:else}
                            <span class="block truncate font-medium" title={job.label}>
                              {job.label}
                            </span>
                          {/if}
                        </td>
                        <td class="text-muted-foreground px-4 {cellPad} text-right text-xs whitespace-nowrap tabular-nums">
                          {job.created_at != null ? formatRelativeDate(job.created_at) : "—"}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatInt(job.input_tokens)}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatInt(job.output_tokens)}
                        </td>
                        <td class="text-muted-foreground px-4 {cellPad} text-xs">
                          {#if job.other_metrics.length === 0}
                            —
                          {:else}
                            {job.other_metrics
                              .map((m) => `${metricLabel(m.metric)} : ${formatInt(m.quantity)}`)
                              .join(" · ")}
                          {/if}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatAmount(job.billable)}
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          {/if}
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
