<script lang="ts">
  import { toast } from "svelte-sonner"
  import { navigate } from "svelte5-router"

  import { jobsCreateEnrichmentJob } from "@/client"
  import type { JobPublic } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"

  let { appName }: { appName: string } = $props()

  let mode: "ids" | "tag" = $state("ids")
  let idsRaw = $state("")
  let tag = $state("")
  let translate = $state(false)
  let submitting = $state(false)
  let errorMessage = $state<string | null>(null)
  let createdJob = $state<JobPublic | null>(null)

  function parseIds(raw: string): number[] {
    return [...new Set(
      raw
        .split(/[\s,;]+/)
        .map((part) => Number.parseInt(part, 10))
        .filter((n) => Number.isFinite(n) && n > 0),
    )]
  }

  const parsedIds = $derived(parseIds(idsRaw))

  async function onSubmit(event: SubmitEvent) {
    event.preventDefault()
    errorMessage = null
    if (mode === "ids" && parsedIds.length === 0) {
      errorMessage = "Collez au moins un identifiant produit valide."
      return
    }
    if (mode === "tag" && !tag.trim()) {
      errorMessage = "Indiquez un tag."
      return
    }
    submitting = true
    const { data, error } = await jobsCreateEnrichmentJob({
      body: {
        selection: mode === "ids" ? { ids: parsedIds } : { tag: tag.trim() },
        config: { translate },
      },
    })
    submitting = false
    if (error || !data) {
      toast.error("Création du job impossible. Réessayez.")
      return
    }
    toast.success(`Job #${data.id} créé — traitement lancé`)
    createdJob = data
  }

  function resetForm() {
    createdJob = null
    idsRaw = ""
    tag = ""
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell
      {appName}
      {user}
      breadcrumbs={[{ label: "Jobs", href: "/jobs" }, { label: "Nouveau job" }]}
    >
      <div class="mx-auto max-w-2xl p-4">
        {#if createdJob}
          <Card>
            <CardHeader>
              <CardTitle class="font-title text-lg">Job #{createdJob.id} créé</CardTitle>
              <CardDescription>
                Le traitement démarre côté serveur — vous pouvez fermer cette page.
              </CardDescription>
            </CardHeader>
            <CardContent class="flex flex-col gap-4">
              <dl class="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                <div>
                  <dt class="text-muted-foreground">Statut</dt>
                  <dd class="font-medium">{createdJob.status}</dd>
                </div>
                <div>
                  <dt class="text-muted-foreground">Produits</dt>
                  <dd class="font-medium">{createdJob.counts.total}</dd>
                </div>
                <div>
                  <dt class="text-muted-foreground">En attente</dt>
                  <dd class="font-medium">{createdJob.counts.pending}</dd>
                </div>
                <div>
                  <dt class="text-muted-foreground">Échecs</dt>
                  <dd class="font-medium">{createdJob.counts.failed}</dd>
                </div>
              </dl>
              <div class="flex flex-col gap-2 sm:flex-row">
                <Button
                  class="w-full sm:w-auto"
                  onclick={() => navigate(`/jobs/${createdJob?.id}`)}
                >
                  Suivre le job
                </Button>
                <Button variant="secondary" class="w-full sm:w-auto" onclick={resetForm}>
                  Lancer un autre job
                </Button>
              </div>
            </CardContent>
          </Card>
        {:else}
          <Card>
            <CardHeader>
              <CardTitle class="font-title text-lg">Nouveau job d'enrichissement</CardTitle>
              <CardDescription>
                Sélectionnez les produits Tillin à enrichir, par identifiants ou par tag.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form class="flex flex-col gap-4" onsubmit={onSubmit}>
                <!-- Selection mode toggle: full-width buttons on mobile. -->
                <div class="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Mode de sélection">
                  <Button
                    type="button"
                    variant={mode === "ids" ? "default" : "outline"}
                    aria-pressed={mode === "ids"}
                    onclick={() => (mode = "ids")}
                  >
                    Par identifiants
                  </Button>
                  <Button
                    type="button"
                    variant={mode === "tag" ? "default" : "outline"}
                    aria-pressed={mode === "tag"}
                    onclick={() => (mode = "tag")}
                  >
                    Par tag
                  </Button>
                </div>

                {#if mode === "ids"}
                  <div class="flex flex-col gap-1.5">
                    <Label for="ids">Identifiants produits</Label>
                    <textarea
                      id="ids"
                      rows="5"
                      placeholder="Ex. 101, 102, 103 (séparés par virgules, espaces ou retours à la ligne)"
                      class="border-input bg-background placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 w-full rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
                      bind:value={idsRaw}
                    ></textarea>
                    <p class="text-muted-foreground text-xs">
                      {parsedIds.length} produit{parsedIds.length > 1 ? "s" : ""} détecté{parsedIds.length > 1 ? "s" : ""}
                    </p>
                  </div>
                {:else}
                  <div class="flex flex-col gap-1.5">
                    <Label for="tag">Tag</Label>
                    <Input id="tag" class="h-10 text-sm" placeholder="Ex. ss25" bind:value={tag} />
                    <p class="text-muted-foreground text-xs">
                      Les produits portant ce tag seront résolus côté serveur.
                    </p>
                  </div>
                {/if}

                <label class="flex items-center gap-2 text-sm">
                  <input type="checkbox" bind:checked={translate} class="accent-primary size-4" />
                  Traduire les contenus
                </label>

                {#if errorMessage}
                  <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
                {/if}

                <Button type="submit" size="lg" class="h-10 w-full text-sm" disabled={submitting}>
                  {submitting ? "Création…" : "Lancer le job"}
                </Button>
              </form>
            </CardContent>
          </Card>
        {/if}
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
