<script lang="ts">
  // Bibliothèque d'instructions éditoriales nommées (CRUD complet).
  // Chaque instruction peut être sélectionnée à la création d'un job ; les
  // catégories par défaut permettent au backend de l'appliquer automatiquement.
  import NotebookPen from "@lucide/svelte/icons/notebook-pen"
  import Plus from "@lucide/svelte/icons/plus"
  import Search from "@lucide/svelte/icons/search"
  import { onMount } from "svelte"
  import { toast } from "svelte-sonner"

  import {
    createInstruction,
    deleteInstruction,
    listInstructions,
    updateInstruction,
  } from "@/lib/api/instructions"
  import type { InstructionPublic } from "@/lib/api/instructions"
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
  import { Separator } from "@/lib/components/ui/separator"
  import { Skeleton } from "@/lib/components/ui/skeleton"
  import TagInput from "@/lib/components/app/TagInput.svelte"

  let instructions = $state<InstructionPublic[] | null>(null)
  let loadFailed = $state(false)

  // Recherche par nom : la bibliothèque peut dépasser 30 instructions.
  let search = $state("")
  const filteredInstructions = $derived.by(() => {
    if (instructions === null) return []
    const needle = search.trim().toLowerCase()
    if (needle === "") return instructions
    return instructions.filter((i) => i.name.toLowerCase().includes(needle))
  })

  // Formulaire inline créer/modifier : editingId === null → création.
  let formOpen = $state(false)
  let editingId = $state<number | null>(null)
  let name = $state("")
  let content = $state("")
  let categories = $state<string[]>([])
  let formError = $state<string | null>(null)
  let saving = $state(false)

  // Suppression en deux temps (même pattern que le rejet en review).
  let confirmingDeleteId = $state<number | null>(null)
  let deleteTimer: ReturnType<typeof setTimeout> | undefined

  onMount(async () => {
    const { data, error } = await listInstructions()
    if (error || data === undefined) {
      loadFailed = true
      instructions = []
      toast.error("Impossible de charger la bibliothèque d'instructions.")
      return
    }
    instructions = data
  })

  function openCreate() {
    editingId = null
    name = ""
    content = ""
    categories = []
    formError = null
    formOpen = true
  }

  function openEdit(instruction: InstructionPublic) {
    editingId = instruction.id
    name = instruction.name
    content = instruction.content
    categories = [...instruction.categories]
    formError = null
    formOpen = true
  }

  function closeForm() {
    formOpen = false
    editingId = null
    formError = null
  }

  async function submitForm(event: SubmitEvent) {
    event.preventDefault()
    formError = null
    const body = {
      name: name.trim(),
      content: content.trim(),
      categories: categories.map((c) => c.trim()).filter((c) => c !== ""),
    }
    if (!body.name || !body.content) {
      formError = "Le nom et le contenu sont obligatoires."
      return
    }
    saving = true
    if (editingId === null) {
      const { data, error } = await createInstruction(body)
      saving = false
      if (error || data === undefined) {
        toast.error("Création de l'instruction impossible.")
        return
      }
      instructions = [...(instructions ?? []), data]
      toast.success("Instruction créée")
    } else {
      const { data, error } = await updateInstruction(editingId, body)
      saving = false
      if (error || data === undefined) {
        toast.error("Enregistrement de l'instruction impossible.")
        return
      }
      instructions = (instructions ?? []).map((i) => (i.id === data.id ? data : i))
      toast.success("Instruction mise à jour")
    }
    closeForm()
  }

  async function onDeleteClick(id: number) {
    clearTimeout(deleteTimer)
    if (confirmingDeleteId !== id) {
      // First activation arms the button; it disarms after a short delay.
      confirmingDeleteId = id
      deleteTimer = setTimeout(() => (confirmingDeleteId = null), 3000)
      return
    }
    confirmingDeleteId = null
    const { error } = await deleteInstruction(id)
    if (error !== undefined) {
      toast.error("Suppression impossible.")
      return
    }
    instructions = (instructions ?? []).filter((i) => i.id !== id)
    if (editingId === id) closeForm()
    toast.success("Instruction supprimée")
  }
</script>

<Card size="sm">
  <CardHeader>
    <CardTitle class="font-title text-sm">Bibliothèque d'instructions</CardTitle>
    <CardDescription class="text-muted-foreground text-xs">
      Instructions éditoriales nommées, réutilisables à la création d'un job.
      Les catégories indiquent où elles s'appliquent par défaut.
    </CardDescription>
  </CardHeader>
  <CardContent class="flex flex-col gap-3">
    {#if instructions === null}
      <Skeleton class="h-12 w-full" />
      <Skeleton class="h-12 w-full" />
    {:else}
      {#if instructions.length === 0 && !formOpen}
        <div class="flex flex-col items-center gap-3 py-6 text-center">
          <span class="bg-muted flex size-12 items-center justify-center rounded-full">
            <NotebookPen size={20} class="text-muted-foreground" aria-hidden="true" />
          </span>
          <p class="text-muted-foreground max-w-sm text-sm">
            {loadFailed
              ? "La bibliothèque n'a pas pu être chargée. Réessayez plus tard."
              : "Aucune instruction pour l'instant. Créez par exemple « Ton chaussures » ou « Descriptions accessoires » pour guider la génération selon la catégorie."}
          </p>
        </div>
      {:else if instructions.length > 0}
        <div class="relative sm:max-w-72">
          <Search
            size={14}
            class="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2"
            aria-hidden="true"
          />
          <Input
            type="search"
            class="pl-8"
            placeholder="Rechercher une instruction…"
            aria-label="Rechercher une instruction par nom"
            bind:value={search}
          />
        </div>
        {#if filteredInstructions.length === 0}
          <p class="text-muted-foreground py-2 text-sm">
            Aucune instruction ne correspond à « {search.trim()} ».
          </p>
        {/if}
        <ul class="flex flex-col">
          {#each filteredInstructions as instruction, index (instruction.id)}
            {#if index > 0}
              <Separator />
            {/if}
            <li class="flex items-start justify-between gap-3 py-2.5">
              <div class="flex min-w-0 flex-col gap-1">
                <span class="text-sm font-medium">{instruction.name}</span>
                <span class="text-muted-foreground line-clamp-2 text-xs">
                  {instruction.content}
                </span>
                {#if instruction.categories.length > 0}
                  <div class="flex flex-wrap items-center gap-1">
                    {#each instruction.categories as category (category)}
                      <span
                        class="bg-muted text-muted-foreground rounded-full px-1.5 py-0.5 text-xs whitespace-nowrap"
                      >
                        {category}
                      </span>
                    {/each}
                  </div>
                {/if}
              </div>
              <div class="flex shrink-0 items-center gap-1">
                <Button variant="ghost" size="sm" onclick={() => openEdit(instruction)}>
                  Modifier
                </Button>
                <Button
                  variant={confirmingDeleteId === instruction.id ? "destructive" : "ghost"}
                  size="sm"
                  onclick={() => onDeleteClick(instruction.id)}
                >
                  {confirmingDeleteId === instruction.id ? "Confirmer ?" : "Supprimer"}
                </Button>
              </div>
            </li>
          {/each}
        </ul>
      {/if}

      {#if formOpen}
        <form
          class="border-border flex flex-col gap-3 rounded-md border border-dashed p-3"
          onsubmit={submitForm}
        >
          <span class="text-sm font-medium">
            {editingId === null ? "Nouvelle instruction" : "Modifier l'instruction"}
          </span>
          <div class="flex flex-col gap-1.5 sm:max-w-80">
            <Label for="instruction-name">Nom</Label>
            <Input
              id="instruction-name"
              placeholder="Ex. Ton chaussures"
              bind:value={name}
            />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label for="instruction-content">Contenu</Label>
            <textarea
              id="instruction-content"
              rows="3"
              class="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 field-sizing-content max-h-60 min-h-20 w-full resize-none rounded-md border p-2.5 text-sm transition-colors outline-none focus-visible:ring-1"
              placeholder="Ex. Insister sur le confort et la matière, phrases courtes, pas de superlatifs…"
              bind:value={content}
            ></textarea>
          </div>
          <div class="flex flex-col gap-1.5">
            <Label for="instruction-categories">Catégories par défaut</Label>
            <TagInput
              id="instruction-categories"
              bind:values={categories}
              placeholder="Ex. Chaussures — Entrée pour ajouter"
            />
            <p class="text-muted-foreground text-xs">
              Optionnel : l'instruction s'appliquera d'office aux produits de ces catégories.
            </p>
          </div>
          {#if formError}
            <p class="text-destructive text-xs" role="alert">{formError}</p>
          {/if}
          <div class="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onclick={closeForm}>Annuler</Button>
            <Button type="submit" size="sm" disabled={saving}>
              {saving ? "Enregistrement…" : "Enregistrer"}
            </Button>
          </div>
        </form>
      {:else}
        <div>
          <Button variant="outline" size="sm" onclick={openCreate}>
            <Plus size={14} aria-hidden="true" data-icon="inline-start" />
            Nouvelle instruction
          </Button>
        </div>
      {/if}
    {/if}
  </CardContent>
</Card>
