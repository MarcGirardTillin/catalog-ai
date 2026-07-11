<script lang="ts">
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import SystemShell from "@/lib/components/app/SystemShell.svelte"

  let {
    appName = "CatalogAI",
    message = "Une erreur inattendue est survenue. Réessayez.",
    onReset,
  }: {
    appName?: string
    message?: string
    onReset: () => void
  } = $props()
</script>

<SystemShell {appName}>
  <Card class="w-full text-center shadow-sm">
    <CardHeader>
      <CardTitle class="font-title text-lg font-bold">
        Une erreur est survenue
      </CardTitle>
      <CardDescription>{message}</CardDescription>
    </CardHeader>
    <CardContent class="flex justify-center gap-3">
      <Button variant="outline" onclick={onReset}>Réessayer</Button>
      <Button onclick={() => window.location.replace("/")}>
        Retour à l'accueil
      </Button>
    </CardContent>
  </Card>
</SystemShell>
