<script lang="ts">
  import { navigate } from "svelte5-router"

  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import SystemShell from "@/lib/components/app/SystemShell.svelte"

  let { appName }: { appName: string } = $props()
</script>

<SystemShell {appName}>
  <Card class="w-full text-center shadow-sm">
    <CardHeader>
      <CardTitle class="font-title text-3xl font-bold">404</CardTitle>
      <CardDescription>Cette page n'existe pas (ou plus).</CardDescription>
    </CardHeader>
    <CardContent class="flex justify-center">
      <Button variant="outline" onclick={() => navigate("/", { replace: true })}>
        Retour à l'accueil
      </Button>
    </CardContent>
  </Card>
</SystemShell>
