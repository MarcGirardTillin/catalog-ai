<script lang="ts">
  // Console admin — vue d'ensemble clients : par compte et par mois, coût
  // brut vs facturable (= la marge), volumes de jobs/imports et échecs.
  import { createQuery } from "@tanstack/svelte-query"
  import { navigate } from "svelte5-router"

  import {
    getAdminOverview,
    getAdminTimeseries,
    type AdminTimeseriesGroupBy,
  } from "@/lib/api/admin"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent, CardHeader, CardTitle } from "@/lib/components/ui/card"
  import { EmptyState } from "@/lib/components/ui/empty-state"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAdmin from "@/lib/components/app/RequireAdmin.svelte"
  import UsageChart from "@/lib/components/usage/UsageChart.svelte"
  import { prefs } from "@/lib/preferences.svelte"

  let { appName }: { appName: string } = $props()

  const cellPad = $derived(prefs.density === "compact" ? "py-1" : "py-2.5")

  function monthOf(date: Date): string {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`
  }
  const currentMonth = monthOf(new Date())
  let month = $state(monthOf(new Date()))

  // Vue d'ensemble du mois : le mois est dans la clé, changer de mois
  // refetch automatiquement.
  const overviewQuery = createQuery(() => ({
    queryKey: ["admin", "overview", month],
    queryFn: async () => {
      const { data, error } = await getAdminOverview(month)
      if (error || !data) throw new Error("admin_overview_load_failed")
      return data
    },
  }))
  const overview = $derived(overviewQuery.data ?? null)
  const loadFailed = $derived(overviewQuery.isError)

  // --- Graphique de consommation, tous clients confondus ---
  const CHART_MODES: { value: AdminTimeseriesGroupBy; label: string }[] = [
    { value: "none", label: "Total par jour" },
    { value: "service", label: "Par service" },
    { value: "model", label: "Par modèle" },
  ]
  let chartMode = $state<AdminTimeseriesGroupBy>("none")

  const timeseriesQuery = createQuery(() => ({
    queryKey: ["admin", "timeseries", month, chartMode],
    queryFn: async () => {
      const { data, error } = await getAdminTimeseries(month, chartMode)
      if (error || !data) throw new Error("admin_timeseries_load_failed")
      return data
    },
  }))
  const timeseries = $derived(timeseriesQuery.data ?? null)
  const tsFailed = $derived(timeseriesQuery.isError)

  function formatAmount(value: string): string {
    const n = Number(value)
    if (!Number.isFinite(n)) return "—"
    return n.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })
  }
</script>

<RequireAdmin>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Admin" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h1 class="font-title text-lg font-bold">Clients</h1>
          <div class="flex items-center gap-2">
            <label class="sr-only" for="admin-month">Mois</label>
            <input
              id="admin-month"
              type="month"
              max={currentMonth}
              class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
              bind:value={month}
            />
            <Button variant="outline" size="sm" onclick={() => navigate("/admin/billing")}>
              Tarification
            </Button>
            <Button variant="outline" size="sm" onclick={() => navigate("/admin/pricing")}>
              Coûts
            </Button>
          </div>
        </div>
        <p class="text-muted-foreground text-sm">
          Suivi opérateur par client : coût réel des providers, montant
          facturable et marge. Cliquez un client pour le détail.
        </p>

        <!-- Consommation quotidienne, tous clients confondus -->
        <Card size="sm">
          <CardHeader>
            <div class="flex flex-wrap items-center justify-between gap-2">
              <CardTitle class="font-title text-sm">
                Consommation quotidienne (tous clients)
              </CardTitle>
              <div class="flex items-center gap-1" role="group" aria-label="Regroupement du graphique">
                {#each CHART_MODES as mode (mode.value)}
                  <Button
                    size="sm"
                    variant={chartMode === mode.value ? "secondary" : "ghost"}
                    aria-pressed={chartMode === mode.value}
                    onclick={() => (chartMode = mode.value)}
                  >
                    {mode.label}
                  </Button>
                {/each}
              </div>
            </div>
          </CardHeader>
          <CardContent class="flex flex-col gap-3">
            <UsageChart {timeseries} failed={tsFailed} {month} />
          </CardContent>
        </Card>

        {#if loadFailed}
          <p class="text-destructive text-xs" role="alert">
            Impossible de charger la vue d'ensemble.
          </p>
        {:else if overview === null}
          <Skeleton class="h-10 w-full" />
          <Skeleton class="h-10 w-full" />
        {:else if overview.lines.length === 0}
          <EmptyState message="Aucun compte client." />
        {:else}
          <Card class="py-0">
            <CardContent class="overflow-x-auto px-0">
              <table class="w-full min-w-2xl text-sm">
                <thead>
                  <tr class="border-border border-b">
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Client</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Coût réel</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Facturable</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Marge</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Coeff.</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Enrichissements</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Imports</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Échecs</th>
                  </tr>
                </thead>
                <tbody>
                  {#each overview.lines as line (line.account_id)}
                    <tr
                      role="link"
                      tabindex="0"
                      aria-label={`Ouvrir le client ${line.account_name}`}
                      class="border-border hover:bg-muted/50 focus-visible:bg-muted/50 cursor-pointer border-b outline-none transition-colors last:border-b-0"
                      onclick={() => navigate(`/admin/accounts/${line.account_id}`)}
                      onkeydown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault()
                          navigate(`/admin/accounts/${line.account_id}`)
                        }
                      }}
                    >
                      <td class="px-4 {cellPad} font-medium whitespace-nowrap">
                        {line.account_name}
                      </td>
                      <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                        {formatAmount(line.cost)}
                      </td>
                      <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                        {formatAmount(line.billable)}
                      </td>
                      <td class="px-4 {cellPad} text-right font-medium whitespace-nowrap tabular-nums">
                        {formatAmount(line.margin)}
                      </td>
                      <td class="text-muted-foreground px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                        ×{line.coefficient.toLocaleString("fr-FR")}
                      </td>
                      <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                        {line.jobs_count}
                      </td>
                      <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                        {line.imports_count}
                      </td>
                      <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums {line.failed_items > 0 ? 'text-destructive font-medium' : ''}">
                        {line.failed_items}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </CardContent>
          </Card>
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAdmin>
