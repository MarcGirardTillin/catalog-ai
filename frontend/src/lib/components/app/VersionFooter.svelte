<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query"

  import { fetchBackendVersion } from "@/lib/api"

  const versionQuery = createQuery(() => ({
    queryFn: fetchBackendVersion,
    queryKey: ["system", "version"] as const,
    staleTime: 60_000,
  }))
</script>

<p class="text-sm text-muted-foreground">
  {#if versionQuery.data}
    Backend {versionQuery.data.app} {versionQuery.data.version} ({versionQuery.data.environment})
  {:else}
    Backend version unavailable
  {/if}
</p>
