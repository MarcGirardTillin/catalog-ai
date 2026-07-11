<script lang="ts">
  import { navigate } from "svelte5-router"

  import { jobsListJobs } from "@/client"
  import type { JobPublic } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import { prefs } from "@/lib/preferences.svelte"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"
  import { formatDuration, formatRelativeDate } from "@/lib/format"

  let { appName }: { appName: string } = $props()

  // Densité des tables : padding vertical des cellules selon la préférence.
  const cellPad = $derived(prefs.density === "compact" ? "py-1" : "py-2.5")

  let jobs = $state<JobPublic[] | null>(null)
  let errorMessage = $state<string | null>(null)

  $effect(() => {
    jobsListJobs({ query: { page_size: 50 } }).then(({ data, error }) => {
      if (error || !data) {
        errorMessage = "Impossible de charger les enrichissements."
        return
      }
      jobs = data.items
    })
  })

  // done = total - pending - processing (same rule as JobDetailPage).
  function progressOf(job: JobPublic): { done: number; total: number; percent: number } {
    const total = job.counts.total ?? 0
    const pending = job.counts.pending ?? 0
    const processing = job.counts.processing ?? 0
    const done = Math.max(0, total - pending - processing)
    return { done, total, percent: total === 0 ? 0 : Math.round((done / total) * 100) }
  }

  // Suivi par produit : où en sont les items du job (vocabulaire harmonisé).
  // Le statut « Terminé » du job dit seulement que le traitement IA est fini —
  // ces puces disent si les produits sont à vérifier, appliqués, etc.
  type Chip = { label: string; count: number; tone: string }
  function statusChips(job: JobPublic): Chip[] {
    const c = job.counts
    const defs: Chip[] = [
      {
        label: "à vérifier",
        count: c.ready_for_review ?? 0,
        tone: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
      },
      {
        label: "validés",
        count: c.approved ?? 0,
        tone: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
      },
      {
        label: "appliqués",
        count: c.applied ?? 0,
        tone: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
      },
      {
        label: "écartés",
        count: c.rejected ?? 0,
        tone: "bg-muted text-muted-foreground",
      },
      {
        label: "échecs",
        count: c.failed ?? 0,
        tone: "bg-destructive/15 text-destructive",
      },
    ]
    return defs.filter((chip) => chip.count > 0)
  }

  function openJob(id: number) {
    navigate(`/jobs/${id}`)
  }

  function onRowKeydown(event: KeyboardEvent, id: number) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      openJob(id)
    }
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Enrichissements" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <div class="flex items-center justify-between gap-2">
          <h1 class="font-title text-lg font-bold">Enrichissements</h1>
          <Button size="sm" onclick={() => navigate("/products?intent=enrich")}>
            Nouvel enrichissement
          </Button>
        </div>

        {#if errorMessage}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
        {:else if jobs === null}
          <Skeleton class="h-10 w-full" />
          <Skeleton class="h-10 w-full" />
          <Skeleton class="h-10 w-full" />
        {:else if jobs.length === 0}
          <Card>
            <CardContent class="flex flex-col items-center gap-3 py-8 text-center">
              <p class="text-muted-foreground text-sm">
                Aucun enrichissement — créez le premier depuis la recherche produits.
              </p>
              <Button onclick={() => navigate("/products?intent=enrich")}>
                Enrichir des produits
              </Button>
            </CardContent>
          </Card>
        {:else}
          <Card class="py-0">
            <CardContent class="overflow-x-auto px-0">
              <table class="w-full min-w-xl text-sm">
                <thead>
                  <tr class="border-border border-b">
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Enrichissement</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Statut</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Progression</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Suivi produits</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Produits</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Durée</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Créé</th>
                  </tr>
                </thead>
                <tbody>
                  {#each jobs as job (job.id)}
                    {@const progress = progressOf(job)}
                    {@const chips = statusChips(job)}
                    <tr
                      role="link"
                      tabindex="0"
                      aria-label={`Ouvrir l'enrichissement #${job.id}`}
                      class="border-border hover:bg-muted/50 focus-visible:bg-muted/50 cursor-pointer border-b outline-none transition-colors last:border-b-0"
                      onclick={() => openJob(job.id)}
                      onkeydown={(e) => onRowKeydown(e, job.id)}
                    >
                      <td class="px-4 {cellPad} font-medium whitespace-nowrap">#{job.id}</td>
                      <td class="px-4 {cellPad}"><StatusBadge status={job.status} /></td>
                      <td class="px-4 {cellPad}">
                        <div class="flex items-center gap-2">
                          <div class="bg-muted h-1.5 w-20 shrink-0 overflow-hidden rounded-full">
                            <div
                              class="bg-primary h-full rounded-full transition-all"
                              style={`width: ${progress.percent}%`}
                            ></div>
                          </div>
                          <span class="text-muted-foreground text-xs whitespace-nowrap tabular-nums">
                            {progress.done}/{progress.total}
                          </span>
                        </div>
                      </td>
                      <td class="px-4 {cellPad}">
                        {#if chips.length > 0}
                          <div class="flex flex-wrap gap-1">
                            {#each chips as chip (chip.label)}
                              <span
                                class="rounded-full px-2 py-0.5 text-[11px] whitespace-nowrap {chip.tone}"
                              >
                                {chip.count} {chip.label}
                              </span>
                            {/each}
                          </div>
                        {:else}
                          <span class="text-muted-foreground text-xs">—</span>
                        {/if}
                      </td>
                      <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                        {job.counts.total ?? 0}
                      </td>
                      <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                        {job.duration_seconds != null ? formatDuration(job.duration_seconds) : "—"}
                      </td>
                      <td class="text-muted-foreground px-4 {cellPad} text-right text-xs whitespace-nowrap tabular-nums">
                        {formatRelativeDate(job.created_at)}
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
</RequireAuth>
