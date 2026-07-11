<script lang="ts">
  import Sparkles from "@lucide/svelte/icons/sparkles"
  import { navigate } from "svelte5-router"

  import { jobsListJobs, statsDashboardStats } from "@/client"
  import type { DashboardStats, JobPublic } from "@/client"
  import { listImports } from "@/lib/api/imports"
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
  let recentJobs = $state<JobPublic[] | null>(null)
  let errorMessage = $state<string | null>(null)
  // Facturable du mois courant, déjà formaté en EUR ("—" tant que non chargé).
  let usageBillable = $state("—")
  // Somme des produits « À vérifier » sur la première page d'imports
  // (pas d'endpoint dédié — approximation raisonnable sur les plus récents).
  let importsToReview = $state("—")

  $effect(() => {
    statsDashboardStats().then(({ data, error }) => {
      if (error || !data) {
        errorMessage = "Impossible de charger les indicateurs."
        return
      }
      stats = data
    })
    jobsListJobs({ query: { page_size: 5 } }).then(({ data }) => {
      recentJobs = data?.items ?? []
    })
    listImports({ page: 1 }).then(({ data }) => {
      if (!data) return
      const count = data.items.reduce(
        (sum, imp) => sum + (imp.counts.ready_for_review ?? 0),
        0,
      )
      importsToReview = String(count)
    })
    // Consommation du mois courant (facturable) — tuile optionnelle.
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

  const tiles = $derived.by(() => {
    if (!stats) return null
    return [
      { label: "Produits enrichis", value: String(stats.applied_items ?? 0) },
      { label: "À vérifier", value: String(stats.ready_items ?? 0) },
      { label: "Enrichissements en cours", value: String(stats.running_jobs ?? 0) },
      {
        label: "Temps moyen / produit",
        value: stats.avg_item_seconds != null ? formatDuration(stats.avg_item_seconds) : "—",
      },
    ]
  })

  const autoResolveLabel = $derived(
    stats?.auto_resolve_rate != null ? `${Math.round(stats.auto_resolve_rate * 100)} %` : "—",
  )

  function jobItemsLabel(job: JobPublic): string {
    const count = job.counts.total ?? 0
    return `${count} item${count > 1 ? "s" : ""}`
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
        {:else if stats === null}
          <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-24 w-full" />
          </div>
          <Skeleton class="h-4 w-48" />
        {:else if (stats.jobs_total ?? 0) === 0}
          <!-- Empty state: no enrichment yet -->
          <Card>
            <CardContent class="flex flex-col items-center gap-3 py-10 text-center">
              <span class="bg-muted flex size-16 items-center justify-center rounded-full">
                <Sparkles size={28} class="text-muted-foreground" aria-hidden="true" />
              </span>
              <p class="text-muted-foreground text-sm">
                Aucun enrichissement pour l'instant — lancez le premier depuis les produits
              </p>
              <Button onclick={() => navigate("/products?intent=enrich")}>
                Enrichir des produits
              </Button>
            </CardContent>
          </Card>
        {:else if tiles}
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {#each tiles as tile (tile.label)}
              <Card size="sm">
                <CardContent class="flex flex-col gap-1 py-4">
                  <span class="text-muted-foreground text-xs">{tile.label}</span>
                  <span class="text-foreground text-2xl font-semibold sm:text-3xl">
                    {tile.value}
                  </span>
                </CardContent>
              </Card>
            {/each}
            <!-- Tuile Imports : produits d'import à vérifier, lien /imports -->
            <button
              type="button"
              class="cursor-pointer text-left"
              aria-label="Voir les imports à vérifier"
              onclick={() => navigate("/imports")}
            >
              <Card class="hover:ring-primary/40 h-full transition-shadow" size="sm">
                <CardContent class="flex flex-col gap-1 py-4">
                  <span class="text-muted-foreground text-xs">Imports à vérifier</span>
                  <span class="text-foreground text-2xl font-semibold tabular-nums sm:text-3xl">
                    {importsToReview}
                  </span>
                </CardContent>
              </Card>
            </button>
            <!-- Tuile Consommation : facturable du mois courant, lien /usage -->
            <button
              type="button"
              class="cursor-pointer text-left"
              aria-label="Voir la consommation du mois"
              onclick={() => navigate("/usage")}
            >
              <Card class="hover:ring-primary/40 h-full transition-shadow" size="sm">
                <CardContent class="flex flex-col gap-1 py-4">
                  <span class="text-muted-foreground text-xs">Consommation du mois</span>
                  <span class="text-foreground text-2xl font-semibold tabular-nums sm:text-3xl">
                    {usageBillable}
                  </span>
                </CardContent>
              </Card>
            </button>
          </div>
          <p class="text-muted-foreground text-xs">
            Résolution automatique
            <span class="text-foreground font-medium">{autoResolveLabel}</span>
          </p>

          <!-- Recent jobs -->
          <div class="mt-1 flex items-center justify-between gap-2">
            <h2 class="font-title text-sm font-bold">Enrichissements récents</h2>
            <a
              href="/jobs"
              class="text-primary text-xs underline-offset-2 hover:underline"
              onclick={(e) => {
                e.preventDefault()
                navigate("/jobs")
              }}
            >
              Voir tous les enrichissements →
            </a>
          </div>
          {#if recentJobs === null}
            <Skeleton class="h-16 w-full" />
            <Skeleton class="h-16 w-full" />
          {:else if recentJobs.length === 0}
            <Card size="sm">
              <CardContent class="text-muted-foreground py-4 text-center text-xs">
                Aucun enrichissement récent.
              </CardContent>
            </Card>
          {:else}
            <div class="flex flex-col gap-2">
              {#each recentJobs as job (job.id)}
                <button
                  type="button"
                  class="w-full cursor-pointer text-left"
                  onclick={() => navigate(`/jobs/${job.id}`)}
                >
                  <Card class="hover:ring-primary/40 transition-shadow" size="sm">
                    <CardContent class="flex flex-wrap items-center justify-between gap-2">
                      <div class="flex items-center gap-3">
                        <span class="font-title text-sm font-bold">Enrichissement #{job.id}</span>
                        <StatusBadge status={job.status} />
                      </div>
                      <div class="text-muted-foreground flex items-center gap-3 text-xs">
                        <span>{jobItemsLabel(job)}</span>
                        <span>{formatRelativeDate(job.created_at)}</span>
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
