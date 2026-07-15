<script lang="ts">
  // Console admin — détail d'un client : consommation COMPLÈTE (modèles,
  // coûts, marge), activité récente, et réglages opérateur (coefficient,
  // minutes « temps gagné »).
  import { createQuery, useQueryClient } from "@tanstack/svelte-query"
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import {
    getAdminAccountActivity,
    getAdminAccountSettings,
    getAdminAccountTimeseries,
    getAdminAccountUsage,
    getAdminAccountUsageByJob,
    putAdminAccountSettings,
    type AdminAccountSettings,
    type AdminTimeseriesGroupBy,
  } from "@/lib/api/admin"
  import {
    getAdminAccountCredits,
    grantAdminAccountCredits,
    type CreditEntryPublic,
  } from "@/lib/api/credits"
  import type { UsageByJob } from "@/lib/api/usage"
  import { Button } from "@/lib/components/ui/button"
  import { Select } from "@/lib/components/ui/select"
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
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"
  import UsageChart from "@/lib/components/usage/UsageChart.svelte"
  import { formatRelativeDate } from "@/lib/format"
  import { prefs } from "@/lib/preferences.svelte"
  import { IMAGE_SERVICE_LABEL, metricLabel, serviceLabel } from "@/lib/usageLabels"

  let { appName, id }: { appName: string; id: string } = $props()

  const queryClient = useQueryClient()
  const cellPad = $derived(prefs.density === "compact" ? "py-1" : "py-2.5")
  const accountId = $derived(Number(id))

  function monthOf(date: Date): string {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`
  }
  const currentMonth = monthOf(new Date())
  let month = $state(monthOf(new Date()))

  // Consommation du compte : mois et id dans les clés, les changements de
  // paramètres refetchent automatiquement.
  const summaryQuery = createQuery(() => ({
    queryKey: ["admin", "account", id, "usage", month],
    queryFn: async () => {
      const { data, error } = await getAdminAccountUsage(accountId, month)
      if (error || !data) throw new Error("admin_account_usage_load_failed")
      return data
    },
  }))
  const byJobQuery = createQuery(() => ({
    queryKey: ["admin", "account", id, "by-job", month],
    queryFn: async () => {
      const { data, error } = await getAdminAccountUsageByJob(accountId, month)
      if (error || !data) throw new Error("admin_account_by_job_load_failed")
      return data
    },
  }))
  const summary = $derived(summaryQuery.data ?? null)
  const byJob = $derived(byJobQuery.data ?? null)
  const loadFailed = $derived(summaryQuery.isError || byJobQuery.isError)

  const activityQuery = createQuery(() => ({
    queryKey: ["admin", "account", id, "activity"],
    queryFn: async () => {
      const { data } = await getAdminAccountActivity(accountId)
      return data ?? { account_id: accountId, entries: [] }
    },
  }))
  const activity = $derived(activityQuery.data ?? null)

  // --- Graphique de consommation quotidienne du compte ---
  const CHART_MODES: { value: AdminTimeseriesGroupBy; label: string }[] = [
    { value: "none", label: "Total par jour" },
    { value: "service", label: "Par service" },
    { value: "model", label: "Par modèle" },
  ]
  let chartMode = $state<AdminTimeseriesGroupBy>("none")

  const timeseriesQuery = createQuery(() => ({
    queryKey: ["admin", "account", id, "timeseries", month, chartMode],
    queryFn: async () => {
      const { data, error } = await getAdminAccountTimeseries(
        accountId,
        month,
        chartMode,
      )
      if (error || !data) throw new Error("admin_account_timeseries_load_failed")
      return data
    },
  }))
  const timeseries = $derived(timeseriesQuery.data ?? null)
  const tsFailed = $derived(timeseriesQuery.isError)

  // --- Table « Par service » : lignes du summary agrégées par libellé de
  // service neutre (le même regroupement que voit le client, mais avec les
  // montants opérateur complets). ---
  type ServiceRow = {
    service: string
    metric: string
    quantity: number
    cost: number
    billable: number
  }
  const serviceRows = $derived.by<ServiceRow[]>(() => {
    if (!summary) return []
    const merged = new Map<string, ServiceRow>()
    for (const line of summary.lines) {
      const service = serviceLabel(line.provider)
      const key = `${service}|${line.metric}`
      const row = merged.get(key) ?? {
        service,
        metric: line.metric,
        quantity: 0,
        cost: 0,
        billable: 0,
      }
      row.quantity += line.quantity
      row.cost += Number(line.cost ?? 0)
      row.billable += Number(line.billable ?? 0)
      merged.set(key, row)
    }
    return [...merged.values()].sort(
      (a, b) => a.service.localeCompare(b.service) || a.metric.localeCompare(b.metric),
    )
  })

  // --- Crédits prépayés : solde, ledger et octroi manuel ---
  const creditsQuery = createQuery(() => ({
    queryKey: ["admin", "account", id, "credits"],
    queryFn: async () => {
      const { data, error } = await getAdminAccountCredits(accountId)
      if (error || !data) throw new Error("admin_account_credits_load_failed")
      return data
    },
  }))
  const credits = $derived(creditsQuery.data ?? null)

  let grantCredits = $state("")
  let grantKind = $state<"grant" | "purchase" | "adjustment">("grant")
  let grantLabel = $state("")
  let grantPrice = $state("")
  let granting = $state(false)

  async function submitGrant() {
    if (granting) return
    const amount = Math.trunc(Number(grantCredits))
    if (!Number.isFinite(amount) || amount === 0) {
      toast.error("Le montant de crédits doit être un entier non nul (signé).")
      return
    }
    const price = grantPrice.trim() === "" ? null : Number(grantPrice)
    if (price != null && (!Number.isFinite(price) || price < 0)) {
      toast.error("Le prix doit être un nombre positif ou nul.")
      return
    }
    granting = true
    const { data, error } = await grantAdminAccountCredits(accountId, {
      credits: amount,
      kind: grantKind,
      label: grantLabel.trim() || null,
      price_eur: price,
    })
    granting = false
    if (error || !data) {
      toast.error("Enregistrement du mouvement impossible.")
      return
    }
    toast.success(`Mouvement enregistré — solde : ${data.balance} crédits`)
    grantCredits = ""
    grantLabel = ""
    grantPrice = ""
    queryClient.invalidateQueries({ queryKey: ["admin", "account", id, "credits"] })
  }

  const CREDIT_KIND_LABELS: Record<string, string> = {
    purchase: "Achat de pack",
    grant: "Offert",
    subscription: "Abonnement",
    consumption: "Consommation",
    adjustment: "Ajustement",
  }
  function creditKindLabel(kind: string): string {
    return CREDIT_KIND_LABELS[kind] ?? kind
  }
  function creditEntryLabel(entry: CreditEntryPublic): string {
    if (entry.label) return entry.label
    if (entry.kind === "consumption" && entry.action) {
      const labels: Record<string, string> = {
        import_product: "Produits importés",
        enrich_item: "Fiches enrichies",
        image_process: "Images traitées",
        image_generate: "Visuels générés",
      }
      const base = labels[entry.action] ?? entry.action
      return entry.quantity != null ? `${base} × ${entry.quantity}` : base
    }
    return "—"
  }

  // --- Réglages opérateur du compte (coefficient + temps gagné) ---
  // Le formulaire édite une copie locale (bind:value) hydratée depuis la query.
  let settings = $state<AdminAccountSettings | null>(null)
  let savingSettings = $state(false)

  const settingsQuery = createQuery(() => ({
    queryKey: ["admin", "account", id, "settings"],
    queryFn: async () => {
      const { data, error } = await getAdminAccountSettings(accountId)
      if (error || !data) throw new Error("admin_account_settings_load_failed")
      return data
    },
  }))
  $effect(() => {
    const data = settingsQuery.data
    if (data) settings = { ...data }
  })
  $effect(() => {
    if (settingsQuery.isError) {
      toast.error("Impossible de charger les réglages du client.")
    }
  })

  async function saveSettings() {
    if (!settings || savingSettings) return
    const coefficient = Number(settings.billing_coefficient)
    const importMin = Math.round(Number(settings.minutes_saved_per_import_product))
    const enrichedMin = Math.round(
      Number(settings.minutes_saved_per_enriched_product),
    )
    if (!Number.isFinite(coefficient) || coefficient < 0) {
      toast.error("Le coefficient doit être un nombre positif ou nul.")
      return
    }
    if (
      [importMin, enrichedMin].some(
        (v) => !Number.isFinite(v) || v < 0 || v > 120,
      )
    ) {
      toast.error("Les minutes doivent être comprises entre 0 et 120.")
      return
    }
    const creditInts = {
      credit_cost_import_product: settings.credit_cost_import_product,
      credit_cost_enrich_item: settings.credit_cost_enrich_item,
      credit_cost_image_process: settings.credit_cost_image_process,
      credit_cost_image_generate: settings.credit_cost_image_generate,
      monthly_free_credits: settings.monthly_free_credits,
      low_credit_threshold: settings.low_credit_threshold,
    }
    const normalizedCredits: Record<string, number> = {}
    for (const [key, raw] of Object.entries(creditInts)) {
      const value = Math.round(Number(raw))
      if (!Number.isFinite(value) || value < 0) {
        toast.error("Les valeurs de crédits doivent être des entiers positifs.")
        return
      }
      normalizedCredits[key] = value
    }
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
    savingSettings = true
    const { data, error } = await putAdminAccountSettings(accountId, {
      ...settings,
      billing_coefficient: coefficient,
      minutes_saved_per_import_product: importMin,
      minutes_saved_per_enriched_product: enrichedMin,
      ...normalizedCredits,
      credit_packs: packs,
    })
    savingSettings = false
    if (error || !data) {
      toast.error("Enregistrement des réglages impossible.")
      return
    }
    settings = { ...data }
    toast.success("Réglages du client enregistrés")
    // Le coefficient change le facturable affiché : on invalide les lectures
    // de consommation du compte (summary, par traitement, série quotidienne).
    queryClient.invalidateQueries({ queryKey: ["admin", "account", id, "usage"] })
    queryClient.invalidateQueries({ queryKey: ["admin", "account", id, "by-job"] })
    queryClient.invalidateQueries({
      queryKey: ["admin", "account", id, "timeseries"],
    })
    queryClient.invalidateQueries({ queryKey: ["admin", "account", id, "settings"] })
    queryClient.invalidateQueries({ queryKey: ["admin", "account", id, "credits"] })
  }

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

  // --- Formatage ---
  function formatAmount(value: string | null): string {
    if (value == null) return "—"
    const n = Number(value)
    if (!Number.isFinite(n)) return "—"
    return n.toLocaleString("fr-FR", { style: "currency", currency: "EUR" })
  }

  function formatInt(n: number): string {
    return n.toLocaleString("fr-FR")
  }

  function isTokenMetric(metric: string): boolean {
    return metric.trim().endsWith("_tokens")
  }

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

  const margin = $derived.by(() => {
    if (!summary) return null
    const cost = Number(summary.totals.cost)
    const billable = Number(summary.totals.billable)
    if (!Number.isFinite(cost) || !Number.isFinite(billable)) return null
    return String(billable - cost)
  })

  function jobHref(jobType: string | null, jobId: number | null): string | null {
    if (jobId == null) return null
    if (jobType === "import") return `/imports/${jobId}`
    if (jobType === "enrichment") return `/jobs/${jobId}`
    return null
  }

  // Mêmes colonnes que le tableau « Par traitement » de l'onglet Consommation
  // client — ici les other_metrics portent les providers bruts, le pivot
  // image passe donc par le mapping provider → service.
  function jobTypeLabel(jobType: string | null): string {
    if (jobType === "import") return "Import fichier"
    if (jobType === "enrichment") return "Enrichissement"
    return "—"
  }
  function jobImages(job: UsageByJob["jobs"][number]): number {
    return job.other_metrics
      .filter((m) => serviceLabel(m.provider) === IMAGE_SERVICE_LABEL)
      .reduce((acc, m) => acc + m.quantity, 0)
  }
  function jobCredits(job: UsageByJob["jobs"][number]): number {
    return (
      job.input_tokens +
      job.output_tokens +
      job.other_metrics
        .filter((m) => serviceLabel(m.provider) !== IMAGE_SERVICE_LABEL)
        .reduce((acc, m) => acc + m.quantity, 0)
    )
  }
</script>

<RequireAdmin>
  {#snippet children(user)}
    <AppShell
      {appName}
      {user}
      breadcrumbs={[
        { label: "Admin", href: "/admin" },
        { label: `Client #${id}` },
      ]}
    >
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h1 class="font-title text-lg font-bold">Client #{id}</h1>
          <div class="flex items-center gap-2">
            <label class="sr-only" for="account-month">Mois</label>
            <input
              id="account-month"
              type="month"
              max={currentMonth}
              class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
              bind:value={month}
            />
          </div>
        </div>

        {#if loadFailed}
          <p class="text-destructive text-xs" role="alert">
            Impossible de charger la consommation du client.
          </p>
        {:else if summary === null || byJob === null}
          <div class="grid grid-cols-3 gap-3">
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
          </div>
          <Skeleton class="h-32 w-full" />
        {:else}
          <!-- Synthèse coût / facturable / marge -->
          <div class="grid grid-cols-3 gap-3">
            <Card size="sm">
              <CardContent class="flex flex-col gap-1 py-4">
                <span class="text-muted-foreground text-xs">Coût réel</span>
                <span class="text-foreground text-2xl font-semibold tabular-nums">
                  {formatAmount(summary.totals.cost)}
                </span>
              </CardContent>
            </Card>
            <Card size="sm">
              <CardContent class="flex flex-col gap-1 py-4">
                <span class="text-muted-foreground text-xs">Facturable</span>
                <span class="text-foreground text-2xl font-semibold tabular-nums">
                  {formatAmount(summary.totals.billable)}
                </span>
                <span class="text-muted-foreground text-xs">
                  coefficient × {summary.coefficient.toLocaleString("fr-FR")}
                </span>
              </CardContent>
            </Card>
            <Card size="sm">
              <CardContent class="flex flex-col gap-1 py-4">
                <span class="text-muted-foreground text-xs">Marge</span>
                <span class="text-foreground text-2xl font-semibold tabular-nums">
                  {formatAmount(margin)}
                </span>
              </CardContent>
            </Card>
          </div>

          {#if summary.unpriced_count > 0}
            <p class="text-warning-foreground text-xs" role="alert">
              {summary.unpriced_count} type{summary.unpriced_count > 1 ? "s" : ""}
              de consommation sans tarif — complétez la
              <a
                href="/admin/pricing"
                class="underline underline-offset-2"
                onclick={(e) => {
                  e.preventDefault()
                  navigate("/admin/pricing")
                }}>grille tarifaire</a
              >.
            </p>
          {/if}

          <!-- Consommation quotidienne du compte -->
          <Card size="sm" class="mt-1">
            <CardHeader>
              <div class="flex flex-wrap items-center justify-between gap-2">
                <CardTitle class="font-title text-sm">Consommation quotidienne</CardTitle>
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

          <!-- Détail par service (même regroupement neutre que la vue client,
               mais avec coût et facturable opérateur) -->
          <h2 class="font-title mt-1 text-sm font-bold">Par service</h2>
          {#if serviceRows.length === 0}
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
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Coût</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Facturable</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each serviceRows as row (row.service + row.metric)}
                      <tr class="border-border border-b last:border-b-0">
                        <td class="px-4 {cellPad} whitespace-nowrap">{row.service}</td>
                        <td class="text-muted-foreground px-4 {cellPad} whitespace-nowrap text-xs">
                          {metricLabel(row.metric)}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatInt(row.quantity)}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatAmount(String(row.cost))}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatAmount(String(row.billable))}
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          {/if}

          <!-- Détail par modèle (vue complète, non expurgée) -->
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

          <!-- Détail par traitement (complet) -->
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
                      <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Type</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Date</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Crédits de génération</th>
                      <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Images traitées</th>
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
                        <td class="text-muted-foreground px-4 {cellPad} text-xs whitespace-nowrap">
                          {jobTypeLabel(job.job_type)}
                        </td>
                        <td class="text-muted-foreground px-4 {cellPad} text-right text-xs whitespace-nowrap tabular-nums">
                          {job.created_at != null ? formatRelativeDate(job.created_at) : "—"}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatInt(jobCredits(job))}
                        </td>
                        <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                          {formatInt(jobImages(job))}
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

        <!-- Activité récente -->
        <h2 class="font-title mt-1 text-sm font-bold">Activité récente</h2>
        {#if activity === null}
          <Skeleton class="h-16 w-full" />
        {:else if activity.entries.length === 0}
          <Card size="sm">
            <CardContent class="text-muted-foreground py-4 text-center text-xs">
              Aucune activité pour l'instant.
            </CardContent>
          </Card>
        {:else}
          <Card class="py-0">
            <CardContent class="overflow-x-auto px-0">
              <table class="w-full min-w-xl text-sm">
                <thead>
                  <tr class="border-border border-b">
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Traitement</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Type</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Statut</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Produits</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Échecs</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Créé</th>
                  </tr>
                </thead>
                <tbody>
                  {#each activity.entries as entry (entry.job_id)}
                    {@const href = jobHref(entry.job_type, entry.job_id)}
                    <tr class="border-border border-b last:border-b-0">
                      <td class="max-w-60 px-4 {cellPad}">
                        {#if href}
                          <a
                            {href}
                            class="text-primary block truncate font-medium underline-offset-2 hover:underline"
                            title={entry.label}
                            onclick={(e) => {
                              e.preventDefault()
                              navigate(href)
                            }}
                          >
                            {entry.label}
                          </a>
                        {:else}
                          <span class="block truncate font-medium">{entry.label}</span>
                        {/if}
                      </td>
                      <td class="text-muted-foreground px-4 {cellPad} text-xs whitespace-nowrap">
                        {entry.job_type === "import" ? "Import" : "Enrichissement"}
                      </td>
                      <td class="px-4 {cellPad}">
                        <StatusBadge status={entry.status} />
                      </td>
                      <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                        {entry.total_items}
                      </td>
                      <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums {entry.failed_items > 0 ? 'text-destructive font-medium' : ''}">
                        {entry.failed_items}
                      </td>
                      <td class="text-muted-foreground px-4 {cellPad} text-right text-xs whitespace-nowrap tabular-nums">
                        {formatRelativeDate(entry.created_at)}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </CardContent>
          </Card>
        {/if}

        <!-- Crédits prépayés : solde, octroi manuel, derniers mouvements -->
        <Card size="sm" class="mt-1">
          <CardHeader>
            <CardTitle class="font-title text-sm">Crédits</CardTitle>
            <CardDescription class="text-muted-foreground text-xs">
              Solde prépayé du compte. Les achats de packs sont enregistrés
              ici manuellement (pas de paiement en ligne).
            </CardDescription>
          </CardHeader>
          <CardContent class="flex flex-col gap-4">
            {#if creditsQuery.isError}
              <p class="text-destructive text-xs" role="alert">
                Impossible de charger les crédits du client.
              </p>
            {:else if credits === null}
              <Skeleton class="h-16 w-full" />
            {:else}
              <div class="flex items-baseline gap-2">
                <span
                  class="text-2xl font-semibold tabular-nums {credits.balance <= 0
                    ? 'text-destructive'
                    : 'text-foreground'}"
                >
                  {formatInt(credits.balance)}
                </span>
                <span class="text-muted-foreground text-xs">crédits restants</span>
              </div>

              <!-- Octroi / achat / ajustement -->
              <div class="grid gap-3 sm:grid-cols-[repeat(4,minmax(0,1fr))_auto]">
                <div class="flex flex-col gap-1.5">
                  <Label for="grant-credits">Crédits (signé)</Label>
                  <Input
                    id="grant-credits"
                    type="number"
                    step="1"
                    inputmode="numeric"
                    placeholder="500 ou -50"
                    bind:value={grantCredits}
                  />
                </div>
                <div class="flex flex-col gap-1.5">
                  <Label for="grant-kind">Type</Label>
                  <Select id="grant-kind" bind:value={grantKind}>
                    <option value="grant">Offert</option>
                    <option value="purchase">Achat de pack</option>
                    <option value="adjustment">Ajustement</option>
                  </Select>
                </div>
                <div class="flex flex-col gap-1.5">
                  <Label for="grant-label">Libellé</Label>
                  <Input
                    id="grant-label"
                    placeholder="Pack 500, geste commercial…"
                    bind:value={grantLabel}
                  />
                </div>
                <div class="flex flex-col gap-1.5">
                  <Label for="grant-price">Prix € (achat)</Label>
                  <Input
                    id="grant-price"
                    type="number"
                    min="0"
                    step="0.01"
                    disabled={grantKind !== "purchase"}
                    bind:value={grantPrice}
                  />
                </div>
                <div class="flex items-end">
                  <Button size="sm" disabled={granting} onclick={submitGrant}>
                    {granting ? "Enregistrement…" : "Enregistrer"}
                  </Button>
                </div>
              </div>

              <!-- Derniers mouvements -->
              {#if credits.entries.length === 0}
                <p class="text-muted-foreground text-xs">
                  Aucun mouvement pour l'instant.
                </p>
              {:else}
                <div class="overflow-x-auto">
                  <table class="w-full min-w-xl text-sm">
                    <thead>
                      <tr class="border-border border-b">
                        <th class="text-muted-foreground px-2 py-2 text-left text-xs font-medium">Date</th>
                        <th class="text-muted-foreground px-2 py-2 text-left text-xs font-medium">Type</th>
                        <th class="text-muted-foreground px-2 py-2 text-left text-xs font-medium">Libellé</th>
                        <th class="text-muted-foreground px-2 py-2 text-right text-xs font-medium">Prix €</th>
                        <th class="text-muted-foreground px-2 py-2 text-right text-xs font-medium">Crédits</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each credits.entries as entry (entry.id)}
                        <tr class="border-border border-b last:border-b-0">
                          <td class="text-muted-foreground px-2 {cellPad} text-xs whitespace-nowrap tabular-nums">
                            {formatRelativeDate(entry.created_at)}
                          </td>
                          <td class="px-2 {cellPad} text-xs whitespace-nowrap">
                            {creditKindLabel(entry.kind)}
                          </td>
                          <td class="text-muted-foreground max-w-60 truncate px-2 {cellPad} text-xs">
                            {creditEntryLabel(entry)}
                          </td>
                          <td class="text-muted-foreground px-2 {cellPad} text-right text-xs whitespace-nowrap tabular-nums">
                            {entry.price_eur != null
                              ? entry.price_eur.toLocaleString("fr-FR", {
                                  style: "currency",
                                  currency: "EUR",
                                })
                              : "—"}
                          </td>
                          <td class="px-2 {cellPad} text-right font-medium whitespace-nowrap tabular-nums {entry.credits < 0 ? 'text-destructive' : 'text-emerald-600 dark:text-emerald-400'}">
                            {entry.credits > 0 ? `+${formatInt(entry.credits)}` : formatInt(entry.credits)}
                          </td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              {/if}
            {/if}
          </CardContent>
        </Card>

        <!-- Réglages opérateur du compte -->
        <Card size="sm" class="mt-1">
          <CardHeader>
            <CardTitle class="font-title text-sm">Réglages opérateur</CardTitle>
            <CardDescription class="text-muted-foreground text-xs">
              Invisibles et non modifiables par le client : coefficient de
              facturation, minutes « temps gagné », grille de crédits,
              abonnement et packs.
            </CardDescription>
          </CardHeader>
          <CardContent class="flex flex-col gap-4">
            {#if settings === null}
              <Skeleton class="h-9 w-full" />
            {:else}
              <div class="grid gap-3 sm:grid-cols-3">
                <div class="flex flex-col gap-1.5">
                  <Label for="acc-coefficient">Coefficient de facturation</Label>
                  <Input
                    id="acc-coefficient"
                    type="number"
                    min="0"
                    step="0.05"
                    bind:value={settings.billing_coefficient}
                  />
                  <p class="text-muted-foreground text-xs">
                    Facturable = coût réel × coefficient.
                  </p>
                </div>
                <div class="flex flex-col gap-1.5">
                  <Label for="acc-min-import">Min. gagnées / fiche créée</Label>
                  <Input
                    id="acc-min-import"
                    type="number"
                    min="0"
                    max="120"
                    step="1"
                    inputmode="numeric"
                    bind:value={settings.minutes_saved_per_import_product}
                  />
                </div>
                <div class="flex flex-col gap-1.5">
                  <Label for="acc-min-enrich">Min. gagnées / fiche enrichie</Label>
                  <Input
                    id="acc-min-enrich"
                    type="number"
                    min="0"
                    max="120"
                    step="1"
                    inputmode="numeric"
                    bind:value={settings.minutes_saved_per_enriched_product}
                  />
                </div>
              </div>
              <!-- Grille de crédits par action -->
              <div class="border-border border-t pt-3">
                <p class="text-foreground mb-2 text-xs font-medium">
                  Grille de crédits par action
                </p>
                <div class="grid gap-3 sm:grid-cols-4">
                  <div class="flex flex-col gap-1.5">
                    <Label for="acc-cr-import">Produit importé</Label>
                    <Input
                      id="acc-cr-import"
                      type="number"
                      min="0"
                      step="1"
                      inputmode="numeric"
                      bind:value={settings.credit_cost_import_product}
                    />
                  </div>
                  <div class="flex flex-col gap-1.5">
                    <Label for="acc-cr-enrich">Fiche enrichie</Label>
                    <Input
                      id="acc-cr-enrich"
                      type="number"
                      min="0"
                      step="1"
                      inputmode="numeric"
                      bind:value={settings.credit_cost_enrich_item}
                    />
                  </div>
                  <div class="flex flex-col gap-1.5">
                    <Label for="acc-cr-image">Image traitée</Label>
                    <Input
                      id="acc-cr-image"
                      type="number"
                      min="0"
                      step="1"
                      inputmode="numeric"
                      bind:value={settings.credit_cost_image_process}
                    />
                  </div>
                  <div class="flex flex-col gap-1.5">
                    <Label for="acc-cr-generate">Visuel généré</Label>
                    <Input
                      id="acc-cr-generate"
                      type="number"
                      min="0"
                      step="1"
                      inputmode="numeric"
                      bind:value={settings.credit_cost_image_generate}
                    />
                  </div>
                </div>
              </div>

              <div class="grid gap-3 sm:grid-cols-2">
                <div class="flex flex-col gap-1.5">
                  <Label for="acc-cr-monthly">Crédits mensuels inclus</Label>
                  <Input
                    id="acc-cr-monthly"
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
                  <Label for="acc-cr-threshold">Seuil d'alerte solde bas</Label>
                  <Input
                    id="acc-cr-threshold"
                    type="number"
                    min="0"
                    step="1"
                    inputmode="numeric"
                    bind:value={settings.low_credit_threshold}
                  />
                </div>
              </div>

              <!-- Packs affichés au client sur sa page Consommation -->
              <div class="border-border border-t pt-3">
                <div class="mb-2 flex items-center justify-between">
                  <p class="text-foreground text-xs font-medium">Packs de crédits</p>
                  <Button size="sm" variant="outline" onclick={addPack}>
                    Ajouter un pack
                  </Button>
                </div>
                {#if (settings.credit_packs ?? []).length === 0}
                  <p class="text-muted-foreground text-xs">
                    Aucun pack affiché au client.
                  </p>
                {:else}
                  <div class="flex flex-col gap-2">
                    {#each settings.credit_packs ?? [] as pack, index (index)}
                      <div class="grid grid-cols-[1fr_1fr_auto] items-end gap-3">
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
                  </div>
                {/if}
              </div>

              <div class="flex justify-end">
                <Button size="sm" disabled={savingSettings} onclick={saveSettings}>
                  {savingSettings ? "Enregistrement…" : "Enregistrer"}
                </Button>
              </div>
            {/if}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  {/snippet}
</RequireAdmin>
