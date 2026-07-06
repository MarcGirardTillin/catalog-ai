<script lang="ts">
  import { navigate } from "svelte5-router"

  import { jobsListJobs } from "@/client"
  import type { JobPublic } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppHeader from "@/lib/components/app/AppHeader.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"

  let { appName }: { appName: string } = $props()

  let jobs = $state<JobPublic[] | null>(null)
  let errorMessage = $state<string | null>(null)

  $effect(() => {
    jobsListJobs({ query: { page_size: 50 } }).then(({ data, error }) => {
      if (error || !data) {
        errorMessage = "Impossible de charger les jobs."
        return
      }
      jobs = data.items
    })
  })

  function selectionLabel(job: JobPublic): string {
    const selection = job.selection_json as { ids?: number[]; tag?: string }
    if (selection.tag) return `Tag « ${selection.tag} »`
    const count = selection.ids?.length ?? 0
    return `${count} produit${count > 1 ? "s" : ""}`
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <div class="bg-background min-h-dvh">
      <AppHeader {appName} {user} />

      <main class="mx-auto flex max-w-2xl flex-col gap-3 p-4">
        <div class="flex items-center justify-between gap-2">
          <h1 class="font-title text-lg font-bold">Jobs d'enrichissement</h1>
          <Button size="sm" onclick={() => navigate("/products")}>Nouveau job</Button>
        </div>

        {#if errorMessage}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
        {:else if jobs === null}
          <Skeleton class="h-20 w-full" />
          <Skeleton class="h-20 w-full" />
        {:else if jobs.length === 0}
          <Card>
            <CardContent class="text-muted-foreground py-6 text-center text-sm">
              Aucun job pour l'instant — lancez votre premier enrichissement.
            </CardContent>
          </Card>
        {:else}
          {#each jobs as job (job.id)}
            <button
              type="button"
              class="w-full cursor-pointer text-left"
              onclick={() => navigate(`/jobs/${job.id}`)}
            >
              <Card class="hover:ring-primary/40 transition-shadow">
                <CardContent class="flex flex-col gap-2">
                  <div class="flex items-center justify-between gap-2">
                    <span class="font-title text-sm font-bold">Job #{job.id}</span>
                    <StatusBadge status={job.status} />
                  </div>
                  <div class="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                    <span>{selectionLabel(job)}</span>
                    <span>{job.counts.total ?? 0} item{(job.counts.total ?? 0) > 1 ? "s" : ""}</span>
                    {#if (job.counts.ready_for_review ?? 0) > 0}
                      <span class="text-warning-foreground font-medium">
                        {job.counts.ready_for_review} à valider
                      </span>
                    {/if}
                    <span>{new Date(job.created_at).toLocaleString("fr-FR")}</span>
                  </div>
                </CardContent>
              </Card>
            </button>
          {/each}
        {/if}
      </main>
    </div>
  {/snippet}
</RequireAuth>
