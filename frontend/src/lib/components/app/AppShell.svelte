<script lang="ts">
  import type { Component, Snippet } from "svelte"
  import ChartColumn from "@lucide/svelte/icons/chart-column"
  import ChevronRight from "@lucide/svelte/icons/chevron-right"
  import FileUp from "@lucide/svelte/icons/file-up"
  import LayoutDashboard from "@lucide/svelte/icons/layout-dashboard"
  import ListChecks from "@lucide/svelte/icons/list-checks"
  import LogOut from "@lucide/svelte/icons/log-out"
  import Menu from "@lucide/svelte/icons/menu"
  import Package from "@lucide/svelte/icons/package"
  import Settings from "@lucide/svelte/icons/settings"
  import SlidersHorizontal from "@lucide/svelte/icons/sliders-horizontal"
  import WandSparkles from "@lucide/svelte/icons/wand-sparkles"
  import X from "@lucide/svelte/icons/x"
  import { listen, navigate } from "svelte5-router"

  import { authLogout } from "@/client"
  import type { UserPublic } from "@/client"
  import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
  } from "@/lib/components/ui/dropdown-menu"

  import ThemePicker from "./ThemePicker.svelte"

  type Breadcrumb = { label: string; href?: string }

  let {
    appName,
    user,
    breadcrumbs = [],
    children,
  }: {
    appName: string
    user: UserPublic
    breadcrumbs?: Breadcrumb[]
    children: Snippet
  } = $props()

  // Route active : les pages remontent le shell à chaque navigation, mais on
  // écoute quand même l'historique pour rester correct en cas de navigation
  // interne sans remount.
  let pathname = $state(window.location.pathname)
  $effect(() =>
    listen(({ location }) => {
      pathname = location.pathname
    }),
  )

  type NavItem = {
    label: string
    href: string
    icon: Component
    isActive: (path: string) => boolean
  }

  // Navigation en deux sections : le flux quotidien (Pipeline) et les
  // réglages durables (Configuration). Les routes ne changent pas.
  const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
    {
      title: "Pipeline",
      items: [
        {
          label: "Tableau de bord",
          href: "/",
          icon: LayoutDashboard,
          isActive: (path) => path === "/",
        },
        {
          label: "Imports",
          href: "/imports",
          icon: FileUp,
          isActive: (path) => path.startsWith("/imports"),
        },
        {
          label: "Produits",
          href: "/products",
          icon: Package,
          isActive: (path) => path.startsWith("/products"),
        },
        {
          label: "Enrichissements",
          href: "/jobs",
          icon: ListChecks,
          // /jobs, /jobs/:id et /items/:id relèvent tous des enrichissements.
          isActive: (path) => path.startsWith("/jobs") || path.startsWith("/items"),
        },
      ],
    },
    {
      title: "Configuration",
      items: [
        {
          label: "Profils d'import",
          href: "/profiles",
          icon: SlidersHorizontal,
          isActive: (path) => path.startsWith("/profiles"),
        },
        {
          label: "Réglages d'enrichissement",
          href: "/enrichment",
          icon: WandSparkles,
          isActive: (path) => path.startsWith("/enrichment"),
        },
        {
          label: "Consommation",
          href: "/usage",
          icon: ChartColumn,
          isActive: (path) => path.startsWith("/usage"),
        },
      ],
    },
  ]

  // Paramètres : section séparée en bas de la sidebar, au-dessus du bloc user.
  const settingsActive = $derived(pathname.startsWith("/settings"))

  let drawerOpen = $state(false)

  // Initiales : deux premières lettres de la partie locale de l'email.
  const initials = $derived(user.email.split("@")[0].slice(0, 2).toUpperCase())

  function go(href: string) {
    drawerOpen = false
    navigate(href)
  }

  async function onLogout() {
    await authLogout()
    navigate("/login")
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape" && drawerOpen) drawerOpen = false
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#snippet sidebarContent()}
  <button
    type="button"
    class="font-title text-foreground border-border flex h-14 shrink-0 cursor-pointer items-center border-b px-4 text-base font-bold"
    onclick={() => go("/")}
  >
    {appName}
  </button>

  <nav class="flex flex-1 flex-col gap-3 overflow-y-auto p-2" aria-label="Navigation principale">
    {#each NAV_GROUPS as group (group.title)}
      <div class="flex flex-col gap-1">
        <p class="text-muted-foreground px-2.5 pt-1 text-[10px] font-medium tracking-wider uppercase">
          {group.title}
        </p>
        {#each group.items as item (item.href)}
          {@const active = item.isActive(pathname)}
          <button
            type="button"
            class="flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors {active
              ? 'bg-accent text-accent-foreground font-medium'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'}"
            aria-current={active ? "page" : undefined}
            onclick={() => go(item.href)}
          >
            <item.icon size={16} class="shrink-0" />
            {item.label}
          </button>
        {/each}
      </div>
    {/each}
  </nav>

  <div class="border-border border-t p-2">
    <button
      type="button"
      class="flex h-9 w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors {settingsActive
        ? 'bg-accent text-accent-foreground font-medium'
        : 'text-muted-foreground hover:bg-muted hover:text-foreground'}"
      aria-current={settingsActive ? "page" : undefined}
      onclick={() => go("/settings")}
    >
      <Settings size={16} class="shrink-0" />
      Paramètres
    </button>
  </div>

  <div class="border-border flex items-center justify-between gap-2 border-t p-3">
    <div class="flex min-w-0 items-center gap-2">
      <span
        class="bg-primary text-primary-foreground flex size-7 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold"
        aria-hidden="true"
      >
        {initials}
      </span>
      <span class="text-muted-foreground truncate text-xs">{user.email}</span>
    </div>
    <ThemePicker />
  </div>
{/snippet}

<div class="bg-background flex min-h-dvh">
  <!-- Sidebar desktop -->
  <aside
    class="border-border bg-card sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r sm:flex"
  >
    {@render sidebarContent()}
  </aside>

  <!-- Drawer mobile -->
  {#if drawerOpen}
    <div class="fixed inset-0 z-50 sm:hidden">
      <button
        type="button"
        class="absolute inset-0 bg-black/50"
        aria-label="Fermer le menu"
        onclick={() => (drawerOpen = false)}
      ></button>
      <aside class="border-border bg-card absolute inset-y-0 left-0 flex w-60 flex-col border-r">
        {@render sidebarContent()}
        <button
          type="button"
          class="text-muted-foreground hover:text-foreground absolute top-4 right-3"
          aria-label="Fermer le menu"
          onclick={() => (drawerOpen = false)}
        >
          <X size={18} />
        </button>
      </aside>
    </div>
  {/if}

  <div class="flex min-w-0 flex-1 flex-col">
    <!-- Topbar -->
    <header
      class="border-border bg-card sticky top-0 z-10 flex h-14 shrink-0 items-center justify-between gap-2 border-b px-4"
    >
      <div class="flex min-w-0 items-center gap-2">
        <button
          type="button"
          class="text-muted-foreground hover:text-foreground -ml-1 p-1 sm:hidden"
          aria-label="Ouvrir le menu"
          aria-expanded={drawerOpen}
          onclick={() => (drawerOpen = true)}
        >
          <Menu size={20} />
        </button>

        {#if breadcrumbs.length > 0}
          <nav aria-label="Fil d'Ariane" class="min-w-0">
            <ol class="flex items-center gap-1 text-sm">
              {#each breadcrumbs as crumb, index (index)}
                {#if index > 0}
                  <li aria-hidden="true" class="text-muted-foreground flex items-center">
                    <ChevronRight size={14} />
                  </li>
                {/if}
                <li class="min-w-0">
                  {#if crumb.href}
                    <button
                      type="button"
                      class="text-muted-foreground hover:text-foreground cursor-pointer truncate transition-colors"
                      onclick={() => go(crumb.href ?? "/")}
                    >
                      {crumb.label}
                    </button>
                  {:else}
                    <span class="text-foreground truncate font-medium" aria-current="page">
                      {crumb.label}
                    </span>
                  {/if}
                </li>
              {/each}
            </ol>
          </nav>
        {/if}
      </div>

      <!-- Menu utilisateur -->
      <DropdownMenu>
        <DropdownMenuTrigger
          class="bg-primary text-primary-foreground focus-visible:ring-ring/50 flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full text-xs font-semibold outline-none focus-visible:ring-2"
          aria-label="Menu utilisateur"
        >
          {initials}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuLabel class="text-muted-foreground max-w-60 truncate text-xs font-normal">
            {user.email}
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onclick={onLogout}>
            <LogOut size={16} />
            Déconnexion
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>

    <main class="flex-1">
      {@render children()}
    </main>
  </div>
</div>
