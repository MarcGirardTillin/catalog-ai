<script lang="ts">
  // Signature de marque : le wordmark « Catalog » (nom seul, figé — décision
  // Marc 2026-07-17, sans le monogramme ; il remplace l'ancien nom
  // configurable FRONTEND_APP_NAME ici), et « by » + le mot-logo Tillin en
  // dessous. L'attribution à Tillin est constante — c'est l'éditeur, pas un
  // réglage.
  //
  // Deux tailles : `sm` pour la barre latérale (contrainte à 56 px de haut),
  // `lg` pour l'écran de connexion.
  import TillinLogo from "./TillinLogo.svelte"

  let { size = "sm" }: { size?: "sm" | "lg" } = $props()

  // Style repris du lockup source (catalog-lockup-navy.svg) : Nunito 800,
  // tracking -2/62 ≈ -0,03 em → font-extrabold + tracking-tight.
  const nameClass = $derived(size === "lg" ? "text-4xl" : "text-lg")

  // Le lettrage « tillin » ne remplit que ~50 % de la hauteur du SVG (le
  // sourire occupe le bas) : le logo doit donc être posé à ~2× la taille du
  // texte « by » pour que les deux paraissent de même corps.
  const byClass = $derived(size === "lg" ? "text-[13px]" : "text-[10px]")
  const logoClass = $derived(size === "lg" ? "h-7 w-auto" : "h-5 w-auto")
</script>

<!-- Le nom, seul en flux, fixe la largeur du bloc (il est toujours le plus
     large des deux). La ligne « by tillin » est ensuite décalée en position
     relative : `left-1/2` vaut 50 % de cette largeur, donc le « by » démarre
     au milieu du nom et le logo déborde librement à droite — sans élargir le
     bloc, ce qui garde le nom centré sur l'écran de connexion. -->
<span class="flex flex-col items-start gap-0.5">
  <span
    class="font-title text-foreground leading-none font-extrabold tracking-tight {nameClass}"
  >
    Catalog
  </span>
  <span
    class="text-muted-foreground relative left-1/2 flex items-center gap-1 leading-none {byClass}"
  >
    by
    <!-- Le logo est décoratif (aria-hidden) : le nom accessible est porté par
         ce texte, pour que le tout se lise « … by Tillin ». -->
    <span class="sr-only">Tillin</span>
    <!-- Le lettrage occupe le HAUT de la viewBox (y 389→607 sur 380→720) : son
         centre est ~15 % de la hauteur au-dessus du centre de la boîte. Sans
         correction, un alignement vertical centre la boîte (sourire compris)
         et le « by » tombe donc trop bas par rapport au mot. On redescend le
         logo d'autant pour aligner « by » sur « tillin », et non sur le SVG.

         `text-foreground` = le navy #150245 du logo officiel en thème clair,
         et le blanc cassé en thème sombre — où le fond EST ce même navy et où
         la charte prévoit justement la variante blanche du logo. -->
    <TillinLogo class="{logoClass} text-foreground translate-y-[15%]" />
  </span>
</span>
