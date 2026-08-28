<script lang="ts" module>
  export type SampleImage = { url: string; label?: string }

  /** Normalise une saisie en « RRGGBB » majuscules, null si invalide. */
  export function normalizeHex(value: string): string | null {
    const raw = value.trim().replace(/^#/, "")
    if (/^[0-9a-fA-F]{6}$/.test(raw)) return raw.toUpperCase()
    if (/^[0-9a-fA-F]{3}$/.test(raw)) {
      return raw
        .split("")
        .map((c) => c + c)
        .join("")
        .toUpperCase()
    }
    return null
  }
</script>

<script lang="ts">
  // Sélecteur de couleur avec PIPETTE (demande Marc 2026-08-28) :
  // - sélecteur natif + champ hexadécimal ;
  // - pipette écran via l'API EyeDropper (Chrome/Edge/Opera) : pointer
  //   n'importe quel pixel affiché, y compris hors du navigateur ;
  // - repli (Safari/Firefox, ou clic sur « sur une image ») : pipette sur
  //   une image de la galerie, lue pixel à pixel dans un canvas.
  // La valeur remontée suit le format du parent (`hash` : « #RRGGBB »
  // ou « RRGGBB »).
  import Pipette from "@lucide/svelte/icons/pipette"
  import { Dialog } from "@/lib/components/ui/dialog"
  import { Input } from "@/lib/components/ui/input"
  import { toast } from "svelte-sonner"

  let {
    id,
    value = $bindable(""),
    hash = true,
    disabled = false,
    placeholder = "#1F4E3D",
    images = [],
    inputClass = "",
  }: {
    id: string
    /** Couleur courante (hex, avec ou sans « # » — libre pour le parent). */
    value: string
    /** true = le composant écrit « #RRGGBB », false = « RRGGBB ». */
    hash?: boolean
    disabled?: boolean
    placeholder?: string
    /** Images sur lesquelles pointer en repli (galerie du produit). */
    images?: SampleImage[]
    inputClass?: string
  } = $props()

  const hexValue = $derived(`#${normalizeHex(value) ?? "888888"}`)
  const eyeDropperSupported =
    typeof window !== "undefined" && "EyeDropper" in window

  function emit(hex: string) {
    const normalized = normalizeHex(hex)
    if (!normalized) return
    value = hash ? `#${normalized}` : normalized
  }

  type EyeDropperCtor = new () => { open(): Promise<{ sRGBHex: string }> }

  async function pickOnScreen() {
    const Ctor = (window as unknown as { EyeDropper?: EyeDropperCtor }).EyeDropper
    if (!Ctor) {
      openImagePicker()
      return
    }
    try {
      const result = await new Ctor().open()
      emit(result.sRGBHex)
    } catch {
      // Échap / annulation : rien à faire.
    }
  }

  // --- Repli : pipette sur une image (canvas) ---
  let pickerOpen = $state(false)
  let pickerImage = $state<SampleImage | null>(null)
  let canvas = $state<HTMLCanvasElement | null>(null)
  let hover = $state<string | null>(null)
  let readError = $state<string | null>(null)

  function openImagePicker() {
    if (images.length === 0) {
      toast.info(
        "Aucune image à échantillonner — la pipette écran n'est disponible que sur Chrome/Edge.",
      )
      return
    }
    pickerImage = images[0]
    pickerOpen = true
  }

  $effect(() => {
    const target = canvas
    const image = pickerImage
    if (!target || !image) return
    readError = null
    hover = null
    const element = new Image()
    // Nécessaire pour lire les pixels d'une image d'un autre domaine ; si
    // le CDN ne renvoie pas d'en-tête CORS, le canvas est « teinté » et la
    // lecture échoue proprement (message ci-dessous).
    element.crossOrigin = "anonymous"
    element.onload = () => {
      const max = 720
      const scale = Math.min(1, max / Math.max(element.width, element.height))
      target.width = Math.round(element.width * scale)
      target.height = Math.round(element.height * scale)
      const ctx = target.getContext("2d", { willReadFrequently: true })
      if (!ctx) return
      ctx.drawImage(element, 0, 0, target.width, target.height)
      try {
        ctx.getImageData(0, 0, 1, 1)
      } catch {
        readError =
          "Impossible de lire les pixels de cette image (le site qui l'héberge n'autorise pas la lecture)."
      }
    }
    element.onerror = () => {
      readError = "Impossible de charger cette image."
    }
    element.src = image.url
  })

  function sampleAt(event: MouseEvent): string | null {
    const target = canvas
    if (!target || readError) return null
    const rect = target.getBoundingClientRect()
    const x = Math.floor(((event.clientX - rect.left) / rect.width) * target.width)
    const y = Math.floor(((event.clientY - rect.top) / rect.height) * target.height)
    const ctx = target.getContext("2d", { willReadFrequently: true })
    if (!ctx) return null
    try {
      const [r, g, b] = ctx.getImageData(x, y, 1, 1).data
      return [r, g, b].map((c) => c.toString(16).padStart(2, "0")).join("").toUpperCase()
    } catch {
      return null
    }
  }

  function onCanvasMove(event: MouseEvent) {
    hover = sampleAt(event)
  }

  function onCanvasClick(event: MouseEvent) {
    const hex = sampleAt(event)
    if (!hex) return
    emit(hex)
    pickerOpen = false
  }
</script>

<div class="flex items-center gap-2">
  <input
    {id}
    type="color"
    class="border-input bg-card h-9 w-10 shrink-0 cursor-pointer rounded-md border p-1"
    {disabled}
    value={hexValue}
    oninput={(e) => emit(e.currentTarget.value)}
  />
  <Input class="font-mono {inputClass}" {placeholder} {disabled} bind:value />
  <button
    type="button"
    class="border-input bg-card text-muted-foreground hover:text-foreground flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-md border transition-colors disabled:cursor-not-allowed disabled:opacity-50"
    {disabled}
    title={eyeDropperSupported
      ? "Pipette : pointer une couleur à l'écran"
      : "Pipette : pointer une couleur sur une image du produit"}
    aria-label="Pipette"
    onclick={pickOnScreen}
  >
    <Pipette size={15} aria-hidden="true" />
  </button>
  {#if eyeDropperSupported && images.length > 0}
    <button
      type="button"
      class="text-muted-foreground cursor-pointer text-xs whitespace-nowrap underline-offset-2 hover:underline disabled:cursor-not-allowed disabled:opacity-50"
      {disabled}
      onclick={openImagePicker}
    >
      sur une image
    </button>
  {/if}
</div>

{#if pickerOpen}
  <Dialog title="Pointer une couleur sur l'image" onClose={() => (pickerOpen = false)}>
    <div class="flex flex-col gap-3">
      {#if images.length > 1}
        <div class="flex flex-wrap gap-1.5">
          {#each images as image (image.url)}
            <button
              type="button"
              class="overflow-hidden rounded border {pickerImage?.url === image.url
                ? 'border-primary ring-primary/40 ring-2'
                : 'border-border opacity-70 hover:opacity-100'}"
              title={image.label ?? ""}
              onclick={() => (pickerImage = image)}
            >
              <img src={image.url} alt="" loading="lazy" class="bg-muted h-12 w-10 object-cover" />
            </button>
          {/each}
        </div>
      {/if}
      {#if readError}
        <p class="text-destructive text-xs" role="alert">{readError}</p>
      {/if}
      <div class="flex max-h-[60vh] justify-center overflow-auto">
        <canvas
          bind:this={canvas}
          class="max-h-[60vh] max-w-full cursor-crosshair rounded"
          onmousemove={onCanvasMove}
          onmouseleave={() => (hover = null)}
          onclick={onCanvasClick}
        ></canvas>
      </div>
      <div class="text-muted-foreground flex items-center gap-2 text-xs">
        {#if hover}
          <span class="border-border h-5 w-5 rounded border" style="background:#{hover}"></span>
          <span class="font-mono">#{hover}</span>
          <span>— cliquer pour choisir</span>
        {:else}
          <span>Survolez l'image, cliquez pour choisir la couleur.</span>
        {/if}
      </div>
    </div>
  </Dialog>
{/if}
