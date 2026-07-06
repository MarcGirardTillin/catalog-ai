<script lang="ts">
  import { navigate } from "svelte5-router"

  import { authLogout } from "@/client"
  import type { UserPublic } from "@/client"
  import { Button } from "@/lib/components/ui/button"

  let { appName, user }: { appName: string; user: UserPublic } = $props()

  async function onLogout() {
    await authLogout()
    navigate("/login")
  }
</script>

<!-- Sticky app header, works from 320px wide up. -->
<header class="border-border bg-card sticky top-0 z-10 border-b">
  <div class="mx-auto flex max-w-2xl items-center justify-between gap-2 px-4 py-3">
    <div class="flex items-center gap-3">
      <button
        type="button"
        class="font-title text-foreground cursor-pointer text-base font-bold"
        onclick={() => navigate("/jobs")}
      >
        {appName}
      </button>
      <nav class="flex items-center gap-1">
        <Button variant="ghost" size="sm" onclick={() => navigate("/jobs")}>Jobs</Button>
        <Button variant="ghost" size="sm" onclick={() => navigate("/jobs/new")}>Nouveau</Button>
      </nav>
    </div>
    <div class="flex items-center gap-2">
      <span class="text-muted-foreground hidden text-xs sm:inline">{user.email}</span>
      <Button variant="ghost" size="sm" onclick={onLogout}>Déconnexion</Button>
    </div>
  </div>
</header>
