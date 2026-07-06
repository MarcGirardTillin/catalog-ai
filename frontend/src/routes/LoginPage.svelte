<script lang="ts">
  import Eye from "@lucide/svelte/icons/eye"
  import EyeOff from "@lucide/svelte/icons/eye-off"
  import { navigate } from "svelte5-router"

  import { authLogin } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"

  export let appName: string

  let email = ""
  let password = ""
  let showPassword = false
  let submitting = false
  let errorMessage: string | null = null

  async function onSubmit(event: SubmitEvent) {
    event.preventDefault()
    submitting = true
    errorMessage = null
    const { data, error } = await authLogin({
      body: { email, password },
    })
    submitting = false
    if (error || !data) {
      errorMessage =
        typeof error === "object" && error !== null && "code" in error && error.code === "invalid_credentials"
          ? "Email ou mot de passe incorrect."
          : "Connexion impossible. Réessayez."
      return
    }
    navigate("/jobs/new")
  }
</script>

<!-- Mobile-first: single column, comfortable touch targets, card grows to max-w-sm on larger screens. -->
<main class="bg-background flex min-h-dvh items-center justify-center p-4">
  <Card class="w-full max-w-sm">
    <CardHeader>
      <CardTitle class="font-title text-2xl">{appName}</CardTitle>
      <CardDescription>Connectez-vous pour accéder au catalogue.</CardDescription>
    </CardHeader>
    <CardContent>
      <form class="flex flex-col gap-4" onsubmit={onSubmit}>
        <div class="flex flex-col gap-1.5">
          <Label for="email">Email</Label>
          <Input
            id="email"
            type="email"
            autocomplete="email"
            required
            class="h-10 text-sm"
            bind:value={email}
          />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="password">Mot de passe</Label>
          <div class="relative">
            <!-- Raw input (not the Input component): a dynamic `type` can't sit
                 on an element that also uses `bind:value`. -->
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              autocomplete="current-password"
              required
              class="border-input bg-background placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-10 w-full min-w-0 rounded-md border py-1 pr-10 pl-2.5 text-sm transition-colors outline-none focus-visible:ring-1 disabled:pointer-events-none disabled:opacity-50"
              bind:value={password}
            />
            <button
              type="button"
              class="text-muted-foreground hover:text-foreground absolute inset-y-0 right-0 flex items-center px-2.5"
              aria-label={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}
              aria-pressed={showPassword}
              onclick={() => (showPassword = !showPassword)}
            >
              {#if showPassword}
                <EyeOff class="size-4" />
              {:else}
                <Eye class="size-4" />
              {/if}
            </button>
          </div>
        </div>
        {#if errorMessage}
          <p class="text-destructive text-xs" role="alert">{errorMessage}</p>
        {/if}
        <Button type="submit" size="lg" class="h-10 w-full text-sm" disabled={submitting}>
          {submitting ? "Connexion…" : "Se connecter"}
        </Button>
      </form>
    </CardContent>
  </Card>
</main>
