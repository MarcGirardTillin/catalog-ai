<script lang="ts">
  import ExternalLink from "@lucide/svelte/icons/external-link"
  import { createQuery, useQueryClient } from "@tanstack/svelte-query"
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import {
    itemsApplyItemRoute,
    itemsApproveItem,
    jobsCancelJob,
    jobsListJobItems,
    jobsReadJob,
    jobsRetryJobFailures,
  } from "@/client"
  import { ConfirmButton } from "@/lib/components/ui/confirm-button"
  import type { ItemPublic, JobPublic } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import FeatureGate from "@/lib/components/app/FeatureGate.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"
  import { matchedByLabel } from "@/lib/enrich-match"
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

  // Arrêt d'un traitement en cours : les items en attente passent écartés
  // (aucun crédit débité) ; l'item en cours se termine normalement.
  let cancelling = $state(false)
  async function cancelJob() {
    if (!job || cancelling) return
    cancelling = true
    const { data, error } = await jobsCancelJob({ path: { job_id: job.id } })
    cancelling = false
    if (error || !data) {
      toast.error("Arrêt impossible.")
      return
    }
    toast.success("Traitement arrêté — les produits non traités sont écartés")
    queryClient.setQueryData(["jobs", jobId], data)
    queryClient.invalidateQueries({ queryKey: ["jobs", jobId, "items"] })
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

  // --- Validation groupée (Marc 2026-10-08) : valider plusieurs produits
  // sans passer par la vérification, comme une review où l'on ne touche à
  // rien (mêmes routes, même jeu de champs proposés). ---
  const selectable = (item: ItemPublic) =>
    item.status === "ready_for_review" || item.status === "approved"
  const selectableItems = $derived((items ?? []).filter(selectable))
  let selected = $state<Set<number>>(new Set())
  // La liste bouge (polling, décisions) : la sélection ne garde que les
  // items encore sélectionnables.
  const selectedItems = $derived(selectableItems.filter((i) => selected.has(i.id)))
  const allSelected = $derived(
    selectableItems.length > 0 && selectedItems.length === selectableItems.length,
  )
  const someSelected = $derived(selectedItems.length > 0 && !allSelected)
  const selectedToReview = $derived(
    selectedItems.filter((i) => i.status === "ready_for_review").length,
  )

  function toggleItem(itemId: number) {
    const next = new Set(selected)
    if (next.has(itemId)) next.delete(itemId)
    else next.add(itemId)
    selected = next
  }
  function toggleAll() {
    selected = allSelected ? new Set() : new Set(selectableItems.map((i) => i.id))
  }

  let bulkBusy = $state<"approve" | "apply" | null>(null)
  let bulkTotal = $state(0)
  let bulkDone = $state(0)

  async function processItem(item: ItemPublic, apply: boolean): Promise<boolean> {
    if (item.status === "ready_for_review") {
      const { error } = await itemsApproveItem({ path: { item_id: item.id } })
      if (error) return false
    }
    if (apply) {
      const { error } = await itemsApplyItemRoute({ path: { item_id: item.id } })
      if (error) return false
    }
    return true
  }

  async function bulkValidate(apply: boolean) {
    const targets = apply
      ? selectedItems
      : selectedItems.filter((i) => i.status === "ready_for_review")
    if (bulkBusy || targets.length === 0) return
    bulkBusy = apply ? "apply" : "approve"
    bulkTotal = targets.length
    bulkDone = 0
    let failed = 0
    // Trois à la fois : l'application écrit dans Tillin (images, poids).
    const queue = [...targets]
    async function worker() {
      for (let next = queue.shift(); next; next = queue.shift()) {
        if (!(await processItem(next, apply))) failed += 1
        bulkDone += 1
      }
    }
    await Promise.all([worker(), worker(), worker()])
    bulkBusy = null
    selected = new Set()
    const ok = targets.length - failed
    const verb = apply ? "validé(s) et appliqué(s)" : "validé(s)"
    if (ok > 0) toast.success(`${ok} produit(s) ${verb}`)
    if (failed > 0) {
      toast.error(`${failed} produit(s) en échec — ouvrez-les pour voir le détail.`)
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["jobs", jobId] }),
      queryClient.invalidateQueries({ queryKey: ["jobs", jobId, "items"] }),
    ])
  }

  // Libellés neutres pour la méthode de résolution (white-label : jamais de
  // nom de prestataire dans l'UI).
  const SOURCE_LABELS: Record<string, string> = {
    shopify_json: "automatique",
    firecrawl: "recherche web",
    site_search: "recherche du site",
    llm: "sélection IA",
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
      <FeatureGate
        feature="feature_enrich"
        message="Le module d'enrichissement n'est pas activé pour votre compte."
      >
      <div
        class="mx-auto flex max-w-4xl flex-col gap-3 p-4"
        class:pb-20={selectedItems.length > 0 || bulkBusy}
      >
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
              {#if running || counts.ready_for_review > 0 || retryableCount > 0}
                <div class="flex flex-wrap items-center gap-2">
                  {#if running}
                    <!-- Arrêt : les items en attente sont écartés (0 crédit),
                         l'item en cours de traitement se termine. -->
                    <ConfirmButton
                      label={cancelling ? "Arrêt…" : "Arrêter"}
                      confirmLabel="Écarter les produits restants ?"
                      disabled={cancelling}
                      onconfirm={cancelJob}
                    />
                  {/if}
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

          <div class="mt-1 flex items-center justify-between gap-2">
            <h2 class="font-title text-sm font-bold">Produits</h2>
            {#if selectableItems.length > 0}
              <label class="text-muted-foreground flex cursor-pointer items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  class="accent-primary block size-4"
                  checked={allSelected}
                  indeterminate={someSelected}
                  disabled={bulkBusy !== null}
                  onchange={toggleAll}
                />
                Tout sélectionner ({selectableItems.length})
              </label>
            {/if}
          </div>
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
              {@const matchedBy = matchedByLabel(item)}
              <div class="flex items-center gap-2">
              {#if selectableItems.length > 0}
                <!-- Case hors du bouton de la carte (contenu interactif
                     interdit dans un <button>) ; colonne gardée vide pour
                     les produits non sélectionnables (alignement). -->
                <div class="flex w-4 shrink-0 justify-center">
                  {#if selectable(item)}
                    <input
                      type="checkbox"
                      class="accent-primary block size-4"
                      aria-label={`Sélectionner ${item.product_title ?? `le produit ${item.tillin_product_id}`}`}
                      checked={selected.has(item.id)}
                      disabled={bulkBusy !== null}
                      onchange={() => toggleItem(item.id)}
                    />
                  {/if}
                </div>
              {/if}
              <button
                type="button"
                class="min-w-0 flex-1 cursor-pointer text-left"
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
                    <div class="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
                      <!-- Bouton explicite (UX Marc 2026-07-31) : « Voir le
                           produit » plutôt qu'un id cliquable opaque ; sans
                           déclencher l'ouverture de la review. -->
                      <span
                        role="link"
                        tabindex="0"
                        class="text-primary flex cursor-pointer items-center gap-1 underline-offset-2 hover:underline"
                        onclick={(e) => {
                          e.stopPropagation()
                          navigate(`/products?product=${item.tillin_product_id}`)
                        }}
                        onkeydown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault()
                            e.stopPropagation()
                            navigate(`/products?product=${item.tillin_product_id}`)
                          }
                        }}
                      >
                        <ExternalLink size={12} aria-hidden="true" />
                        Voir le produit
                      </span>
                      {#if item.source_method}
                        <span>
                          source : {SOURCE_LABELS[item.source_method] ??
                            item.source_method}
                        </span>
                      {/if}
                      {#if matchedBy}
                        <span>trouvé par : {matchedBy}</span>
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
              </div>
            {/each}
          {/if}
        {/if}
      </div>
      {#if selectedItems.length > 0 || bulkBusy}
        <!-- Barre d'actions de la sélection (même motif que la recherche
             produits). « Valider » ne concerne que les produits à vérifier. -->
        <div class="border-border bg-card fixed inset-x-0 bottom-0 border-t sm:left-60">
          <div class="p-3">
            <div class="mx-auto flex max-w-4xl flex-wrap items-center gap-2 sm:justify-end">
              <span class="text-muted-foreground mr-auto text-xs">
                {bulkBusy
                  ? `Traitement… ${bulkDone}/${bulkTotal}`
                  : `${selectedItems.length} sélectionné(s)`}
              </span>
              <Button
                variant="ghost"
                size="sm"
                disabled={bulkBusy !== null}
                onclick={() => (selected = new Set())}
              >
                Vider
              </Button>
              {#if selectedToReview > 0}
                <Button
                  variant="outline"
                  size="sm"
                  disabled={bulkBusy !== null}
                  onclick={() => bulkValidate(false)}
                >
                  Valider ({selectedToReview})
                </Button>
              {/if}
              <Button size="sm" disabled={bulkBusy !== null} onclick={() => bulkValidate(true)}>
                Valider et appliquer ({selectedItems.length})
              </Button>
            </div>
          </div>
        </div>
      {/if}
      </FeatureGate>
    </AppShell>
  {/snippet}
</RequireAuth>
