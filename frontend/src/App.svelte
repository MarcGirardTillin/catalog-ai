<script lang="ts">
  import { mode, ModeWatcher } from "mode-watcher"
  import { Toaster } from "svelte-sonner"
  import {
    QueryClient,
    QueryClientProvider,
  } from "@tanstack/svelte-query"
  import { Route, Router } from "svelte5-router"

  import { frontendEnv } from "./lib/env"
  import AppErrorFallback from "@/lib/components/app/AppErrorFallback.svelte"
  import HomePage from "./routes/HomePage.svelte"
  import ImportDetailPage from "./routes/ImportDetailPage.svelte"
  import ImportNewPage from "./routes/ImportNewPage.svelte"
  import ImportsListPage from "./routes/ImportsListPage.svelte"
  import ItemReviewPage from "./routes/ItemReviewPage.svelte"
  import JobDetailPage from "./routes/JobDetailPage.svelte"
  import JobNewPage from "./routes/JobNewPage.svelte"
  import JobsListPage from "./routes/JobsListPage.svelte"
  import LoginPage from "./routes/LoginPage.svelte"
  import MaintenancePage from "./routes/MaintenancePage.svelte"
  import NotFoundPage from "./routes/NotFoundPage.svelte"
  import ProductSearchPage from "./routes/ProductSearchPage.svelte"
  import ProfilesPage from "./routes/ProfilesPage.svelte"
  import SettingsPage from "./routes/SettingsPage.svelte"

  const appName = frontendEnv.appName() || "Techlab starter"
  const maintenanceEnabled = frontendEnv.maintenanceEnabled()
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
      },
    },
  })
</script>

<ModeWatcher />
<Toaster richColors position="top-right" theme={mode.current ?? "system"} />

<QueryClientProvider client={queryClient}>
  <svelte:boundary>
    {#if maintenanceEnabled}
      <MaintenancePage {appName} />
    {:else}
      <Router>
        <Route path="/" component={HomePage} {appName} />
        <Route path="/login" component={LoginPage} {appName} />
        <Route path="/products" component={ProductSearchPage} {appName} />
        <Route path="/jobs/new" component={JobNewPage} {appName} />
        <Route path="/jobs/:id">
          {#snippet children(params)}
            <JobDetailPage {appName} id={params.id} />
          {/snippet}
        </Route>
        <Route path="/jobs" component={JobsListPage} {appName} />
        <Route path="/imports/new" component={ImportNewPage} {appName} />
        <Route path="/imports/:id">
          {#snippet children(params)}
            <ImportDetailPage {appName} id={params.id} />
          {/snippet}
        </Route>
        <Route path="/imports" component={ImportsListPage} {appName} />
        <Route path="/profiles" component={ProfilesPage} {appName} />
        <Route path="/settings" component={SettingsPage} {appName} />
        <Route path="/items/:id">
          {#snippet children(params)}
            <ItemReviewPage {appName} id={params.id} />
          {/snippet}
        </Route>
        <Route path="*" component={NotFoundPage} {appName} />
      </Router>
    {/if}
    {#snippet failed(error, reset)}
      <AppErrorFallback
        message={error instanceof Error ? error.message : "Something went wrong. Please try again."}
        onReset={reset}
      />
    {/snippet}
  </svelte:boundary>
</QueryClientProvider>
