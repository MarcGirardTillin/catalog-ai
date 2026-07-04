<script lang="ts">
  import {
    Card,
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
      <CardTitle class="text-3xl font-semibold tracking-tight">{appName}</CardTitle>
      <CardDescription class="font-semibold uppercase tracking-[0.24em] text-primary">Application shell</CardDescription>
    </CardHeader>
  </Card>

  <svelte:fragment slot="footer">
    <p>{appName} - {new Date().getFullYear()}</p>
    <VersionFooter />
  </svelte:fragment>
</LayoutShell>
