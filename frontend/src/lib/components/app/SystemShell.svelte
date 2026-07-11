<script lang="ts">
  // Mise en page commune des pages système (404, maintenance, erreur) :
  // logo + carte centrée, même direction artistique que /login (halo primary).
  import type { Snippet } from "svelte"

  let { appName, children }: { appName: string; children: Snippet } = $props()
</script>

<main
  class="bg-background relative flex min-h-dvh items-center justify-center overflow-hidden p-4"
>
  <div
    class="bg-primary/10 pointer-events-none absolute -top-32 left-1/2 size-120 -translate-x-1/2 rounded-full blur-3xl"
    aria-hidden="true"
  ></div>

  <div class="relative flex w-full max-w-sm flex-col items-center gap-6">
    <div class="flex flex-col items-center gap-1">
      <span class="font-title text-foreground text-2xl font-bold">{appName}</span>
      <span class="text-primary text-xs font-semibold tracking-[0.24em] uppercase">
        Enrichissement de catalogue
      </span>
    </div>

    {@render children()}
  </div>
</main>
