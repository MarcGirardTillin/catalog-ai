<script lang="ts">
  import type { Component, Snippet } from "svelte"
  import ChartColumn from "@lucide/svelte/icons/chart-column"
  import ChevronRight from "@lucide/svelte/icons/chevron-right"
  import Coins from "@lucide/svelte/icons/coins"
  import FileUp from "@lucide/svelte/icons/file-up"
  import LayoutDashboard from "@lucide/svelte/icons/layout-dashboard"
  import ListChecks from "@lucide/svelte/icons/list-checks"
  import LogOut from "@lucide/svelte/icons/log-out"
  import Menu from "@lucide/svelte/icons/menu"
  import Package from "@lucide/svelte/icons/package"
  import Settings from "@lucide/svelte/icons/settings"
  import ShieldCheck from "@lucide/svelte/icons/shield-check"
  import SlidersHorizontal from "@lucide/svelte/icons/sliders-horizontal"
  import X from "@lucide/svelte/icons/x"
  import { createQuery } from "@tanstack/svelte-query"
  import { listen, navigate } from "svelte5-router"

  import { authLogout, statsDashboardStats } from "@/client"
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
  import Wordmark from "./Wordmark.svelte"

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

  type NavChild = {
    label: string
    href: string
    isActive: (path: string) => boolean
  }

  type NavItem = {
    label: string
    href: string
    icon: Component
    isActive: (path: string) => boolean
    /** Module requis (clé DashboardStats) : entrée masquée s'il est coupé. */
    feature?: "feature_import" | "feature_enrich" | "feature_studio"
    /** Sous-menu façon Shopify : cliquer le parent ouvre sa liste, les
     *  autres facettes s'affichent en dessous quand la section est active. */
    children?: NavChild[]
  }

  // Navigation façon Shopify (demande Marc 2026-07-29) : chaque section du
  // pipeline porte ses facettes de configuration en sous-menu (visible quand
  // la section est active) ; les réglages transverses ont leur entrée.
  const BASE_NAV_GROUPS: { title: string; items: NavItem[] }[] = [
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
          feature: "feature_import",
          children: [
            {
              label: "Profils d'import",
              href: "/profiles",
              isActive: (path) => path.startsWith("/profiles"),
            },
          ],
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
          feature: "feature_enrich",
          children: [
            {
              label: "Réglages d'enrichissement",
              href: "/enrichment",
              isActive: (path) => path.startsWith("/enrichment"),
            },
          ],
        },
      ],
    },
    {
      title: "Configuration",
      items: [
        {
          label: "Consommation",
          href: "/usage",
          icon: ChartColumn,
          isActive: (path) => path.startsWith("/usage"),
        },
        {
          label: "Réglages",
          href: "/boutique",
          icon: SlidersHorizontal,
          isActive: (path) => path.startsWith("/boutique"),
        },
      ],
    },
  ]

  /** Sous-menu ouvert : la section (parent ou une facette) est active. */
  function navOpen(item: NavItem, path: string): boolean {
    if (!item.children?.length) return false
    return item.isActive(path) || item.children.some((c) => c.isActive(path))
  }

  // --- Pastilles d'état + modules : polling léger des compteurs du
  // dashboard ; le cache est partagé avec la page d'accueil (même queryKey).
  const statsQuery = createQuery(() => ({
    queryKey: ["stats", "dashboard"],
    queryFn: async () => {
      const { data, error } = await statsDashboardStats()
      if (error || !data) throw new Error("stats_load_failed")
      return data
    },
    refetchInterval: 30_000,
  }))

  // Modules souscrits par le compte (DashboardStats) : les entrées d'un
  // module coupé disparaissent de la nav. Tant que les stats ne sont pas
  // chargées on affiche tout (mieux qu'un flash de menu amputé) — le backend
  // refuse de toute façon en 403. L'admin voit toujours tout.
  const visibleBaseGroups = $derived.by(() => {
    const stats = statsQuery.data
    if (user.is_admin || !stats) return BASE_NAV_GROUPS
    return BASE_NAV_GROUPS.map((group) => ({
      ...group,
      items: group.items.filter(
        (item) => item.feature === undefined || stats[item.feature] !== false,
      ),
    })).filter((group) => group.items.length > 0)
  })

  // Groupe Admin (console opérateur), visible seulement pour l'admin.
  const NAV_GROUPS = $derived<{ title: string; items: NavItem[] }[]>(
    user.is_admin
      ? [
          ...visibleBaseGroups,
          {
            title: "Admin",
            items: [
              {
                label: "Clients",
                href: "/admin",
                icon: ShieldCheck,
                isActive: (path: string) =>
                  path.startsWith("/admin") &&
                  !path.startsWith("/admin/pricing") &&
                  !path.startsWith("/admin/billing"),
              },
              {
                label: "Tarification",
                href: "/admin/billing",
                icon: Coins,
                isActive: (path: string) => path.startsWith("/admin/billing"),
              },
              {
                label: "Coûts",
                href: "/admin/pricing",
                icon: ChartColumn,
                isActive: (path: string) => path.startsWith("/admin/pricing"),
              },
            ],
          },
        ]
      : visibleBaseGroups,
  )

  // count = nombre affiché DANS la pastille (null = simple point, ex. « en
  // cours » ou solde bas — un chiffre n'y apporterait rien).
  type NavDot = { tone: string; title: string; count: number | null }

  // Une seule pastille par menu, la plus urgente : échec > à vérifier > en cours.
  function navDot(failed: number, review: number, running: number): NavDot | null {
    if (failed > 0)
      return { tone: "bg-destructive", title: `${failed} en échec`, count: failed }
    if (review > 0)
      return { tone: "bg-amber-500", title: `${review} à vérifier`, count: review }
    if (running > 0)
      return {
        tone: "bg-primary animate-pulse",
        title: `${running} en cours`,
        count: null,
      }
    return null
  }

  // Pastille de solde de crédits sur « Consommation » : rouge à 0 (bloquant),
  // ambre sous le seuil configuré pour le compte.
  function creditDot(balance: number, threshold: number): NavDot | null {
    if (balance <= 0)
      return { tone: "bg-destructive", title: "Crédits épuisés", count: null }
    if (balance < threshold)
      return {
        tone: "bg-amber-500",
        title: `Solde bas : ${balance} crédits`,
        count: null,
      }
    return null
  }

  const navDots = $derived.by((): Record<string, NavDot | null> => {
    const s = statsQuery.data
    if (!s) return {}
    return {
      // Compte les DOSSIERS (imports/tâches) à vérifier, pas les produits
      // qu'ils contiennent (préférence Marc 2026-07-28).
      "/imports": navDot(
        s.import_failed_items ?? 0,
        s.imports_to_review ?? 0,
        s.imports_processing ?? 0,
      ),
      "/jobs": navDot(
        s.enrich_failed_items ?? 0,
        s.enrich_jobs_to_review ?? 0,
        s.running_jobs ?? 0,
      ),
      "/usage": creditDot(s.credit_balance ?? 0, s.low_credit_threshold ?? 0),
    }
  })

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
    class="border-border flex h-14 shrink-0 cursor-pointer items-center border-b px-4"
    aria-label="Aller au tableau de bord"
    onclick={() => go("/")}
  >
    <Wordmark />
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
            {#if navDots[item.href]}
              {@const dot = navDots[item.href]}
              {#if dot?.count != null}
                <!-- Pastille chiffrée : nb d'éléments à vérifier / en échec. -->
                <span
                  class="ml-auto flex h-4 min-w-4 shrink-0 items-center justify-center rounded-full px-1 text-[10px] font-semibold text-white tabular-nums {dot.tone}"
                  title={dot.title}
                  role="status"
                  aria-label={dot.title}
                >
                  {dot.count > 99 ? "99+" : dot.count}
                </span>
              {:else}
                <span
                  class="ml-auto size-2 shrink-0 rounded-full {dot?.tone}"
                  title={dot?.title}
                  role="status"
                  aria-label={dot?.title}
                ></span>
              {/if}
            {/if}
          </button>
          {#if navOpen(item, pathname)}
            <!-- Facettes de la section active (sous-menu façon Shopify). -->
            {#each item.children ?? [] as child (child.href)}
              {@const childActive = child.isActive(pathname)}
              <button
                type="button"
                class="flex h-8 cursor-pointer items-center rounded-md py-1 pr-2.5 pl-9 text-sm transition-colors {childActive
                  ? 'bg-accent text-accent-foreground font-medium'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'}"
                aria-current={childActive ? "page" : undefined}
                onclick={() => go(child.href)}
              >
                {child.label}
              </button>
            {/each}
          {/if}
        {/each}
      </div>
    {/each}
  </nav>

  <!-- Bloc compte : avatar + email = menu (Paramètres, Déconnexion). Un seul
       point d'entrée profil, en bas de la sidebar — l'avatar en topbar était
       un doublon. -->
  <div class="border-border flex items-center justify-between gap-2 border-t p-3">
    <DropdownMenu>
      <DropdownMenuTrigger
        class="hover:bg-muted focus-visible:ring-ring/50 -m-1.5 flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-md p-1.5 outline-none focus-visible:ring-2"
        aria-label="Menu du compte"
      >
        <span
          class="bg-primary text-primary-foreground flex size-7 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold"
          aria-hidden="true"
        >
          {initials}
        </span>
        <span class="text-muted-foreground truncate text-xs">{user.email}</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start">
        <DropdownMenuLabel class="text-muted-foreground max-w-60 truncate text-xs font-normal">
          {user.email}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onclick={() => go("/settings")}>
          <Settings size={16} />
          Paramètres
        </DropdownMenuItem>
        <DropdownMenuItem onclick={onLogout}>
          <LogOut size={16} />
          Déconnexion
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
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

    </header>

    <main class="flex-1">
      {@render children()}
    </main>
  </div>
</div>
