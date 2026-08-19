<script lang="ts">
  // Garde d'affichage d'un module par compte : les pages restent accessibles
  // par URL directe même quand la nav les masque — plutôt que des 403 en
  // cascade, un écran « module non activé ». Purement visuel : les routes
  // serveur restent gardées par require_feature. Cache partagé avec AppShell
  // (même queryKey) ; tant que les flags ne sont pas chargés, on affiche le
  // contenu (convention du repo : `=== false` seulement).
  import type { Snippet } from "svelte"
  import { createQuery } from "@tanstack/svelte-query"
  import { navigate } from "svelte5-router"

  import { statsDashboardStats } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import { Card, CardContent } from "@/lib/components/ui/card"

  let {
    feature,
    message,
    children,
  }: {
    feature: "feature_import" | "feature_enrich" | "feature_studio"
    message: string
    children: Snippet
  } = $props()

  const statsQuery = createQuery(() => ({
    queryKey: ["stats", "dashboard"],
    queryFn: async () => {
      const { data, error } = await statsDashboardStats()
      if (error || !data) throw new Error("stats_load_failed")
      return data
    },
  }))
  const disabled = $derived(statsQuery.data?.[feature] === false)
</script>

{#if disabled}
  <div class="mx-auto flex max-w-4xl flex-col gap-3 p-4">
    <Card>
      <CardContent class="flex flex-col items-start gap-3 py-6">
        <p class="text-sm">{message}</p>
        <Button variant="secondary" onclick={() => navigate("/")}>
          Retour au tableau de bord
        </Button>
      </CardContent>
    </Card>
  </div>
{:else}
  {@render children()}
{/if}
