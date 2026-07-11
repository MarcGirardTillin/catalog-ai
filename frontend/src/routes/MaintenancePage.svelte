<script lang="ts">
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import SystemShell from "@/lib/components/app/SystemShell.svelte"

  import { frontendEnv } from "../lib/env"

  let { appName }: { appName: string } = $props()
</script>

<SystemShell {appName}>
  <Card class="w-full text-center shadow-sm">
    <CardHeader>
      <CardTitle class="font-title text-lg font-bold">Maintenance en cours</CardTitle>
      <CardDescription>
        L'accès est temporairement suspendu le temps d'une opération de
        maintenance. Revenez dans quelques minutes.
      </CardDescription>
    </CardHeader>
    {#if frontendEnv.environment()}
      <CardContent>
        <p class="text-muted-foreground text-sm">
          Environnement : {frontendEnv.environment()}
        </p>
      </CardContent>
    {/if}
  </Card>
</SystemShell>
