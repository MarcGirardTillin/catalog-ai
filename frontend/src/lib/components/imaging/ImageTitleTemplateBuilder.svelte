<script lang="ts" module>
  // Constructeur du modèle de titre d'image : séquence ordonnée de tokens
  // cliquables ET de textes libres ({title} mon-texte {position}). Le moteur
  // backend rend les {tokens} et garde le texte littéral tel quel, puis
  // slugifie tout (minuscules, tirets) — pas de casse ni de séparateur.
  export type TemplatePart =
    | { type: "token"; key: string }
    | { type: "text"; value: string }

  export const IMAGE_TOKENS = [
    { key: "reference", label: "Référence" },
    { key: "color", label: "Couleur" },
    { key: "position", label: "Position" },
    { key: "brand", label: "Marque" },
    { key: "title", label: "Titre" },
  ] as const

  /** Segments d'un modèle stocké : tokens connus + textes libres. */
  export function parseImageTemplate(template: string): TemplatePart[] {
    const parts: TemplatePart[] = []
    let last = 0
    for (const match of template.matchAll(/\{(\w+)\}/g)) {
      const literal = template.slice(last, match.index).trim()
      if (literal) parts.push({ type: "text", value: literal })
      if (IMAGE_TOKENS.some((token) => token.key === match[1])) {
        parts.push({ type: "token", key: match[1] })
      }
      last = (match.index ?? 0) + match[0].length
    }
    const tail = template.slice(last).trim()
    if (tail) parts.push({ type: "text", value: tail })
    return parts
  }

  /** Modèle string depuis les segments (séparés par des espaces). */
  export function buildImageTemplate(parts: TemplatePart[]): string {
    return parts
      .map((part) => (part.type === "token" ? `{${part.key}}` : part.value))
      .join(" ")
  }
</script>

<script lang="ts">
  import { Input } from "@/lib/components/ui/input"
  import { Label } from "@/lib/components/ui/label"

  let { parts = $bindable() }: { parts: TemplatePart[] } = $props()

  const TOKEN_SAMPLE: Record<string, string> = {
    reference: "30008362",
    color: "Vert",
    position: "2",
    brand: "ARMEDANGELS",
    title: "Polo rayé en coton bio",
  }

  const template = $derived(buildImageTemplate(parts))
  // Miroir de la slugification backend (minuscules, tirets, sans accents).
  const preview = $derived(
    parts
      .map((part) =>
        part.type === "token" ? (TOKEN_SAMPLE[part.key] ?? "") : part.value,
      )
      .join(" ")
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^A-Za-z0-9._-]+/g, "-")
      .replace(/^[-._]+|[-._]+$/g, "")
      .toLowerCase(),
  )
  const availableTokens = $derived(
    IMAGE_TOKENS.filter(
      (token) =>
        !parts.some((part) => part.type === "token" && part.key === token.key),
    ),
  )

  let freeText = $state("")

  function addToken(key: string) {
    parts = [...parts, { type: "token", key }]
  }

  function addFreeText() {
    // Les accolades sont réservées aux tokens : on les retire du texte libre.
    const value = freeText.replaceAll(/[{}]/g, "").trim()
    if (!value) return
    parts = [...parts, { type: "text", value }]
    freeText = ""
  }

  function removeAt(index: number) {
    parts = parts.filter((_, i) => i !== index)
  }
</script>

<div class="flex flex-col gap-2">
  <Label>Modèle de nom des images</Label>

  <div class="flex flex-wrap items-center gap-1.5">
    {#if parts.length === 0}
      <span class="text-muted-foreground text-xs italic">
        Aucun segment — les images gardent un nom technique automatique.
      </span>
    {/if}
    {#each parts as part, index (index)}
      <span
        class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium
          {part.type === 'token'
          ? 'bg-primary/10 text-primary'
          : 'bg-muted text-foreground'}"
      >
        {part.type === "token"
          ? (IMAGE_TOKENS.find((t) => t.key === part.key)?.label ?? part.key)
          : `« ${part.value} »`}
        <button
          type="button"
          class="{part.type === 'token'
            ? 'hover:bg-primary/20'
            : 'hover:bg-muted-foreground/20'} -mr-1 cursor-pointer rounded-full p-0.5"
          aria-label="Retirer ce segment"
          onclick={() => removeAt(index)}
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
    <!-- Texte libre inséré à la position courante (fin de séquence). -->
    <div class="flex items-center gap-1">
      <Input
        class="h-7 w-36 text-xs"
        placeholder="Texte libre…"
        bind:value={freeText}
        onkeydown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault()
            addFreeText()
          }
        }}
      />
      <button
        type="button"
        class="text-muted-foreground hover:text-foreground hover:bg-muted/50 cursor-pointer rounded-full border border-dashed px-2.5 py-0.5 text-xs transition-colors"
        disabled={!freeText.trim()}
        onclick={addFreeText}
      >
        + Texte
      </button>
    </div>
  </div>

  {#if parts.length > 0}
    <p class="text-muted-foreground text-xs">
      Modèle : <code class="font-mono">{template}</code>
      <br />
      Aperçu : <span class="text-foreground font-mono">{preview}.webp</span>
    </p>
  {/if}
</div>
