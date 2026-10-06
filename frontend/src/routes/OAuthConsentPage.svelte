<script lang="ts">
  // Consentement OAuth du serveur MCP : une application (ex. Claude) demande
  // l'accès au compte CatalogAI de l'utilisateur connecté. « Autoriser »
  // émet un code et renvoie vers l'application ; « Refuser » la prévient.
  // La demande expire au bout de 10 minutes.
  import ShieldCheck from "@lucide/svelte/icons/shield-check"

  import { oauthApproveRequest, oauthDenyRequest, oauthReadRequest } from "@/client"
  import type { OAuthRequestPublic } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import RequireAuth from "@/lib/components/app/RequireAuth.svelte"
  import Wordmark from "@/lib/components/app/Wordmark.svelte"

  const requestKey = new URLSearchParams(window.location.search).get("request") ?? ""

  let request = $state<OAuthRequestPublic | null>(null)
  let failed = $state(false)
  let deciding = $state<"approve" | "deny" | null>(null)

  async function load() {
    if (!requestKey) {
      failed = true
      return
    }
    const { data, error } = await oauthReadRequest({ path: { request_key: requestKey } })
    if (error || !data) {
      failed = true
      return
    }
    request = data
  }

  async function decide(choice: "approve" | "deny") {
    if (deciding) return
    deciding = choice
    const call = choice === "approve" ? oauthApproveRequest : oauthDenyRequest
    const { data, error } = await call({ path: { request_key: requestKey } })
    if (error || !data) {
      deciding = null
      failed = true
      return
    }
    // Retour vers l'application cliente (code ou refus).
    window.location.href = data.redirect_url
  }
</script>

<RequireAuth>
  {#snippet children(user)}
    {#await load() then}
      <main class="bg-background flex min-h-dvh items-center justify-center p-4">
        <div class="flex w-full max-w-md flex-col items-center gap-6">
          <Wordmark size="lg" />
          <Card class="w-full">
            {#if failed}
              <CardHeader>
                <CardTitle class="font-title text-base">Demande expirée</CardTitle>
                <CardDescription class="text-muted-foreground text-sm">
                  Cette demande d'autorisation n'est plus valable (elle expire au
                  bout de 10 minutes ou a déjà été traitée). Relancez la connexion
                  depuis l'application.
                </CardDescription>
              </CardHeader>
            {:else if request}
              <CardHeader>
                <CardTitle class="font-title flex items-center gap-2 text-base">
                  <ShieldCheck size={18} class="text-primary" aria-hidden="true" />
                  {request.client_name} souhaite accéder à CatalogAI
                </CardTitle>
                <CardDescription class="text-muted-foreground text-sm">
                  En votre nom ({user.email}{user.account_name
                    ? ` · ${user.account_name}`
                    : ""}), avec vos droits et vos crédits. Retour vers
                  <span class="text-foreground font-medium">{request.redirect_host}</span>.
                </CardDescription>
              </CardHeader>
              <CardContent class="flex flex-col gap-4">
                <ul class="flex flex-col gap-2 text-sm">
                  {#each request.scopes as scope (scope.scope)}
                    <li class="flex gap-2">
                      <span class="bg-primary mt-1.5 size-1.5 shrink-0 rounded-full" aria-hidden="true"></span>
                      <span>{scope.label}</span>
                    </li>
                  {/each}
                </ul>
                <p class="text-muted-foreground text-xs">
                  Vous pourrez retirer l'accès à tout moment depuis l'application
                  cliente. Aucun mot de passe n'est partagé.
                </p>
                <div class="flex justify-end gap-2">
                  <Button
                    variant="outline"
                    disabled={deciding !== null}
                    onclick={() => decide("deny")}
                  >
                    {deciding === "deny" ? "…" : "Refuser"}
                  </Button>
                  <Button disabled={deciding !== null} onclick={() => decide("approve")}>
                    {deciding === "approve" ? "Autorisation…" : "Autoriser"}
                  </Button>
                </div>
              </CardContent>
            {/if}
          </Card>
        </div>
      </main>
    {/await}
  {/snippet}
</RequireAuth>
