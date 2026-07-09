<script lang="ts">
  // Page Consommation : coûts LLM du mois (synthèse, détail par modèle et
  // par job), export CSV, grille tarifaire et coefficient de facturation.
  import ChartColumn from "@lucide/svelte/icons/chart-column"
  import Download from "@lucide/svelte/icons/download"
  import Lock from "@lucide/svelte/icons/lock"
  import Plus from "@lucide/svelte/icons/plus"
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw"
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert"
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import { settingsReadAccountSettings } from "@/client"
  import {
    createUsagePrice,
    deleteUsagePrice,
    getUsageByJob,
    getUsageExport,
    getUsageSummary,
    getUsageTimeseries,
    listUsagePrices,
    refreezeUsageMonth,
    updateUsagePrice,
  } from "@/lib/api/usage"
  import type {
    UsageByJob,
    UsagePrice,
    UsageSummary,
    UsageTimeseries,
    UsageTimeseriesGroupBy,
  } from "@/lib/api/usage"
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
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import type { AccountSettingsExtended } from "@/lib/accountSettings.svelte"
  import { saveAccountSettingsPartial } from "@/lib/accountSettings.svelte"
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

  // --- Série temporelle quotidienne (graphiques) ---
  const TS_VIEWS: { key: UsageTimeseriesGroupBy; label: string }[] = [
    { key: "none", label: "Total" },
    { key: "model", label: "Par modèle" },
    { key: "provider", label: "Par provider" },
  ]
  let timeseries = $state<UsageTimeseries | null>(null)
  let tsView = $state<UsageTimeseriesGroupBy>("none")
  let tsFailed = $state(false)
  // Séries masquées via la légende (multi-séries uniquement).
  let hiddenSeries = $state<Set<string>>(new Set())

  async function loadTimeseries() {
    const targetMonth = month
    const targetView = tsView
    timeseries = null
    tsFailed = false
    hiddenSeries = new Set()
    const { data, error } = await getUsageTimeseries(targetMonth, targetView)
    if (targetMonth !== month || targetView !== tsView) return // rechangé
    if (error || data === undefined) {
      tsFailed = true
      return
    }
    timeseries = data
  }

  $effect(() => {
    void month // recharge au changement de mois…
    void tsView // …ou de vue
    loadTimeseries()
  })

  function toggleSeries(key: string) {
    const next = new Set(hiddenSeries)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    hiddenSeries = next
  }

  // --- Géométrie du graphique SVG (viewBox fixe, rendu responsive 100%) ---
  const CW = 720
  const CH = 220
  const PAD = { l: 46, r: 14, t: 12, b: 26 }
  const PLOT_W = CW - PAD.l - PAD.r
  const PLOT_H = CH - PAD.t - PAD.b
  // Palette catégorielle lisible en clair comme en sombre.
  const PALETTE = [
    "#6366f1",
    "#f59e0b",
    "#10b981",
    "#ef4444",
    "#3b82f6",
    "#a855f7",
    "#ec4899",
    "#14b8a6",
    "#f97316",
    "#8b5cf6",
  ]

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

  // Modèle de graphique dérivé de la série temporelle courante.
  const chart = $derived.by(() => {
    const ts = timeseries
    if (!ts) return null
    const n = daysInMonth
    const series = ts.series.map((s, i) => {
      const byDay = new Map<number, number>()
      for (const p of s.points) {
        const day = Number(p.date.slice(8, 10))
        const amt = Number(p.amount)
        if (Number.isFinite(day) && Number.isFinite(amt)) {
          byDay.set(day, (byDay.get(day) ?? 0) + amt)
        }
      }
      return { key: s.key, color: PALETTE[i % PALETTE.length], byDay }
    })
    let maxY = 0
    for (const s of series) {
      if (hiddenSeries.has(s.key)) continue
      for (const v of s.byDay.values()) if (v > maxY) maxY = v
    }
    const yMax = niceCeil(maxY)
    const yFor = (amount: number) => PAD.t + (1 - amount / yMax) * PLOT_H
    // Étiquettes X clairsemées (jour 1 puis tous les 5 jours).
    const xTicks: number[] = []
    for (let d = 1; d <= n; d += 5) xTicks.push(d)
    if (xTicks[xTicks.length - 1] !== n) xTicks.push(n)
    // Graduations Y (0 → yMax en 4 pas).
    const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax)
    return { n, series, maxY, yMax, yFor, xTicks, yTicks }
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

  /** Horodatage fr-FR (date + heure) depuis un ISO datetime. */
  function formatDateTime(iso: string): string {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString("fr-FR", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  /** Jour du mois "YYYY-MM-DD" en libellé court "3 juil." pour les tooltips. */
  function formatDayLabel(day: number): string {
    const [y, m] = month.split("-").map(Number)
    const d = new Date(y, (m ?? 1) - 1, day)
    return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" })
  }

  // --- Re-figement d'un mois facturé ---
  let refreezing = $state(false)
  let confirmingRefreeze = $state(false)
  let refreezeTimer: ReturnType<typeof setTimeout> | undefined

  async function onRefreezeClick() {
    clearTimeout(refreezeTimer)
    if (!confirmingRefreeze) {
      confirmingRefreeze = true
      refreezeTimer = setTimeout(() => (confirmingRefreeze = false), 3000)
      return
    }
    confirmingRefreeze = false
    refreezing = true
    // Le bouton n'est proposé que sur un mois déjà figé, donc `not_frozen`
    // (400) est en pratique inatteignable : un seul message d'échec suffit.
    const { data, error } = await refreezeUsageMonth(month)
    refreezing = false
    if (error || data === undefined) {
      toast.error("Re-figement impossible.")
      return
    }
    summary = data
    toast.success("Mois re-figé avec les tarifs actuels")
    await Promise.all([loadMonth(), loadTimeseries()])
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

  // --- Grille tarifaire ---
  let prices = $state<UsagePrice[] | null>(null)

  async function loadPrices() {
    const { data, error } = await listUsagePrices()
    if (error || data === undefined) {
      prices = []
      toast.error("Impossible de charger la grille tarifaire.")
      return
    }
    prices = data
  }

  $effect(() => {
    loadPrices()
  })

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

  const formIsTokenMetric = $derived(isTokenMetric(formMetric))

  // Suppression en deux temps (même pattern que la bibliothèque d'instructions).
  let confirmingDeleteId = $state<number | null>(null)
  let deleteTimer: ReturnType<typeof setTimeout> | undefined

  function openCreate() {
    editingId = null
    formProvider = ""
    formModel = ""
    formMetric = ""
    formPrice = ""
    formError = null
    formOpen = true
  }

  function openEdit(price: UsagePrice) {
    editingId = price.id
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
        toast.error("Création du tarif impossible.")
        return
      }
      toast.success("Tarif créé")
    } else {
      const { data, error } = await updateUsagePrice(editingId, body)
      savingPrice = false
      if (error || data === undefined) {
        toast.error("Enregistrement du tarif impossible.")
        return
      }
      toast.success("Tarif mis à jour")
    }
    closeForm()
    await Promise.all([loadPrices(), loadMonth()])
  }

  async function onDeletePriceClick(id: number) {
    clearTimeout(deleteTimer)
    if (confirmingDeleteId !== id) {
      // Première activation : arme le bouton, qui se désarme après un délai.
      confirmingDeleteId = id
      deleteTimer = setTimeout(() => (confirmingDeleteId = null), 3000)
      return
    }
    confirmingDeleteId = null
    const { error } = await deleteUsagePrice(id)
    if (error !== undefined) {
      toast.error("Suppression impossible.")
      return
    }
    if (editingId === id) closeForm()
    toast.success("Tarif supprimé")
    await Promise.all([loadPrices(), loadMonth()])
  }

  // --- Coefficient de facturation (réglage de compte, PUT partiel) ---
  let coefficientLoaded = $state(false)
  let coefficient = $state(1)
  let savingCoefficient = $state(false)

  $effect(() => {
    settingsReadAccountSettings().then(({ data, error }) => {
      if (error || !data) {
        toast.error("Impossible de charger le coefficient de facturation.")
        return
      }
      coefficient = (data as AccountSettingsExtended).billing_coefficient ?? 1
      coefficientLoaded = true
    })
  })

  async function saveCoefficient() {
    const value = Number(coefficient)
    if (!Number.isFinite(value) || value < 0) {
      toast.error("Le coefficient doit être un nombre positif ou nul.")
      return
    }
    savingCoefficient = true
    const ok = await saveAccountSettingsPartial({ billing_coefficient: value })
    savingCoefficient = false
    if (!ok) {
      toast.error("Enregistrement du coefficient impossible.")
      return
    }
    toast.success("Coefficient de facturation enregistré")
    await loadMonth()
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
          <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
          </div>
          <Skeleton class="h-32 w-full" />
          <Skeleton class="h-32 w-full" />
        {:else}
          <!-- Bandeau de statut du mois (figé ou à venir) -->
          {#if summary.frozen}
            <div
              class="border-border bg-muted/40 flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 text-sm"
            >
              <div class="flex items-start gap-2.5">
                <Lock size={16} class="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-500" aria-hidden="true" />
                <div class="flex flex-col gap-0.5">
                  <span class="font-medium">
                    Mois facturé le {formatLongDate(summary.billing_date)} — tarifs figés
                  </span>
                  {#if summary.frozen_at}
                    <span class="text-muted-foreground text-xs">
                      Figé le {formatDateTime(summary.frozen_at)}
                    </span>
                  {/if}
                </div>
              </div>
              <Button
                variant={confirmingRefreeze ? "destructive" : "outline"}
                size="sm"
                disabled={refreezing}
                onclick={onRefreezeClick}
              >
                <RotateCcw size={14} aria-hidden="true" data-icon="inline-start" />
                {refreezing
                  ? "Re-figement…"
                  : confirmingRefreeze
                    ? "Confirmer le re-figement ?"
                    : "Re-figer avec les tarifs actuels"}
              </Button>
            </div>
          {:else}
            <div
              class="border-border bg-muted/40 flex items-start gap-2.5 rounded-md border p-3 text-sm"
            >
              <ChartColumn size={16} class="text-muted-foreground mt-0.5 shrink-0" aria-hidden="true" />
              <span>Sera facturé le {formatLongDate(summary.billing_date)}.</span>
            </div>
          {/if}

          <!-- Cartes de synthèse -->
          <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Card size="sm">
              <CardContent class="flex flex-col gap-1 py-4">
                <span class="text-muted-foreground text-xs">Coût du mois</span>
                <span class="text-foreground text-2xl font-semibold tabular-nums sm:text-3xl">
                  {formatAmount(summary.totals.cost)}
                </span>
              </CardContent>
            </Card>
            <Card size="sm">
              <CardContent class="flex flex-col gap-1 py-4">
                <span class="text-muted-foreground text-xs">Facturable</span>
                <span class="text-foreground text-2xl font-semibold tabular-nums sm:text-3xl">
                  {formatAmount(summary.totals.billable)}
                </span>
                <span class="text-muted-foreground text-xs">
                  coefficient × {summary.coefficient.toLocaleString("fr-FR")}
                </span>
              </CardContent>
            </Card>
            <Card size="sm">
              <CardContent class="flex flex-col gap-1 py-4">
                <span class="text-muted-foreground text-xs">Tokens entrée</span>
                <span class="text-foreground text-2xl font-semibold tabular-nums sm:text-3xl">
                  {inputTokensTotal != null ? formatInt(inputTokensTotal) : "—"}
                </span>
              </CardContent>
            </Card>
            <Card size="sm">
              <CardContent class="flex flex-col gap-1 py-4">
                <span class="text-muted-foreground text-xs">Tokens sortie</span>
                <span class="text-foreground text-2xl font-semibold tabular-nums sm:text-3xl">
                  {outputTokensTotal != null ? formatInt(outputTokensTotal) : "—"}
                </span>
              </CardContent>
            </Card>
          </div>

          <!-- Bandeau : consommations sans tarif -->
          {#if summary.unpriced_count > 0}
            <div
              class="border-border bg-muted/50 flex items-start gap-2.5 rounded-md border p-3 text-sm"
              role="alert"
            >
              <TriangleAlert
                size={16}
                class="text-amber-600 mt-0.5 shrink-0 dark:text-amber-500"
                aria-hidden="true"
              />
              <p>
                {summary.unpriced_count} type{summary.unpriced_count > 1 ? "s" : ""}
                de consommation sans tarif — complétez la grille tarifaire ci-dessous.
              </p>
            </div>
          {/if}

          <!-- Évolution quotidienne (graphique SVG inline) -->
          <Card size="sm" class="mt-1">
            <CardHeader class="flex flex-row flex-wrap items-center justify-between gap-2">
              <CardTitle class="font-title text-sm">Évolution quotidienne</CardTitle>
              <div
                class="border-border bg-muted/40 inline-flex items-center gap-0.5 rounded-md border p-0.5"
                role="tablist"
                aria-label="Vue du graphique"
              >
                {#each TS_VIEWS as v (v.key)}
                  <button
                    type="button"
                    role="tab"
                    aria-selected={tsView === v.key}
                    class="cursor-pointer rounded px-2.5 py-1 text-xs font-medium transition-colors {tsView ===
                    v.key
                      ? 'bg-card text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'}"
                    onclick={() => (tsView = v.key)}
                  >
                    {v.label}
                  </button>
                {/each}
              </div>
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
                  aria-label="Évolution quotidienne du montant facturable en euros pour {month}, vue {TS_VIEWS.find(
                    (v) => v.key === tsView,
                  )?.label}"
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

                  {#if tsView === "none"}
                    <!-- Vue Total : barres par jour -->
                    {@const s = c.series[0]}
                    {@const bw = Math.max(2, (PLOT_W / c.n) * 0.6)}
                    {#if s}
                      {#each [...s.byDay.entries()] as [day, amount] (day)}
                        {@const x = xForDay(day, c.n)}
                        {@const y = c.yFor(amount)}
                        <rect
                          x={x - bw / 2}
                          y={y}
                          width={bw}
                          height={Math.max(0, CH - PAD.b - y)}
                          rx="1.5"
                          fill={s.color}
                        >
                          <title>{formatDayLabel(day)} : {formatAmount(String(amount))}</title>
                        </rect>
                      {/each}
                    {/if}
                  {:else}
                    <!-- Vues multi-séries : lignes -->
                    {#each c.series as s (s.key)}
                      {#if !hiddenSeries.has(s.key)}
                        {@const pts = [...s.byDay.entries()].sort((a, b) => a[0] - b[0])}
                        {#if pts.length > 1}
                          <polyline
                            points={pts
                              .map(([day, amount]) => `${xForDay(day, c.n)},${c.yFor(amount)}`)
                              .join(" ")}
                            fill="none"
                            stroke={s.color}
                            stroke-width="1.75"
                            stroke-linejoin="round"
                            stroke-linecap="round"
                          />
                        {/if}
                        {#each pts as [day, amount] (day)}
                          <circle
                            cx={xForDay(day, c.n)}
                            cy={c.yFor(amount)}
                            r="2.5"
                            fill={s.color}
                          >
                            <title>{s.key} — {formatDayLabel(day)} : {formatAmount(String(amount))}</title>
                          </circle>
                        {/each}
                      {/if}
                    {/each}
                  {/if}
                </svg>

                <!-- Légende cliquable (multi-séries) -->
                {#if tsView !== "none" && c.series.length > 0}
                  <div class="flex flex-wrap gap-x-3 gap-y-1.5">
                    {#each c.series as s (s.key)}
                      {@const hidden = hiddenSeries.has(s.key)}
                      <button
                        type="button"
                        class="flex cursor-pointer items-center gap-1.5 text-xs transition-opacity {hidden
                          ? 'opacity-40'
                          : ''}"
                        aria-pressed={!hidden}
                        onclick={() => toggleSeries(s.key)}
                      >
                        <span
                          class="size-2.5 shrink-0 rounded-sm"
                          style="background-color:{s.color}"
                          aria-hidden="true"
                        ></span>
                        <span class="text-foreground max-w-40 truncate">{s.key}</span>
                      </button>
                    {/each}
                  </div>
                {/if}
              {/if}
            </CardContent>
          </Card>

          <!-- Table Par modèle -->
          <h2 class="font-title mt-1 text-sm font-bold">Par modèle</h2>
          {#if summary.lines.length === 0}
            <Card size="sm">
              <CardContent class="text-muted-foreground py-4 text-center text-xs">
                Aucune consommation sur ce mois.
              </CardContent>
            </Card>
          {:else}
            <Card class="py-0">
              <CardContent class="overflow-x-auto px-0">
                <table class="w-full min-w-2xl text-sm">
                  <thead>
                    <tr class="border-border border-b">
                      <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Provider</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Modèle</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Métrique</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Quantité</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Prix unitaire</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Coût</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Facturable</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each summary.lines as line, index (index)}
                      <tr class="border-border border-b last:border-b-0">
                        <td class="px-4 {cellPad} whitespace-nowrap">{line.provider}</td>
                        <td class="max-w-52 truncate px-4 {cellPad}" title={line.model ?? undefined}>
                          {line.model ?? "—"}
                        </td>
                        <td class="text-muted-foreground px-4 {cellPad} whitespace-nowrap text-xs">
                          {line.metric}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatInt(line.quantity)}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatUnitPrice(line.metric, line.unit_price)}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatAmount(line.cost)}
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
          <h2 class="font-title mt-1 text-sm font-bold">Par job</h2>
          {#if byJob.jobs.length === 0}
            <Card size="sm">
              <CardContent class="text-muted-foreground py-4 text-center text-xs">
                Aucun job sur ce mois.
              </CardContent>
            </Card>
          {:else}
            <Card class="py-0">
              <CardContent class="overflow-x-auto px-0">
                <table class="w-full min-w-2xl text-sm">
                  <thead>
                    <tr class="border-border border-b">
                      <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Job</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Date</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Tokens entrée</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Tokens sortie</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Autres métriques</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Coût</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Facturable</th>
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
                              .map((m) => `${m.metric} : ${formatInt(m.quantity)}`)
                              .join(" · ")}
                          {/if}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatAmount(job.cost)}
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

        <!-- Grille tarifaire -->
        <Card size="sm" class="mt-1">
          <CardHeader>
            <CardTitle class="font-title flex items-center gap-2 text-sm">
              <ChartColumn size={14} aria-hidden="true" />
              Grille tarifaire
            </CardTitle>
            <CardDescription class="text-muted-foreground text-xs">
              Prix appliqués pour calculer les coûts. Pour les métriques en
              tokens, le prix se saisit et s'affiche en € par million.
            </CardDescription>
          </CardHeader>
          <CardContent class="flex flex-col gap-3">
            {#if summary?.frozen}
              <p
                class="border-warning/40 bg-warning/10 text-warning-foreground rounded-md border px-3 py-2 text-xs"
                role="note"
              >
                Vous consultez un mois facturé : la grille est globale, vos
                modifications de tarifs n'affecteront que les mois non encore
                facturés — pas ce mois figé.
              </p>
            {/if}
            {#if prices === null}
              <Skeleton class="h-10 w-full" />
              <Skeleton class="h-10 w-full" />
            {:else}
              {#if prices.length === 0 && !formOpen}
                <p class="text-muted-foreground py-2 text-center text-sm">
                  Aucun tarif pour l'instant — ajoutez par exemple le prix des
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
                              <Button
                                variant={confirmingDeleteId === price.id ? "destructive" : "ghost"}
                                size="sm"
                                onclick={() => onDeletePriceClick(price.id)}
                              >
                                {confirmingDeleteId === price.id ? "Confirmer ?" : "Supprimer"}
                              </Button>
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
                    {editingId === null ? "Nouveau tarif" : "Modifier le tarif"}
                  </span>
                  <div class="grid gap-3 sm:grid-cols-2">
                    <div class="flex flex-col gap-1.5">
                      <Label for="price-provider">Provider</Label>
                      <Input
                        id="price-provider"
                        placeholder="Ex. anthropic"
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
                    Nouveau tarif
                  </Button>
                </div>
              {/if}
            {/if}
          </CardContent>
        </Card>

        <!-- Coefficient de facturation -->
        <Card size="sm">
          <CardHeader>
            <CardTitle class="font-title text-sm">Coefficient de facturation</CardTitle>
            <CardDescription class="text-muted-foreground text-xs">
              Multiplie le coût réel pour obtenir le montant facturable.
            </CardDescription>
          </CardHeader>
          <CardContent class="flex flex-wrap items-end gap-3">
            {#if !coefficientLoaded}
              <Skeleton class="h-9 w-40" />
            {:else}
              <div class="flex flex-col gap-1.5 sm:max-w-40">
                <Label for="billing-coefficient">Coefficient</Label>
                <input
                  id="billing-coefficient"
                  type="number"
                  min="0"
                  step="0.05"
                  class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                  bind:value={coefficient}
                />
              </div>
              <Button
                size="sm"
                disabled={savingCoefficient}
                onclick={saveCoefficient}
              >
                {savingCoefficient ? "Enregistrement…" : "Enregistrer"}
              </Button>
            {/if}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
