<script lang="ts">
  // Accès Claude / Codex (serveur MCP) : jetons d'API personnels. Un jeton
  // agit avec les droits de l'utilisateur (modules, crédits) ; il n'est
  // affiché qu'une fois, à la création. La session Tillin (72 h) reste celle
  // de l'app : reconnectez-vous sur l'app si elle a expiré.
  import Copy from "@lucide/svelte/icons/copy"
  import { toast } from "svelte-sonner"

  import {
    apiTokensCreateToken,
    apiTokensListTokens,
    apiTokensRevokeToken,
  } from "@/client"
  import type { ApiTokenPublic } from "@/client"
  import { Button } from "@/lib/components/ui/button"
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "@/lib/components/ui/card"
  import { ConfirmButton } from "@/lib/components/ui/confirm-button"
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"
  import { Select } from "@/lib/components/ui/select"
  import { frontendEnv } from "@/lib/env"
  import { formatRelativeDate } from "@/lib/format"

  let tokens = $state<ApiTokenPublic[] | null>(null)
  let name = $state("")
  let ttlDays = $state(90)
  let creating = $state(false)
  // Jeton en clair juste créé (jamais relisible ensuite).
  let secret = $state<string | null>(null)

  const apiUrl = (frontendEnv.apiUrl() ?? window.location.origin).replace(/\/+$/, "")
  const mcpUrl = `${apiUrl}/mcp`
  const shownSecret = $derived(secret ?? "VOTRE_JETON")
  const claudeCommand = $derived(
    `claude mcp add --transport http catalogai ${mcpUrl} --header "Authorization: Bearer ${shownSecret}"`,
  )
  const codexConfig = $derived(
    `[mcp_servers.catalogai]\nurl = "${mcpUrl}"\nbearer_token_env_var = "CATALOGAI_TOKEN"\ndefault_tools_approval_mode = "writes"`,
  )

  async function load() {
    const { data } = await apiTokensListTokens()
    tokens = data ?? []
  }

  $effect(() => {
    void load()
  })

  async function create(event: SubmitEvent) {
    event.preventDefault()
    if (!name.trim() || creating) return
    creating = true
    const { data, error } = await apiTokensCreateToken({
      body: { name: name.trim(), ttl_days: ttlDays },
    })
    creating = false
    if (error || !data) {
      toast.error("Création du jeton impossible (10 jetons actifs au plus).")
      return
    }
    secret = data.secret
    name = ""
    await load()
  }

  async function revoke(token: ApiTokenPublic) {
    const { error } = await apiTokensRevokeToken({ path: { token_id: token.id } })
    if (error) {
      toast.error("Révocation impossible.")
      return
    }
    toast.success(`Jeton « ${token.name} » révoqué`)
    await load()
  }

  function formatDay(iso: string): string {
    return new Date(iso).toLocaleDateString("fr-FR", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })
  }

  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(`${label} copié`)
    } catch {
      toast.error("Copie impossible : sélectionnez le texte à la main.")
    }
  }
</script>

<Card size="sm">
  <CardHeader>
    <CardTitle class="font-title text-sm">Claude & Codex (MCP)</CardTitle>
    <CardDescription class="text-muted-foreground text-xs">
      Pilotez CatalogAI depuis Claude Code ou OpenAI Codex : recherche de produits,
      enrichissements, imports. Un jeton agit avec vos droits et vos crédits ; les
      actions qui écrivent dans Tillin demandent une confirmation.
    </CardDescription>
  </CardHeader>
  <CardContent class="flex flex-col gap-4">
    <form class="flex flex-wrap items-end gap-2" onsubmit={create}>
      <div class="flex min-w-48 grow flex-col gap-1.5">
        <Label for="token-name">Nom du jeton</Label>
        <Input
          id="token-name"
          placeholder="Ex. Claude Code — portable"
          maxlength={80}
          bind:value={name}
        />
      </div>
      <div class="flex flex-col gap-1.5">
        <Label for="token-ttl">Validité</Label>
        <Select id="token-ttl" class="w-32" bind:value={ttlDays}>
          <option value={30}>30 jours</option>
          <option value={90}>90 jours</option>
          <option value={365}>1 an</option>
        </Select>
      </div>
      <Button type="submit" size="sm" disabled={!name.trim() || creating}>
        {creating ? "Création…" : "Créer un jeton"}
      </Button>
    </form>

    {#if secret}
      <div class="border-primary/40 bg-primary/5 flex flex-col gap-2 rounded-md border p-3">
        <p class="text-sm font-medium">
          Copiez ce jeton maintenant : il ne sera plus affiché.
        </p>
        <div class="flex items-center gap-2">
          <code class="bg-card min-w-0 grow truncate rounded border px-2 py-1 font-mono text-xs">
            {secret}
          </code>
          <Button variant="outline" size="sm" onclick={() => copy(secret ?? "", "Jeton")}>
            <Copy size={13} aria-hidden="true" data-icon="inline-start" />
            Copier
          </Button>
        </div>
      </div>
    {/if}

    <div class="flex flex-col gap-2">
      <span class="text-xs font-medium">Claude Code</span>
      <div class="flex items-start gap-2">
        <code class="bg-muted min-w-0 grow overflow-x-auto rounded px-2 py-1.5 font-mono text-[11px] whitespace-pre">{claudeCommand}</code>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Copier la commande Claude Code"
          onclick={() => copy(claudeCommand, "Commande")}
        >
          <Copy size={13} />
        </Button>
      </div>
      <span class="text-xs font-medium">Codex (~/.codex/config.toml)</span>
      <div class="flex items-start gap-2">
        <code class="bg-muted min-w-0 grow overflow-x-auto rounded px-2 py-1.5 font-mono text-[11px] whitespace-pre">{codexConfig}</code>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Copier la configuration Codex"
          onclick={() => copy(codexConfig, "Configuration")}
        >
          <Copy size={13} />
        </Button>
      </div>
      <p class="text-muted-foreground text-xs">
        Codex lit le jeton dans la variable d'environnement CATALOGAI_TOKEN. Si
        Claude ou Codex signale une session Tillin expirée, reconnectez-vous ici
        sur CatalogAI (la session Tillin dure 72 h).
      </p>
    </div>

    <div class="flex flex-col gap-2">
      <span class="text-xs font-medium">Vos jetons</span>
      {#if tokens === null}
        <p class="text-muted-foreground text-xs">Chargement…</p>
      {:else if tokens.length === 0}
        <p class="text-muted-foreground text-xs">Aucun jeton pour l'instant.</p>
      {:else}
        <ul class="divide-border flex flex-col divide-y rounded-md border">
          {#each tokens as token (token.id)}
            <li class="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
              <div class="flex min-w-0 flex-col">
                <span class="font-medium">{token.name}</span>
                <span class="text-muted-foreground text-xs">
                  <code class="font-mono">{token.prefix}…</code>
                  · créé {formatRelativeDate(token.created_at)}
                  · {token.last_used_at
                    ? `utilisé ${formatRelativeDate(token.last_used_at)}`
                    : "jamais utilisé"}
                  {#if token.expires_at && token.active}
                    · expire le {formatDay(token.expires_at)}
                  {/if}
                </span>
              </div>
              {#if token.active}
                <ConfirmButton
                  label="Révoquer"
                  confirmLabel="Révoquer ce jeton ?"
                  variant="outline"
                  class="text-destructive"
                  onconfirm={() => revoke(token)}
                />
              {:else}
                <span class="text-muted-foreground text-xs">
                  {token.revoked_at ? "Révoqué" : "Expiré"}
                </span>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  </CardContent>
</Card>
