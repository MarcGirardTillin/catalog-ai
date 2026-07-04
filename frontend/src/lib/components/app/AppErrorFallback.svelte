<script lang="ts">
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"

  export let message = "Something went wrong. Please try again."
  export let onReset: () => void
</script>

<main class="mx-auto flex min-h-screen w-full max-w-5xl items-center justify-center px-4 py-8">
  <Card class="w-full max-w-xl text-center">
    <CardHeader>
      <CardTitle class="text-3xl font-semibold tracking-tight">Error</CardTitle>
      <CardDescription>{message}</CardDescription>
    </CardHeader>
    <CardContent class="flex justify-center gap-3">
      <Button variant="outline" onclick={onReset}>Retry</Button>
      <Button onclick={() => window.location.replace("/")}>Go home</Button>
    </CardContent>
  </Card>
</main>
