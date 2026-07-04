<script lang="ts">
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"

  import { frontendEnv } from "../lib/env"

  export let appName: string
</script>

<main class="mx-auto flex min-h-screen w-full max-w-5xl items-center justify-center px-4 py-8">
  <Card class="w-full max-w-xl text-center">
    <CardHeader>
      <CardTitle class="text-3xl font-semibold tracking-tight">{appName} is under maintenance</CardTitle>
      <CardDescription>Access is temporarily disabled while a maintenance operation is running.</CardDescription>
    </CardHeader>
    {#if frontendEnv.environment()}
      <CardContent>
        <p class="text-sm text-muted-foreground">Environment: {frontendEnv.environment()}</p>
      </CardContent>
    {/if}
  </Card>
</main>
