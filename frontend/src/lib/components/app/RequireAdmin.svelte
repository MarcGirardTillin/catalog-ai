<script lang="ts">
  // Garde des pages /admin : authentifié ET opérateur (is_admin). Non
  // connecté → /login ; connecté non-admin → accueil. Le backend re-vérifie
  // de toute façon (403 admin_required).
  import type { Snippet } from "svelte"
  import { navigate } from "svelte5-router"

  import { authReadCurrentUser } from "@/client"
  import type { UserPublic } from "@/client"
  import { loadPreferences } from "@/lib/preferences.svelte"
  import { Skeleton } from "@/lib/components/ui/skeleton"

  let { children }: { children: Snippet<[UserPublic]> } = $props()

  let user = $state<UserPublic | null>(null)
  let checking = $state(true)

  $effect(() => {
    authReadCurrentUser().then(({ data, error }) => {
      checking = false
      if (error || !data) {
        navigate("/login")
        return
      }
      if (!data.is_admin) {
        navigate("/", { replace: true })
        return
      }
      user = data
      loadPreferences()
    })
  })
</script>

{#if checking}
  <div class="flex min-h-dvh flex-col gap-3 p-4">
    <Skeleton class="h-8 w-40" />
    <Skeleton class="h-32 w-full" />
  </div>
{:else if user}
  {@render children(user)}
{/if}
