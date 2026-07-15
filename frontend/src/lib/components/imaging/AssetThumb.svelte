<script lang="ts">
  // Miniature d'un asset d'imagerie : charge le premier fichier stagé en blob
  // (auth cookie) tant qu'il existe — après enregistrement ou rejet, le
  // staging est purgé et on affiche un simple placeholder.
  import ImageOff from "@lucide/svelte/icons/image-off"

  import { fetchAssetPreviews, type ImageAssetPublic } from "@/lib/api/imaging"

  let { asset }: { asset: ImageAssetPublic } = $props()

  let url = $state<string | null>(null)
  let failed = $state(false)

  const previewable = $derived(
    asset.status === "completed" &&
      !asset.saved &&
      (asset.preview_urls?.length ?? 0) > 0,
  )

  $effect(() => {
    if (!previewable) return
    let revoked = false
    fetchAssetPreviews(asset).then((urls) => {
      if (revoked) {
        for (const u of urls) URL.revokeObjectURL(u)
        return
      }
      url = urls[0] ?? null
      failed = urls.length === 0
      for (const u of urls.slice(1)) URL.revokeObjectURL(u)
    })
    return () => {
      revoked = true
      if (url) URL.revokeObjectURL(url)
    }
  })
</script>

{#if url}
  <img
    src={url}
    alt="Visuel généré"
    class="bg-muted size-10 rounded-md object-cover"
  />
{:else}
  <span
    class="bg-muted text-muted-foreground flex size-10 items-center justify-center rounded-md {previewable && !failed
      ? 'animate-pulse'
      : ''}"
    aria-hidden="true"
  >
    <ImageOff size={14} />
  </span>
{/if}
