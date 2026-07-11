<script lang="ts">
  // Tableau de bord client, orienté action : « qu'est-ce qui m'attend » (À
  // traiter), la valeur du mois (dont le temps gagné), et l'activité récente
  // fusionnée (enrichissements + imports). Tous les compteurs viennent du
  // serveur (DashboardStats) — plus d'approximation page-1.
  import CircleCheck from "@lucide/svelte/icons/circle-check"
  import ClipboardCheck from "@lucide/svelte/icons/clipboard-check"
  import LoaderCircle from "@lucide/svelte/icons/loader-circle"
  import Send from "@lucide/svelte/icons/send"
  import Sparkles from "@lucide/svelte/icons/sparkles"
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert"
  import { navigate } from "svelte5-router"

  import { jobsListJobs, statsDashboardStats } from "@/client"
  import type { Component } from "svelte"
  import type { DashboardStats, JobPublic } from "@/client"
  import { listImports, type ImportJobPublic } from "@/lib/api/imports"
  import { getUsageSummary } from "@/lib/api/usage"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"
  import { formatDuration, formatRelativeDate } from "@/lib/format"

  let { appName }: { appName: string } = $props()

  let stats = $state<DashboardStats | null>(null)
  let errorMessage = $state<string | null>(null)
  // Facturable du mois courant, déjà formaté en EUR ("—" tant que non chargé).
  let usageBillable = $state("—")

  // Activité récente : enrichissements + imports fusionnés par date.
  type ActivityEntry = {
    key: string
    kind: "enrichment" | "import"
    id: number
    label: string
    status: string
    detail: string
    created_at: string
  }
  let activity = $state<ActivityEntry[] | null>(null)

  function jobChips(counts: JobPublic["counts"]): string {
    const parts: string[] = []
    const ready = counts.ready_for_review ?? 0
    const applied = counts.applied ?? 0
    const failed = counts.failed ?? 0
    if (ready > 0) parts.push(`${ready} à vérifier`)
    if (applied > 0) parts.push(`${applied} appliqué${applied > 1 ? "s" : ""}`)
    if (failed > 0) parts.push(`${failed} échec${failed > 1 ? "s" : ""}`)
    return parts.join(" · ") || `${counts.total ?? 0} produit${(counts.total ?? 0) > 1 ? "s" : ""}`
  }

  function importChips(imp: ImportJobPublic): string {
    const parts: string[] = []
    const ready = imp.counts.ready_for_review ?? 0
    const applied = imp.counts.applied ?? 0
    if (ready > 0) parts.push(`${ready} à transférer`)
    if (applied > 0) parts.push(`${applied} transféré${applied > 1 ? "s" : ""}`)
    return parts.join(" · ") || `${imp.counts.total} produit${imp.counts.total > 1 ? "s" : ""}`
  }

  $effect(() => {
    statsDashboardStats().then(({ data, error }) => {
      if (error || !data) {
        errorMessage = "Impossible de charger les indicateurs."
        return
      }
      stats = data
    })
    // Activité récente fusionnée (5 entrées max, tous types confondus).
    Promise.all([
      jobsListJobs({ query: { page_size: 5 } }),
      listImports({ page: 1, page_size: 5 }),
    ]).then(([jobsResult, importsResult]) => {
      const entries: ActivityEntry[] = []
      for (const job of jobsResult.data?.items ?? []) {
        entries.push({
          key: `job-${job.id}`,
          kind: "enrichment",
          id: job.id,
          label: `Enrichissement #${job.id}`,
          status: job.status,
          detail: jobChips(job.counts),
          created_at: job.created_at,
        })
      }
      for (const imp of importsResult.data?.items ?? []) {
        entries.push({
          key: `import-${imp.id}`,
          kind: "import",
          id: imp.id,
          label: imp.file_name,
          status: imp.status,
          detail: importChips(imp),
          created_at: imp.created_at,
        })
      }
      entries.sort((a, b) => b.created_at.localeCompare(a.created_at))
      activity = entries.slice(0, 5)
    })
    // Consommation du mois courant (facturable) — tuile vers /usage.
    const now = new Date()
    const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
    getUsageSummary(month).then(({ data, error }) => {
      if (error || !data) return
      const billable = Number(data.totals.billable)
      usageBillable = Number.isFinite(billable)
        ? billable.toLocaleString("fr-FR", {
            style: "currency",
            currency: data.currency || "EUR",
          })
        : "—"
    })
  })

  // --- « À traiter » : cartes actionnables (masquées à zéro). ---
  type TodoCard = {
    key: string
    label: string
    count: number
    href: string
    icon: Component
    tone: string
  }
  const todoCards = $derived.by<TodoCard[] | null>(() => {
    if (!stats) return null
    const cards: TodoCard[] = [
      {
        key: "review",
        label: "produits à vérifier",
        count: stats.ready_items ?? 0,
        href: "/jobs",
        icon: ClipboardCheck,
        tone: "text-amber-600 dark:text-amber-500",
      },
      {
        key: "transfer",
        label: "produits à transférer vers Tillin",
        count: stats.imports_to_transfer ?? 0,
        href: "/imports",
        icon: Send,
        tone: "text-blue-600 dark:text-blue-500",
      },
      {
        key: "running",
        label: "traitements en cours",
        count: (stats.running_jobs ?? 0) + (stats.imports_processing ?? 0),
        href: "/jobs",
        icon: LoaderCircle,
        tone: "text-muted-foreground",
      },
      {
        key: "failed",
        label: "échecs à relancer",
        count: stats.failed_items ?? 0,
        href: "/jobs",
        icon: TriangleAlert,
        tone: "text-destructive",
      },
    ]
    return cards.filter((card) => card.count > 0)
  })

  // --- « Ce mois-ci » ---
  /** "6 h 40" depuis des minutes ; "25 min" sous l'heure. */
  function formatMinutes(minutes: number): string {
    if (minutes < 60) return `${minutes} min`
    const h = Math.floor(minutes / 60)
    const rem = minutes % 60
    return rem === 0 ? `${h} h` : `${h} h ${String(rem).padStart(2, "0")}`
  }

  const monthTiles = $derived.by(() => {
    if (!stats) return null
    return [
      {
        key: "saved",
        label: "Temps gagné ce mois-ci",
        value: `≈ ${formatMinutes(stats.minutes_saved_this_month ?? 0)}`,
        href: null as string | null,
        highlight: true,
      },
      {
        key: "enriched",
        label: "Fiches enrichies",
        value: String(stats.applied_this_month ?? 0),
        href: null,
        highlight: false,
      },
      {
        key: "imported",
        label: "Fiches importées",
        value: String(stats.imported_this_month ?? 0),
        href: null,
        highlight: false,
      },
      {
        key: "usage",
        label: "Consommation du mois",
        value: usageBillable,
        href: "/usage",
        highlight: false,
      },
      {
        key: "avg",
        label: "Temps moyen / produit",
        value:
          stats.avg_item_seconds != null
            ? formatDuration(stats.avg_item_seconds)
            : "—",
        href: null,
        highlight: false,
      },
      {
        key: "auto",
        label: "Résolution automatique",
        value:
          stats.auto_resolve_rate != null
            ? `${Math.round(stats.auto_resolve_rate * 100)} %`
            : "—",
        href: null,
        highlight: false,
      },
    ]
  })

  function activityHref(entry: ActivityEntry): string {
    return entry.kind === "import" ? `/imports/${entry.id}` : `/jobs/${entry.id}`
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Tableau de bord" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-4 p-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h1 class="font-title text-lg font-bold">Tableau de bord</h1>
          <Button size="sm" onclick={() => navigate("/products?intent=enrich")}>
            <Sparkles size={14} />
            Enrichir des produits
          </Button>
        </div>

        {#if errorMessage}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
        {:else if stats === null || todoCards === null || monthTiles === null}
          <Skeleton class="h-20 w-full" />
          <div class="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
          </div>
          <Skeleton class="h-24 w-full" />
        {:else}
          <!-- À traiter : ce qui attend une action, tous types confondus. -->
          <h2 class="font-title text-sm font-bold">À traiter</h2>
          {#if todoCards.length === 0}
            <Card size="sm">
              <CardContent class="flex items-center gap-2.5 py-4">
                <CircleCheck
                  size={18}
                  class="shrink-0 text-emerald-600 dark:text-emerald-500"
                  aria-hidden="true"
                />
                <p class="text-sm">
                  Rien en attente — tout est vérifié et transféré.
                </p>
              </CardContent>
            </Card>
          {:else}
            <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {#each todoCards as card (card.key)}
                <button
                  type="button"
                  class="cursor-pointer text-left"
                  aria-label={`${card.count} ${card.label}`}
                  onclick={() => navigate(card.href)}
                >
                  <Card class="hover:ring-primary/40 h-full transition-shadow" size="sm">
                    <CardContent class="flex flex-col gap-1 py-4">
                      <card.icon size={16} class={card.tone} aria-hidden="true" />
                      <span class="text-foreground text-2xl font-semibold tabular-nums">
                        {card.count}
                      </span>
                      <span class="text-muted-foreground text-xs">{card.label}</span>
                    </CardContent>
                  </Card>
                </button>
              {/each}
            </div>
          {/if}

          <!-- Ce mois-ci : la valeur produite (temps gagné en tête). -->
          <h2 class="font-title mt-1 text-sm font-bold">Ce mois-ci</h2>
          <div class="grid grid-cols-2 gap-3 lg:grid-cols-3">
            {#each monthTiles as tile (tile.key)}
              {#if tile.href}
                <button
                  type="button"
                  class="cursor-pointer text-left"
                  aria-label={tile.label}
                  onclick={() => tile.href && navigate(tile.href)}
                >
                  <Card class="hover:ring-primary/40 h-full transition-shadow" size="sm">
                    <CardContent class="flex flex-col gap-1 py-4">
                      <span class="text-muted-foreground text-xs">{tile.label}</span>
                      <span class="text-foreground text-2xl font-semibold tabular-nums">
                        {tile.value}
                      </span>
                    </CardContent>
                  </Card>
                </button>
              {:else}
                <Card
                  size="sm"
                  class={tile.highlight ? "ring-primary/30 ring-1" : ""}
                >
                  <CardContent class="flex flex-col gap-1 py-4">
                    <span class="text-muted-foreground text-xs">{tile.label}</span>
                    <span
                      class="text-2xl font-semibold tabular-nums {tile.highlight
                        ? 'text-primary'
                        : 'text-foreground'}"
                    >
                      {tile.value}
                    </span>
                  </CardContent>
                </Card>
              {/if}
            {/each}
          </div>

          <!-- Activité récente : enrichissements + imports fusionnés. -->
          <div class="mt-1 flex items-center justify-between gap-2">
            <h2 class="font-title text-sm font-bold">Activité récente</h2>
            <div class="flex items-center gap-3">
              <a
                href="/imports"
                class="text-primary text-xs underline-offset-2 hover:underline"
                onclick={(e) => {
                  e.preventDefault()
                  navigate("/imports")
                }}
              >
                Imports →
              </a>
              <a
                href="/jobs"
                class="text-primary text-xs underline-offset-2 hover:underline"
                onclick={(e) => {
                  e.preventDefault()
                  navigate("/jobs")
                }}
              >
                Enrichissements →
              </a>
            </div>
          </div>
          {#if activity === null}
            <Skeleton class="h-16 w-full" />
            <Skeleton class="h-16 w-full" />
          {:else if activity.length === 0}
            <Card size="sm">
              <CardContent class="flex flex-col items-center gap-3 py-8 text-center">
                <span class="bg-muted flex size-12 items-center justify-center rounded-full">
                  <Sparkles size={20} class="text-muted-foreground" aria-hidden="true" />
                </span>
                <p class="text-muted-foreground max-w-md text-sm">
                  Aucune activité pour l'instant — importez un bon de commande
                  fournisseur ou enrichissez vos premiers produits.
                </p>
                <div class="flex flex-wrap justify-center gap-2">
                  <Button variant="outline" size="sm" onclick={() => navigate("/imports/new")}>
                    Importer un fichier
                  </Button>
                  <Button size="sm" onclick={() => navigate("/products?intent=enrich")}>
                    Enrichir des produits
                  </Button>
                </div>
              </CardContent>
            </Card>
          {:else}
            <div class="flex flex-col gap-2">
              {#each activity as entry (entry.key)}
                <button
                  type="button"
                  class="w-full cursor-pointer text-left"
                  onclick={() => navigate(activityHref(entry))}
                >
                  <Card class="hover:ring-primary/40 transition-shadow" size="sm">
                    <CardContent class="flex flex-wrap items-center justify-between gap-2">
                      <div class="flex min-w-0 items-center gap-3">
                        <span
                          class="bg-muted text-muted-foreground shrink-0 rounded-full px-2 py-0.5 text-[11px]"
                        >
                          {entry.kind === "import" ? "Import" : "Enrichissement"}
                        </span>
                        <span class="font-title truncate text-sm font-bold" title={entry.label}>
                          {entry.label}
                        </span>
                        <StatusBadge
                          status={entry.status}
                          context={entry.kind === "import" ? "import" : undefined}
                        />
                      </div>
                      <div class="text-muted-foreground flex shrink-0 items-center gap-3 text-xs">
                        <span>{entry.detail}</span>
                        <span>{formatRelativeDate(entry.created_at)}</span>
                      </div>
                    </CardContent>
                  </Card>
                </button>
              {/each}
            </div>
          {/if}
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
