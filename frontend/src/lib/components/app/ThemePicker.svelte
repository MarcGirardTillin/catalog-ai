<script lang="ts">
  import Monitor from "@lucide/svelte/icons/monitor"
  import Moon from "@lucide/svelte/icons/moon"
  import Sun from "@lucide/svelte/icons/sun"
  import { mode, resetMode, setMode } from "mode-watcher"

  import { buttonVariants } from "@/lib/components/ui/button"
  import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
  } from "@/lib/components/ui/dropdown-menu"
</script>

<DropdownMenu>
  <DropdownMenuTrigger
    class={buttonVariants({ variant: "outline", size: "icon" })}
    aria-label="Toggle theme"
  >
    {#if mode.current === "dark"}
      <Moon size={16} />
    {:else}
      <Sun size={16} />
    {/if}
  </DropdownMenuTrigger>
  <DropdownMenuContent align="end">
    <DropdownMenuItem onclick={() => setMode("light")}>
      <Sun size={16} />
      Light
    </DropdownMenuItem>
    <DropdownMenuItem onclick={() => setMode("dark")}>
      <Moon size={16} />
      Dark
    </DropdownMenuItem>
    <DropdownMenuItem onclick={resetMode}>
      <Monitor size={16} />
      System
    </DropdownMenuItem>
  </DropdownMenuContent>
</DropdownMenu>
