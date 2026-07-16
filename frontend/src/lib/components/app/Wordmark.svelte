<script lang="ts">
  // Signature de marque : le nom du produit, et « by » + le mot-logo Tillin
  // en dessous. Le nom vient de la config (FRONTEND_APP_NAME) ; l'attribution
  // à Tillin, elle, est constante — c'est l'éditeur, pas un réglage.
  //
  // Deux tailles : `sm` pour la barre latérale (contrainte à 56 px de haut),
  // `lg` pour l'écran de connexion.
  import TillinLogo from "./TillinLogo.svelte"

  let { appName, size = "sm" }: { appName: string; size?: "sm" | "lg" } = $props()

  // Le lettrage « tillin » ne remplit que ~50 % de la hauteur du SVG (le
  // sourire occupe le bas) : le logo doit donc être posé à ~2× la taille du
  // texte « by » pour que les deux paraissent de même corps.
  const nameClass = $derived(size === "lg" ? "text-2xl" : "text-base")
  const byClass = $derived(size === "lg" ? "text-[11px]" : "text-[10px]")
  const logoClass = $derived(size === "lg" ? "h-6 w-auto" : "h-5 w-auto")
</script>

<span
  class="flex flex-col gap-0.5 {size === 'lg' ? 'items-center' : 'items-start'}"
>
  <span class="font-title text-foreground leading-none font-bold {nameClass}">
    {appName}
  </span>
  <span
    class="text-muted-foreground flex items-center gap-1 leading-none {byClass}"
  >
    by
    <!-- Le logo est décoratif (aria-hidden) : le nom accessible est porté par
         ce texte, pour que le tout se lise « … by Tillin ». -->
    <span class="sr-only">Tillin</span>
    <TillinLogo class={logoClass} />
  </span>
</span>
