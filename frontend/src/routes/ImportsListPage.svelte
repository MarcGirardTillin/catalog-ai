<script lang="ts">
  import FileUp from "@lucide/svelte/icons/file-up"
  import { createQuery } from "@tanstack/svelte-query"
  import { navigate } from "svelte5-router"

  import { listImports, type ImportJobPublic } from "@/lib/api/imports"
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

  // TanStack Query : cache partagé (retour liste ↔ détail instantané).
  const importsQuery = createQuery(() => ({
    queryKey: ["imports", "list"],
    queryFn: async () => {
      const { data, error } = await listImports({ page_size: 50 })
      if (error || !data) throw new Error("imports_load_failed")
      return data
    },
  }))
  const imports = $derived(importsQuery.data?.items ?? null)
  const errorMessage = $derived(
    importsQuery.isError ? "Impossible de charger les imports." : null,
  )

  // Suivi produits : où en sont les produits extraits de l'import.
  type Chip = { label: string; count: number; tone: string }
  function statusChips(job: ImportJobPublic): Chip[] {
    const c = job.counts
    const defs: Chip[] = [
      {
        label: "transférés",
        count: c.applied ?? 0,
        tone: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
      },
      {
        label: "à transférer",
        count: c.ready_for_review ?? 0,
        tone: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
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

  function openImport(id: number) {
    navigate(`/imports/${id}`)
  }

  function onRowKeydown(event: KeyboardEvent, id: number) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      openImport(id)
    }
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Imports" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
        <div class="flex items-center justify-between gap-2">
          <h1 class="font-title text-lg font-bold">Imports fournisseurs</h1>
          <Button size="sm" onclick={() => navigate("/imports/new")}>Importer un fichier</Button>
        </div>

        {#if errorMessage}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
        {:else if imports === null}
          <Skeleton class="h-10 w-full" />
          <Skeleton class="h-10 w-full" />
          <Skeleton class="h-10 w-full" />
        {:else if imports.length === 0}
          <Card>
            <CardContent class="flex flex-col items-center gap-3 py-10 text-center">
              <span
                class="bg-muted text-muted-foreground flex size-10 items-center justify-center rounded-full"
                aria-hidden="true"
              >
                <FileUp size={18} />
              </span>
              <div class="flex flex-col gap-1">
                <p class="text-sm font-medium">Aucun import pour l'instant</p>
                <p class="text-muted-foreground max-w-md text-sm">
                  Déposez un bon de commande fournisseur (PDF, Excel ou CSV) : l'IA en
                  extrait les produits — références, coloris, tailles, EAN, prix — prêts
                  à créer dans Tillin après votre relecture.
                </p>
              </div>
              <Button onclick={() => navigate("/imports/new")}>Importer un fichier</Button>
            </CardContent>
          </Card>
        {:else}
          <Card class="py-0">
            <CardContent class="overflow-x-auto px-0">
              <table class="w-full min-w-xl text-sm">
                <thead>
                  <tr class="border-border border-b">
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Fichier</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Statut</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Produits extraits</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-left text-xs font-medium">Suivi produits</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Durée</th>
                    <th class="text-muted-foreground px-4 py-2.5 text-right text-xs font-medium">Créé</th>
                  </tr>
                </thead>
                <tbody>
                  {#each imports as job (job.id)}
                    {@const chips = statusChips(job)}
                    <tr
                      role="link"
                      tabindex="0"
                      aria-label={`Ouvrir l'import ${job.file_name}`}
                      class="border-border hover:bg-muted/50 focus-visible:bg-muted/50 cursor-pointer border-b outline-none transition-colors last:border-b-0"
                      onclick={() => openImport(job.id)}
                      onkeydown={(e) => onRowKeydown(e, job.id)}
                    >
                      <td class="max-w-60 px-4 {cellPad} font-medium" title={job.file_names.join("\n")}>
                        <span class="flex items-center gap-1.5">
                          <span class="truncate">{job.file_name}</span>
                          {#if job.file_names.length > 1}
                            <!-- Lot multi-fichiers : signaler les fichiers croisés. -->
                            <span
                              class="bg-muted text-muted-foreground shrink-0 rounded-full px-1.5 py-0.5 text-[11px]"
                            >
                              +{job.file_names.length - 1}
                            </span>
                          {/if}
                        </span>
                      </td>
                      <td class="px-4 {cellPad}"><StatusBadge status={job.status} /></td>
                      <td class="px-4 {cellPad} text-right whitespace-nowrap tabular-nums">
                        {job.counts.total}
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
