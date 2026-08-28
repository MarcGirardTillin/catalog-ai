<script lang="ts">
  // Bannière « Catalog a été mis à jour » : compare l'identifiant du build
  // chargé (__BUILD_ID__) à /version.json (servi sans cache), toutes les
  // 5 min et au retour sur l'onglet. Un écart = nouveau déploiement → on
  // propose de recharger (demande Marc 2026-08-28). En dev, /version.json
  // n'existe pas : silencieux.
  import RefreshCw from "@lucide/svelte/icons/refresh-cw"

  const POLL_MS = 5 * 60 * 1000
  let updateAvailable = $state(false)

  async function check() {
    if (updateAvailable) return
    try {
      const response = await fetch("/version.json", { cache: "no-store" })
      if (!response.ok) return
      const data = (await response.json()) as { build?: string }
      if (data.build && data.build !== __BUILD_ID__) updateAvailable = true
    } catch {
      // Réseau/JSON indisponible : on réessaiera au prochain tick.
    }
  }

  $effect(() => {
    void check()
    const timer = setInterval(() => void check(), POLL_MS)
    const onVisible = () => {
      if (document.visibilityState === "visible") void check()
    }
    document.addEventListener("visibilitychange", onVisible)
    return () => {
      clearInterval(timer)
      document.removeEventListener("visibilitychange", onVisible)
    }
  })
</script>

{#if updateAvailable}
  <div
    class="bg-primary text-primary-foreground flex items-center justify-center gap-2 px-4 py-1.5 text-xs"
    role="status"
  >
    <RefreshCw size={13} aria-hidden="true" />
    <span>Catalog a été mis à jour.</span>
    <button
      type="button"
      class="cursor-pointer font-semibold underline underline-offset-2"
      onclick={() => window.location.reload()}
    >
      Recharger la page pour profiter de la dernière version
    </button>
  </div>
{/if}
