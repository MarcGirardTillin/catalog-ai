<script lang="ts" module>
  // Constructeur du modèle de titre d'image (même principe que le modèle de
  // titre produit : tokens cliquables, pas de saisie libre). Le nom rendu est
  // TOUJOURS slugifié côté serveur (minuscules, tirets) — pas de casse ni de
  // séparateur à choisir.
  export const IMAGE_TOKENS = [
    { key: "reference", label: "Référence" },
    { key: "color", label: "Couleur" },
    { key: "position", label: "Position" },
    { key: "brand", label: "Marque" },
    { key: "title", label: "Titre" },
  ] as const

  /** Tokens d'un modèle stocké (les inconnus sont ignorés). */
  export function parseImageTemplate(template: string): string[] {
    return [...template.matchAll(/\{(\w+)\}/g)]
      .map((match) => match[1])
      .filter((key) => IMAGE_TOKENS.some((token) => token.key === key))
  }
</script>

<script lang="ts">
  import { Label } from "@/lib/components/ui/label"

  let { tokens = $bindable() }: { tokens: string[] } = $props()

  const TOKEN_SAMPLE: Record<string, string> = {
    reference: "30008362",
    color: "Vert",
    position: "2",
    brand: "ARMEDANGELS",
    title: "Polo rayé en coton bio",
  }

  const template = $derived(tokens.map((key) => `{${key}}`).join(" "))
  // Miroir de la slugification backend (minuscules, tirets, sans accents).
  const preview = $derived(
    tokens
      .map((key) => TOKEN_SAMPLE[key] ?? "")
      .join(" ")
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^A-Za-z0-9._-]+/g, "-")
      .replace(/^[-._]+|[-._]+$/g, "")
      .toLowerCase(),
  )
  const availableTokens = $derived(
    IMAGE_TOKENS.filter((token) => !tokens.includes(token.key)),
  )

  function addToken(key: string) {
    if (!tokens.includes(key)) tokens = [...tokens, key]
  }

  function removeToken(key: string) {
    tokens = tokens.filter((k) => k !== key)
  }
</script>

<div class="flex flex-col gap-2">
  <Label>Modèle de nom des images</Label>

  <div class="flex flex-wrap items-center gap-1.5">
    {#if tokens.length === 0}
      <span class="text-muted-foreground text-xs italic">
        Aucun token — les images gardent un nom technique automatique.
      </span>
    {/if}
    {#each tokens as key (key)}
      <span
        class="bg-primary/10 text-primary inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium"
      >
        {IMAGE_TOKENS.find((t) => t.key === key)?.label ?? key}
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
            aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg
          >
        </button>
      </span>
    {/each}
  </div>

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

  {#if tokens.length > 0}
    <p class="text-muted-foreground text-xs">
      Modèle : <code class="font-mono">{template}</code>
      <br />
      Aperçu : <span class="text-foreground font-mono">{preview}.webp</span>
    </p>
  {/if}
</div>
