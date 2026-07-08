<script lang="ts">
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import { jobsListJobItems, jobsReadJob, jobsRetryJobFailures } from "@/client"
  import type { ItemPublic, JobPublic } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"

  let { appName, id }: { appName: string; id: string } = $props()

  let job = $state<JobPublic | null>(null)
  let items = $state<ItemPublic[] | null>(null)
  let errorMessage = $state<string | null>(null)
  let retrying = $state(false)

  async function load() {
    const jobId = Number(id)
    const [jobResult, itemsResult] = await Promise.all([
      jobsReadJob({ path: { job_id: jobId } }),
      jobsListJobItems({ path: { job_id: jobId }, query: { page_size: 100 } }),
    ])
    if (jobResult.error || !jobResult.data) {
      errorMessage = "Job introuvable."
      return
    }
    job = jobResult.data
    items = itemsResult.data?.items ?? []
  }

  // Initial load + poll every 2.5s while the worker is still busy.
  $effect(() => {
    load()
    const timer = setInterval(() => {
      if (job && (job.status === "pending" || job.status === "processing")) {
        load()
      }
    }, 2500)
    return () => clearInterval(timer)
  })

  // OpenAPI marks the pydantic-defaulted count fields optional — normalize.
  const counts = $derived.by(() => {
    const c = job?.counts
    return {
      total: c?.total ?? 0,
      pending: c?.pending ?? 0,
      processing: c?.processing ?? 0,
      ready_for_review: c?.ready_for_review ?? 0,
      approved: c?.approved ?? 0,
      applied: c?.applied ?? 0,
      rejected: c?.rejected ?? 0,
      failed: c?.failed ?? 0,
    }
  })

  const progress = $derived.by(() => {
    if (counts.total === 0) return 0
    const done = counts.total - counts.pending - counts.processing
    return Math.round((done / counts.total) * 100)
  })

  function formatDuration(seconds: number): string {
    const s = Math.round(seconds)
    if (s < 60) return `${s} s`
    const m = Math.floor(s / 60)
    const rem = s % 60
    return rem === 0 ? `${m} min` : `${m} min ${rem} s`
  }

  // Live elapsed while the job is still running (recomputed on each poll tick).
  let now = $state(Date.now())
  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 1000)
    return () => clearInterval(t)
  })

  const timing = $derived.by(() => {
    if (!job) return null
    if (job.duration_seconds != null) {
      return { label: "Durée", value: formatDuration(job.duration_seconds) }
    }
    if (job.started_at) {
      const elapsed = (now - new Date(job.started_at).getTime()) / 1000
      return { label: "En cours depuis", value: formatDuration(Math.max(0, elapsed)) }
    }
    return null
  })

  const retryableCount = $derived(counts.failed + counts.rejected)

  async function retryFailures() {
    if (!job) return
    const count = retryableCount
    retrying = true
    const { data, error } = await jobsRetryJobFailures({ path: { job_id: job.id } })
    retrying = false
    if (error || !data) {
      toast.error("Relance impossible.")
      return
    }
    toast.success(`Relance des échecs lancée (${count} item${count > 1 ? "s" : ""})`)
    job = data
    load() // refresh items; polling resumes since the job is pending again
  }

  const COUNT_LABELS: [keyof Omit<typeof counts, "total">, string][] = [
    ["pending", "En attente"],
    ["processing", "En cours"],
    ["ready_for_review", "À valider"],
    ["approved", "Validés"],
    ["applied", "Appliqués"],
    ["rejected", "Rejetés"],
    ["failed", "Échecs"],
  ]
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell
      {appName}
      {user}
      breadcrumbs={[{ label: "Jobs", href: "/jobs" }, { label: `Job #${id}` }]}
    >
      <div class="mx-auto flex max-w-2xl flex-col gap-3 p-4">
        {#if errorMessage}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
          <Button variant="secondary" class="w-full sm:w-auto" onclick={() => navigate("/jobs")}>
            Retour aux jobs
          </Button>
        {:else if job === null}
          <Skeleton class="h-24 w-full" />
          <Skeleton class="h-16 w-full" />
        {:else}
          <div class="flex items-center justify-between gap-2">
            <h1 class="font-title text-lg font-bold">Job #{job.id}</h1>
            <StatusBadge status={job.status} />
          </div>

          <Card>
            <CardContent class="flex flex-col gap-3">
              <!-- Progress bar -->
              <div class="flex items-center gap-3">
                <div class="bg-muted h-2 flex-1 overflow-hidden rounded-full">
                  <div
                    class="bg-primary h-full rounded-full transition-all"
                    style={`width: ${progress}%`}
                  ></div>
                </div>
                <span class="text-muted-foreground font-mono text-xs">{progress}%</span>
              </div>
              {#if timing}
                <div class="text-muted-foreground flex items-center gap-1.5 text-xs">
                  <span>{timing.label}</span>
                  <span class="text-foreground font-mono font-medium">{timing.value}</span>
                </div>
              {/if}
              <dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-xs sm:grid-cols-4">
                {#each COUNT_LABELS as [key, label] (key)}
                  {#if counts[key] > 0}
                    <div>
                      <dt class="text-muted-foreground">{label}</dt>
                      <dd class="font-mono font-medium">{counts[key]}</dd>
                    </div>
                  {/if}
                {/each}
              </dl>
              {#if retryableCount > 0}
                <div class="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={retrying}
                    onclick={retryFailures}
                  >
                    {retrying
                      ? "Relance…"
                      : `Relancer les échecs (${retryableCount})`}
                  </Button>
                </div>
              {/if}
            </CardContent>
          </Card>

          <h2 class="font-title mt-1 text-sm font-bold">Produits</h2>
          {#if items === null}
            <Skeleton class="h-16 w-full" />
          {:else if items.length === 0}
            <Card>
              <CardContent class="text-muted-foreground py-6 text-center text-sm">
                Aucun item — les sélections par tag sont résolues quand la
                lecture catalogue est branchée.
              </CardContent>
            </Card>
          {:else}
            {#each items as item (item.id)}
              <button
                type="button"
                class="w-full cursor-pointer text-left"
                onclick={() => navigate(`/items/${item.id}`)}
              >
                <Card class="hover:ring-primary/40 transition-shadow" size="sm">
                  <CardContent class="flex flex-col gap-1.5">
                    <div class="flex items-center justify-between gap-2">
                      <span class="text-sm font-medium">
                        {item.staged_title ?? `Produit ${item.tillin_product_id}`}
                      </span>
                      <StatusBadge status={item.status} />
                    </div>
                    <div class="text-muted-foreground flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
                      <span class="font-mono">#{item.tillin_product_id}</span>
                      {#if item.source_method}
                        <span>source : {item.source_method}</span>
                      {/if}
                      {#if item.match_score != null}
                        <span class="font-mono">score {item.match_score.toFixed(2)}</span>
                      {/if}
                      {#if item.duration_seconds != null}
                        <span class="font-mono">⏱ {formatDuration(item.duration_seconds)}</span>
                      {/if}
                      {#if item.error}
                        <span class="text-destructive">{item.error}</span>
                      {/if}
                    </div>
                  </CardContent>
                </Card>
              </button>
            {/each}
          {/if}
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
