<script lang="ts">
  // Graphique « Évolution quotidienne » de la consommation : barres empilées
  // par jour, une couleur par série (total seul, par service ou par modèle
  // selon le group_by demandé au backend). SVG inline, viewBox fixe rendu
  // responsive, tooltips natifs <title> par segment, légende sous le
  // graphique dès qu'il y a plus d'une série.
  import type { UsageTimeseries } from "@/lib/api/usage"
  import { Skeleton } from "@/lib/components/ui/skeleton"

  let {
    timeseries,
    failed = false,
    month,
  }: {
    timeseries: UsageTimeseries | null
    failed?: boolean
    month: string
  } = $props()

  // Couleurs de séries : ordre fixe, jamais recyclé — les séries arrivent
  // triées du backend, la couleur suit donc la série d'un mois à l'autre.
  // Au-delà de la palette : gris neutre (cas « beaucoup de modèles »).
  const PALETTE = [
    "#6366f1",
    "#10b981",
    "#f59e0b",
    "#ef4444",
    "#06b6d4",
    "#8b5cf6",
    "#ec4899",
    "#84cc16",
  ]
  const OVERFLOW_COLOR = "#9ca3af"

  function seriesColor(index: number): string {
    return PALETTE[index] ?? OVERFLOW_COLOR
  }

  // --- Géométrie (viewBox fixe, rendu responsive 100%) ---
  const CW = 720
  const CH = 220
  const PAD = { l: 46, r: 14, t: 12, b: 26 }
  const PLOT_W = CW - PAD.l - PAD.r
  const PLOT_H = CH - PAD.t - PAD.b

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

  type Segment = { key: string; color: string; amount: number; y0: number; y1: number }

  // Modèle du graphique : par jour, une pile de segments (un par série non
  // nulle ce jour-là) ; yMax = plus haut total quotidien.
  const chart = $derived.by(() => {
    const ts = timeseries
    if (!ts) return null
    const n = daysInMonth
    // amounts[jour] = [{key, amount}] dans l'ordre des séries.
    const perDay = new Map<number, { key: string; amount: number; index: number }[]>()
    const totals = new Map<number, number>()
    ts.series.forEach((s, index) => {
      for (const p of s.points) {
        const day = Number(p.date.slice(8, 10))
        const amt = Number(p.amount)
        if (!Number.isFinite(day) || !Number.isFinite(amt) || amt <= 0) continue
        const stack = perDay.get(day) ?? []
        stack.push({ key: s.key, amount: amt, index })
        perDay.set(day, stack)
        totals.set(day, (totals.get(day) ?? 0) + amt)
      }
    })
    let maxY = 0
    for (const v of totals.values()) if (v > maxY) maxY = v
    const yMax = niceCeil(maxY)
    const yFor = (amount: number) => PAD.t + (1 - amount / yMax) * PLOT_H
    // Piles de segments prêtes à dessiner (du bas vers le haut).
    const stacks = new Map<number, Segment[]>()
    for (const [day, entries] of perDay) {
      let acc = 0
      const segments: Segment[] = []
      for (const entry of entries) {
        const y0 = yFor(acc)
        acc += entry.amount
        segments.push({
          key: entry.key,
          color: seriesColor(entry.index),
          amount: entry.amount,
          y0,
          y1: yFor(acc),
        })
      }
      stacks.set(day, segments)
    }
    const xTicks: number[] = []
    for (let d = 1; d <= n; d += 5) xTicks.push(d)
    if (xTicks[xTicks.length - 1] !== n) xTicks.push(n)
    const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax)
    const barWidth = Math.max(2, (PLOT_W / n) * 0.6)
    return { n, stacks, maxY, yFor, xTicks, yTicks, barWidth }
  })

  const chartIsEmpty = $derived(chart != null && chart.maxY <= 0)
  const showLegend = $derived((timeseries?.series.length ?? 0) > 1)
  const currency = $derived(timeseries?.currency ?? "EUR")

  /** Montant court pour l'axe Y : « 12 € », « 1,2 k€ ». */
  function formatShortEur(n: number): string {
    if (!Number.isFinite(n)) return ""
    if (n >= 1000) {
      return `${(n / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} k€`
    }
    return `${n.toLocaleString("fr-FR", { maximumFractionDigits: n < 10 ? 1 : 0 })} €`
  }

  function formatAmount(n: number): string {
    return n.toLocaleString("fr-FR", { style: "currency", currency })
  }

  /** Jour du mois en libellé court "3 juil." pour les tooltips. */
  function formatDayLabel(day: number): string {
    const [y, m] = month.split("-").map(Number)
    const d = new Date(y, (m ?? 1) - 1, day)
    return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" })
  }
</script>

{#if failed}
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
      <text x={PAD.l - 6} y={y + 3} text-anchor="end" font-size="10" fill="currentColor">
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

    <!-- Barres empilées par jour -->
    {#each [...c.stacks.entries()] as [day, segments] (day)}
      {@const x = xForDay(day, c.n)}
      {#each segments as segment, si (si)}
        <rect
          x={x - c.barWidth / 2}
          y={segment.y1}
          width={c.barWidth}
          height={Math.max(0, segment.y0 - segment.y1)}
          rx="1.5"
          fill={segment.color}
        >
          <title>
            {formatDayLabel(day)}{showLegend ? ` — ${segment.key}` : ""} : {formatAmount(
              segment.amount,
            )}
          </title>
        </rect>
      {/each}
    {/each}
  </svg>

  {#if showLegend && timeseries}
    <div class="flex flex-wrap gap-x-4 gap-y-1.5">
      {#each timeseries.series as s, index (s.key)}
        <span class="text-muted-foreground flex items-center gap-1.5 text-xs">
          <span
            class="size-2.5 shrink-0 rounded-sm"
            style={`background:${seriesColor(index)}`}
            aria-hidden="true"
          ></span>
          {s.key}
        </span>
      {/each}
    </div>
  {/if}
{/if}
