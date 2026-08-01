<script lang="ts">
  // Bibliothèque des visages mannequins (face swap « Remplacer le
  // mannequin ») : upload, prévisualisation (fichiers authentifiés, servis
  // en blob), suppression. Utilisée dans les Réglages boutique ; le studio
  // propose les mêmes visages au moment du geste.
  import { onMount } from "svelte"
  import { toast } from "svelte-sonner"

  import {
    deleteFace,
    fetchFacePreview,
    listFaces,
    uploadFace,
    type FaceReferencePublic,
  } from "@/lib/api/faces"
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
  import { Skeleton } from "@/lib/components/ui/skeleton"

  let faces = $state<FaceReferencePublic[] | null>(null)
  let previews = $state<Record<number, string>>({})
  let name = $state("")
  let fileInput = $state<HTMLInputElement | null>(null)
  let uploading = $state(false)

  async function load() {
    const { data, error } = await listFaces()
    if (error || data === undefined) {
      faces = []
      toast.error("Impossible de charger les visages.")
      return
    }
    faces = data
    for (const face of data) {
      if (!previews[face.id]) {
        void fetchFacePreview(face.id).then((url) => {
          if (url) previews[face.id] = url
        })
      }
    }
  }

  onMount(load)

  async function submit(event: SubmitEvent) {
    event.preventDefault()
    const file = fileInput?.files?.[0]
    if (!file) {
      toast.error("Choisissez une image (JPEG, PNG ou WebP).")
      return
    }
    uploading = true
    const { data, error } = await uploadFace(file, name.trim() || file.name)
    uploading = false
    if (error || !data) {
      toast.error("Téléversement impossible.")
      return
    }
    toast.success("Visage ajouté")
    name = ""
    if (fileInput) fileInput.value = ""
    await load()
  }

  async function remove(face: FaceReferencePublic) {
    const { error } = await deleteFace(face.id)
    if (error) {
      toast.error("Suppression impossible.")
      return
    }
    toast.success("Visage supprimé")
    faces = (faces ?? []).filter((f) => f.id !== face.id)
  }
</script>

<Card size="sm">
  <CardHeader>
    <CardTitle class="font-title text-sm">Visages mannequins</CardTitle>
    <CardDescription class="text-muted-foreground text-xs">
      Visages de référence proposés par « Remplacer le mannequin » dans le
      studio : le mannequin des visuels générés prend l'identité choisie, la
      tenue reste intacte. Portrait net, de face, bien éclairé.
    </CardDescription>
  </CardHeader>
  <CardContent class="flex flex-col gap-4">
    <form class="flex flex-wrap items-end gap-2" onsubmit={submit}>
      <div class="flex flex-col gap-1.5">
        <Label for="face-file">Image</Label>
        <input
          id="face-file"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          class="border-input bg-card h-9 max-w-64 rounded-md border px-2.5 py-1.5 text-xs"
          bind:this={fileInput}
        />
      </div>
      <div class="flex flex-col gap-1.5">
        <Label for="face-name">Nom</Label>
        <Input id="face-name" class="max-w-48" placeholder="Ex. Léa" bind:value={name} />
      </div>
      <Button type="submit" size="sm" disabled={uploading}>
        {uploading ? "Téléversement…" : "Ajouter"}
      </Button>
    </form>

    {#if faces === null}
      <Skeleton class="h-24 w-full" />
    {:else if faces.length === 0}
      <p class="text-muted-foreground text-sm">
        Aucun visage pour l'instant — ajoutez-en un pour activer le
        remplacement de mannequin.
      </p>
    {:else}
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        {#each faces as face (face.id)}
          <div class="border-border flex flex-col gap-1.5 rounded-md border p-2">
            {#if previews[face.id]}
              <img
                src={previews[face.id]}
                alt={face.name}
                class="bg-muted aspect-square w-full rounded object-cover"
              />
            {:else}
              <Skeleton class="aspect-square w-full rounded" />
            {/if}
            <span class="truncate text-xs font-medium" title={face.name}>
              {face.name}
            </span>
            <ConfirmButton
              label="Supprimer"
              confirmLabel="Confirmer ?"
              onconfirm={() => remove(face)}
            />
          </div>
        {/each}
      </div>
    {/if}
  </CardContent>
</Card>
