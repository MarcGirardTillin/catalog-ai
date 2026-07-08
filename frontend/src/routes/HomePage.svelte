<script lang="ts">
  import ListChecks from "@lucide/svelte/icons/list-checks"
  import Plus from "@lucide/svelte/icons/plus"
  import Search from "@lucide/svelte/icons/search"
  import { navigate } from "svelte5-router"

  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import AppShell from "@/lib/components/app/AppShell.svelte"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"

  let { appName }: { appName: string } = $props()

  const SHORTCUTS = [
    {
      title: "Rechercher des produits",
      description: "Parcourir le catalogue Tillin et sélectionner les produits à enrichir.",
      href: "/products",
      icon: Search,
    },
    {
      title: "Créer un job",
      description: "Lancer un enrichissement par identifiants ou par tag.",
      href: "/jobs/new",
      icon: Plus,
    },
    {
      title: "Voir les jobs",
      description: "Suivre les enrichissements en cours et valider les résultats.",
      href: "/jobs",
      icon: ListChecks,
    },
  ]
</script>

<RequireAuth>
  {#snippet children(user)}
    <AppShell {appName} {user} breadcrumbs={[{ label: "Tableau de bord" }]}>
      <div class="mx-auto flex max-w-4xl flex-col gap-4 p-4">
        <h1 class="font-title text-lg font-bold">Tableau de bord</h1>

        <div class="grid gap-3 sm:grid-cols-3">
          {#each SHORTCUTS as shortcut (shortcut.href)}
            <button
              type="button"
              class="cursor-pointer text-left"
              onclick={() => navigate(shortcut.href)}
            >
              <Card class="hover:ring-primary/40 h-full transition-shadow">
                <CardHeader>
                  <shortcut.icon size={18} class="text-primary" />
                  <CardTitle class="font-title text-sm">{shortcut.title}</CardTitle>
                  <CardDescription class="text-xs">{shortcut.description}</CardDescription>
                </CardHeader>
              </Card>
            </button>
          {/each}
        </div>

        <Card size="sm">
          <CardContent class="text-muted-foreground py-4 text-center text-xs">
            Les indicateurs (KPIs) arriveront ici dans une prochaine version.
          </CardContent>
        </Card>
      </div>
    </AppShell>
  {/snippet}
</RequireAuth>
