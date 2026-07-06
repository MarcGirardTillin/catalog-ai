<script lang="ts">
  import { navigate } from "svelte5-router"

  import {
    itemsApplyItemRoute,
    itemsApproveItem,
    itemsPatchItem,
    itemsReadItem,
    itemsRejectItem,
  } from "@/client"
  import type { ItemPublic } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent, CardHeader, CardTitle } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import AppHeader from "@/lib/components/app/AppHeader.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import StatusBadge from "@/lib/components/app/StatusBadge.svelte"

  let { appName, id }: { appName: string; id: string } = $props()

  let item = $state<ItemPublic | null>(null)
  let errorMessage = $state<string | null>(null)
  let busy = $state(false)

  // Editable staged fields (review-time corrections).
  let title = $state("")
  let description = $state("")
  let meta = $state("")

  function hydrate(data: ItemPublic) {
    item = data
    title = data.staged_title ?? ""
    description = data.staged_description ?? ""
    meta = data.staged_meta ?? ""
  }

  $effect(() => {
    itemsReadItem({ path: { item_id: Number(id) } }).then(({ data, error }) => {
      if (error || !data) {
        errorMessage = "Item introuvable."
        return
      }
      hydrate(data)
    })
  })

  const reviewable = $derived(item?.status === "ready_for_review")
  const applicable = $derived(item?.status === "approved")
  const dirty = $derived(
    item !== null &&
      (title !== (item.staged_title ?? "") ||
        description !== (item.staged_description ?? "") ||
        meta !== (item.staged_meta ?? "")),
  )
  const images = $derived(
    (item?.staged_images_json ?? []) as { url: string; position?: number }[],
  )
  const weights = $derived(
    (item?.staged_weights_json ?? []) as {
      variant_id: number
      weight: number
      weight_unit: string
    }[],
  )

  async function save(): Promise<boolean> {
    if (!item) return false
    busy = true
    const { data, error } = await itemsPatchItem({
      path: { item_id: item.id },
      body: {
        staged_title: title || null,
        staged_description: description || null,
        staged_meta: meta || null,
      },
    })
    busy = false
    if (error || !data) {
      errorMessage = "Enregistrement impossible."
      return false
    }
    hydrate(data)
    return true
  }

  async function decide(decision: "approve" | "reject") {
    if (!item) return
    if (decision === "approve" && dirty && !(await save())) return
    busy = true
    const call = decision === "approve" ? itemsApproveItem : itemsRejectItem
    const { data, error } = await call({ path: { item_id: item.id } })
    busy = false
    if (error || !data) {
      errorMessage = "Action impossible."
      return
    }
    navigate(`/jobs/${data.job_id}`)
  }

  async function apply() {
    if (!item) return
    busy = true
    errorMessage = null
    const { data, error } = await itemsApplyItemRoute({ path: { item_id: item.id } })
    busy = false
    if (error || !data) {
      errorMessage = "Écriture vers Tillin impossible. Réessayez."
      return
    }
    navigate(`/jobs/${data.job_id}`)
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <div class="bg-background min-h-dvh">
      <AppHeader {appName} {user} />

      <main class="mx-auto flex max-w-2xl flex-col gap-3 p-4 pb-24">
        {#if errorMessage && item === null}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
          <Button variant="secondary" class="w-full sm:w-auto" onclick={() => navigate("/jobs")}>
            Retour aux jobs
          </Button>
        {:else if item === null}
          <Skeleton class="h-24 w-full" />
          <Skeleton class="h-40 w-full" />
        {:else}
          <div class="flex items-center justify-between gap-2">
            <button
              type="button"
              class="text-muted-foreground hover:text-foreground cursor-pointer text-xs"
              onclick={() => navigate(`/jobs/${item?.job_id}`)}
            >
              ← Job #{item.job_id}
            </button>
            <StatusBadge status={item.status} />
          </div>

          <h1 class="font-title text-lg font-bold">
            Produit #{item.tillin_product_id}
          </h1>

          <!-- Source resolution -->
          <Card size="sm">
            <CardContent class="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
              {#if item.source_url}
                <a
                  href={item.source_url}
                  target="_blank"
                  rel="noreferrer"
                  class="text-primary underline underline-offset-2"
                >
                  Page source ↗
                </a>
              {/if}
              {#if item.source_method}
                <span>méthode : {item.source_method}</span>
              {/if}
              {#if item.match_score != null}
                <span class="font-mono">score {item.match_score.toFixed(2)}</span>
              {/if}
              {#if item.error}
                <span class="text-destructive">{item.error}</span>
              {/if}
              {#if !item.source_url && !item.error}
                <span>Pas de page source résolue.</span>
              {/if}
            </CardContent>
          </Card>

          <!-- Staged content (editable while ready_for_review) -->
          <Card>
            <CardHeader>
              <CardTitle class="font-title text-sm">Contenu proposé</CardTitle>
            </CardHeader>
            <CardContent class="flex flex-col gap-4">
              <div class="flex flex-col gap-1.5">
                <Label for="staged-title">Titre</Label>
                <Input id="staged-title" bind:value={title} disabled={!reviewable} />
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for="staged-description">Description</Label>
                <textarea
                  id="staged-description"
                  rows="6"
                  class="border-input bg-background placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 w-full rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1 disabled:pointer-events-none disabled:opacity-50"
                  placeholder="Pas de description générée (copie IA non branchée)."
                  bind:value={description}
                  disabled={!reviewable}
                ></textarea>
              </div>
              <div class="flex flex-col gap-1.5">
                <Label for="staged-meta">Meta description</Label>
                <Input
                  id="staged-meta"
                  bind:value={meta}
                  placeholder="Pas de meta générée."
                  disabled={!reviewable}
                />
              </div>
              {#if reviewable && dirty}
                <Button variant="secondary" size="sm" class="self-start" disabled={busy} onclick={save}>
                  Enregistrer les corrections
                </Button>
              {/if}
            </CardContent>
          </Card>

          {#if images.length > 0}
            <Card>
              <CardHeader>
                <CardTitle class="font-title text-sm">Images source ({images.length})</CardTitle>
              </CardHeader>
              <CardContent>
                <div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {#each images as image (image.url)}
                    <img
                      src={image.url}
                      alt={`Source ${image.position ?? ""}`}
                      loading="lazy"
                      class="bg-muted aspect-[4/5] w-full rounded-md object-cover"
                    />
                  {/each}
                </div>
              </CardContent>
            </Card>
          {/if}

          {#if weights.length > 0}
            <Card>
              <CardHeader>
                <CardTitle class="font-title text-sm">Poids proposés</CardTitle>
              </CardHeader>
              <CardContent class="flex flex-col gap-1 text-xs">
                {#each weights as row (row.variant_id)}
                  <div class="flex items-center justify-between gap-2">
                    <span class="text-muted-foreground font-mono">variante {row.variant_id}</span>
                    <span class="font-mono font-medium">{row.weight} {row.weight_unit}</span>
                  </div>
                {/each}
              </CardContent>
            </Card>
          {/if}

          {#if errorMessage}
            <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
          {/if}

          {#if reviewable}
            <!-- Sticky decision bar: thumb-reachable on mobile. -->
            <div
              class="border-border bg-card fixed inset-x-0 bottom-0 border-t p-3"
            >
              <div class="mx-auto flex max-w-2xl gap-2">
                <Button
                  variant="outline"
                  class="text-destructive flex-1"
                  disabled={busy}
                  onclick={() => decide("reject")}
                >
                  Rejeter
                </Button>
                <Button class="flex-1" disabled={busy} onclick={() => decide("approve")}>
                  {dirty ? "Enregistrer et valider" : "Valider"}
                </Button>
              </div>
            </div>
          {:else if applicable}
            <!-- Approved item: manual push to Tillin (no auto-push). -->
            <div class="border-border bg-card fixed inset-x-0 bottom-0 border-t p-3">
              <div class="mx-auto flex max-w-2xl items-center gap-3">
                <span class="text-muted-foreground hidden text-xs sm:inline">
                  Validé — prêt à écrire dans Tillin.
                </span>
                <Button class="flex-1 sm:flex-none" disabled={busy} onclick={apply}>
                  {busy ? "Écriture…" : "Appliquer vers Tillin"}
                </Button>
              </div>
            </div>
          {/if}
        {/if}
      </main>
    </div>
  {/snippet}
</RequireAuth>
