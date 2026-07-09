<script lang="ts" module>
  // Constructeur de modèle de titre (tokens cliquables, pas de saisie libre :
  // évite les fautes de frappe dans les {tokens}).
  export const TITLE_TOKENS = [
    { key: "title", label: "Titre" },
    { key: "brand", label: "Marque" },
    { key: "season", label: "Saison" },
    { key: "reference", label: "Référence" },
    { key: "color", label: "Couleur" },
    { key: "category", label: "Catégorie" },
    { key: "department", label: "Rayon" },
  ] as const

  export const SEPARATORS = [
    { value: " ", label: "Espace" },
    { value: " - ", label: "Tiret (-)" },
    { value: " · ", label: "Point médian (·)" },
    { value: " | ", label: "Barre (|)" },
    { value: " / ", label: "Barre oblique (/)" },
  ]

  /** Reconstruit tokens + séparateur depuis un modèle stocké, ou null si vide. */
  export function parseTemplate(
    template: string,
  ): { tokens: string[]; separator: string } | null {
    const keys = [...template.matchAll(/\{(\w+)\}/g)]
      .map((match) => match[1])
      .filter((key) => TITLE_TOKENS.some((token) => token.key === key))
    if (keys.length === 0) return null
    // Infer the separator from the text between the first two tokens.
    const between = template.match(/\}([^{}]*)\{/)?.[1]
    const separator =
      between !== undefined && SEPARATORS.some((s) => s.value === between)
        ? between
        : " "
    return { tokens: keys, separator }
  }
</script>

<script lang="ts">
  import { Label } from "@/lib/components/ui/label"

  let {
    tokens = $bindable(),
    separator = $bindable(),
    titleCase = $bindable(),
  }: {
    tokens: string[]
    separator: string
    titleCase: "none" | "upper" | "capitalize"
  } = $props()

  const CASE_OPTIONS = [
    { value: "none", label: "Aucune (tel quel)" },
    { value: "upper", label: "MAJUSCULES" },
    { value: "capitalize", label: "Initiales En Majuscule" },
  ] as const

  /** Applique la casse choisie à l'aperçu (miroir du backend). */
  function applyCase(text: string): string {
    if (titleCase === "upper") return text.toUpperCase()
    if (titleCase === "capitalize")
      return text.replace(/\b\w/g, (c) => c.toUpperCase())
    return text
  }

  // Sample values for the live preview of the template.
  const TOKEN_SAMPLE: Record<string, string> = {
    title: "Polo rayé en coton bio",
    brand: "ARMEDANGELS",
    season: "H26",
    reference: "30008362",
    color: "Vert",
    category: "T-shirts",
    department: "Homme",
  }

  const titleTemplate = $derived(tokens.map((key) => `{${key}}`).join(separator))
  const templatePreview = $derived(
    applyCase(tokens.map((key) => TOKEN_SAMPLE[key] ?? "").join(separator)),
  )
  const availableTokens = $derived(
    TITLE_TOKENS.filter((token) => !tokens.includes(token.key)),
  )

  function addToken(key: string) {
    if (!tokens.includes(key)) tokens = [...tokens, key]
  }

  function removeToken(key: string) {
    tokens = tokens.filter((k) => k !== key)
  }
</script>

<div class="flex flex-col gap-2">
  <Label>Modèle de titre par défaut</Label>

  <!-- Ordered, removable selected tokens. -->
  <div class="flex flex-wrap items-center gap-1.5">
    {#if tokens.length === 0}
      <span class="text-muted-foreground text-xs italic">
        Aucun token — le modèle par défaut {"{title}"} sera utilisé.
      </span>
    {/if}
    {#each tokens as key, index (key)}
      {#if index > 0}
        <span class="text-muted-foreground font-mono text-xs">
          {separator.trim() || "␣"}
        </span>
      {/if}
      <span
        class="bg-primary/10 text-primary inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium"
      >
        {TITLE_TOKENS.find((t) => t.key === key)?.label ?? key}
        <button
          type="button"
          class="hover:bg-primary/20 -mr-1 cursor-pointer rounded-full p-0.5"
          aria-label={`Retirer le token ${key}`}
          onclick={() => removeToken(key)}
        >
          <svg
            width="10"
            height="10"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
            aria-hidden="true"
            ><path d="M18 6 6 18M6 6l12 12" /></svg
          >
        </button>
      </span>
    {/each}
  </div>

  <!-- Remaining tokens: click to append (no free typing = no typos). -->
  {#if availableTokens.length > 0}
    <div class="flex flex-wrap items-center gap-1.5">
      <span class="text-muted-foreground text-xs">Ajouter :</span>
      {#each availableTokens as token (token.key)}
        <button
          type="button"
          class="text-muted-foreground hover:text-foreground hover:bg-muted/50 cursor-pointer rounded-full border border-dashed px-2.5 py-0.5 text-xs transition-colors"
          onclick={() => addToken(token.key)}
        >
          + {token.label}
        </button>
      {/each}
    </div>
  {/if}

  <div class="flex flex-col gap-1.5 sm:max-w-56">
    <Label for="template-separator">Séparateur entre tokens</Label>
    <select
      id="template-separator"
      class="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
      bind:value={separator}
    >
      {#each SEPARATORS as sep (sep.value)}
        <option value={sep.value}>{sep.label}</option>
      {/each}
    </select>
  </div>

  {#if tokens.length > 0}
    <p class="text-muted-foreground text-xs">
      Modèle : <code class="font-mono">{titleTemplate}</code>
      <br />
      Aperçu : <span class="text-foreground">{templatePreview}</span>
    </p>
  {/if}
</div>
