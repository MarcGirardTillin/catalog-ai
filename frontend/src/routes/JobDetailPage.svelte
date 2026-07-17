<script lang="ts">
  import { createQuery, useQueryClient } from "@tanstack/svelte-query"
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
  import { formatDuration } from "@/lib/format"

  let { appName, id }: { appName: string; id: string } = $props()

  let retrying = $state(false)

  const jobId = $derived(Number(id))
  const queryClient = useQueryClient()

  // TanStack Query : cache + polling conditionnel (2,5 s tant que le worker
  // tourne) — remplace le setInterval maison.
  const jobQuery = createQuery(() => ({
    queryKey: ["jobs", jobId],
    queryFn: async () => {
      const { data, error } = await jobsReadJob({ path: { job_id: jobId } })
      if (error || !data) throw new Error("job_not_found")
      return data
    },
    refetchInterval: (query: { state: { data?: JobPublic } }) => {
      const status = query.state.data?.status
      return status === "pending" || status === "processing" ? 2500 : false
    },
    retry: false,
  }))
  const running = $derived(
    jobQuery.data?.status === "pending" || jobQuery.data?.status === "processing",
  )
  const itemsQuery = createQuery(() => ({
    queryKey: ["jobs", jobId, "items"],
    queryFn: async () => {
      const { data } = await jobsListJobItems({
        path: { job_id: jobId },
        query: { page_size: 100 },
      })
      return data?.items ?? []
    },
    // Suit le statut du job (l'accessor est réactif) : les items avancent
    // pendant le traitement.
    refetchInterval: running ? 2500 : false,
  }))

  const job = $derived(jobQuery.data ?? null)
  const items = $derived<ItemPublic[] | null>(itemsQuery.data ?? null)
  const errorMessage = $derived(jobQuery.isError ? "Job introuvable." : null)

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

  // Ouvre le premier produit encore à vérifier (la review sérielle enchaîne).
  function startReview() {
    const first = (items ?? []).find((i) => i.status === "ready_for_review")
    if (first) navigate(`/items/${first.id}`)
  }

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
    // Le job repasse pending : le cache est mis à jour immédiatement et le
    // polling conditionnel reprend tout seul ; les items sont invalidés.
    queryClient.setQueryData(["jobs", jobId], data)
    queryClient.invalidateQueries({ queryKey: ["jobs", jobId, "items"] })
  }

  // Libellés neutres pour la méthode de résolution (white-label : jamais de
  // nom de prestataire dans l'UI).
  const SOURCE_LABELS: Record<string, string> = {
    shopify_json: "automatique",
    firecrawl: "recherche web",
    manual: "manuelle",
    needs_manual: "à confirmer",
    skipped: "non recherchée",
  }

  const COUNT_LABELS: [keyof Omit<typeof counts, "total">, string][] = [
    ["pending", "En attente"],
    ["processing", "En cours"],
    ["ready_for_review", "À vérifier"],
    ["approved", "Validés"],
    ["applied", "Appliqués"],
    ["rejected", "Écartés"],
    ["failed", "Échecs"],
  ]
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell
      {appName}
      {user}
      breadcrumbs={[
        { label: "Enrichissements", href: "/jobs" },
        { label: `Enrichissement #${id}` },
      ]}
    >
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        {#if errorMessage}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
          <Button variant="secondary" class="w-full sm:w-auto" onclick={() => navigate("/jobs")}>
            Retour aux enrichissements
          </Button>
        {:else if job === null}
          <Skeleton class="h-24 w-full" />
          <Skeleton class="h-16 w-full" />
        {:else}
          <div class="flex items-center justify-between gap-2">
            <h1 class="font-title text-lg font-bold">Enrichissement #{job.id}</h1>
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
              {#if counts.ready_for_review > 0 || retryableCount > 0}
                <div class="flex flex-wrap items-center gap-2">
                  {#if counts.ready_for_review > 0}
                    <!-- Entrée de la review sérielle : premier item à vérifier
                         (les suivants s'enchaînent via l'auto-advance). -->
                    <Button size="sm" onclick={startReview}>
                      Vérifier les produits ({counts.ready_for_review})
                    </Button>
                  {/if}
                  {#if retryableCount > 0}
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
                  {/if}
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
                        {item.product_title ??
                          item.staged_title ??
                          `Produit ${item.tillin_product_id}`}
                      </span>
                      <StatusBadge status={item.status} />
                    </div>
                    <div class="text-muted-foreground flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
                      <span class="font-mono">#{item.tillin_product_id}</span>
                      {#if item.source_method}
                        <span>
                          source : {SOURCE_LABELS[item.source_method] ??
                            item.source_method}
                        </span>
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
