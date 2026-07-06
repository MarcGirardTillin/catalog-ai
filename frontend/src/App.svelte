<script lang="ts">
  import { ModeWatcher } from "mode-watcher"
  import {
    QueryClient,
    QueryClientProvider,
  } from "@tanstack/svelte-query"
  import { Route, Router } from "svelte5-router"

  import { frontendEnv } from "./lib/env"
  import AppErrorFallback from "@/lib/components/app/AppErrorFallback.svelte"
  import HomePage from "./routes/HomePage.svelte"
  import ItemReviewPage from "./routes/ItemReviewPage.svelte"
  import JobDetailPage from "./routes/JobDetailPage.svelte"
  import JobNewPage from "./routes/JobNewPage.svelte"
  import JobsListPage from "./routes/JobsListPage.svelte"
  import LoginPage from "./routes/LoginPage.svelte"
  import MaintenancePage from "./routes/MaintenancePage.svelte"
  import NotFoundPage from "./routes/NotFoundPage.svelte"
  import ProductSearchPage from "./routes/ProductSearchPage.svelte"

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
