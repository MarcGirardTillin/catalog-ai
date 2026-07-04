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
  import LayoutShell from "@/lib/components/app/LayoutShell.svelte"
  import VersionFooter from "@/lib/components/app/VersionFooter.svelte"

  export let appName: string
</script>

<LayoutShell {appName}>
  <Card class="w-full max-w-xl text-center">
    <CardHeader>
      <CardTitle class="text-3xl font-semibold tracking-tight">404</CardTitle>
      <CardDescription>The page you are looking for was not found.</CardDescription>
    </CardHeader>
    <CardContent class="flex justify-center">
      <Button variant="outline" onclick={() => navigate("/", { replace: true })}>Go back</Button>
    </CardContent>
  </Card>

  <svelte:fragment slot="footer">
    <p>{appName} - {new Date().getFullYear()}</p>
    <VersionFooter />
  </svelte:fragment>
</LayoutShell>
