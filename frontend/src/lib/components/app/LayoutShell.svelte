<script lang="ts">
  import { Separator } from "@/lib/components/ui/separator"

  import ThemePicker from "./ThemePicker.svelte"

  export let appName: string
</script>

<div class="flex min-h-screen flex-col">
  <header class="bg-card">
    <div class="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-4 py-4">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">{appName}</p>
      </div>
      <div class="flex items-center gap-3">
        <ThemePicker />
        <slot name="header" />
      </div>
    </div>
  </header>
  <Separator />

  <main class="mx-auto flex w-full max-w-5xl flex-1 items-center justify-center px-4 py-8">
    <slot />
  </main>

  <Separator />
  <footer class="bg-card px-4 py-3 text-center">
    <slot name="footer" />
  </footer>
</div>
