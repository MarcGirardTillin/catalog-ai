# Release Notes

## Latest Changes

- Enrichissement : les sites de marque qui ne sont pas des boutiques
  Shopify (Magento, WooCommerce, PrestaShop…) sont désormais interrogés via
  leur propre moteur de recherche, au code-barres puis à la référence,
  gratuitement et avant la recherche web : une fiche n'est retenue que si
  le code-barres (ou la référence) y figure bien (ex. Le Petit Souk).
- Console admin — Coûts : la grille des coûts fournisseurs est désormais
  COMMUNE à tous les comptes (une seule ligne à créer pour un nouveau
  modèle) ; une remise négociée pour un client s'ajoute en « Exception de
  coûts » sur la page de son compte, avec le prix commun remplacé en
  regard. La migration fusionne les copies existantes sans changer aucun
  coût affiché et ajoute les prix de Claude Sonnet 5.5 (2 $ / 10 $ par
  million de tokens). Les mois déjà figés ne bougent pas.
- Studio : onglet « Cadrage » sous l'image (à côté de « Produit » ou
  « Aperçu »), sur le modèle de l'éditeur Tillin : cadre fixe, image
  déplacée et zoomée dessous, poignées dans les angles (et sur les côtés en
  format Libre) avec recalage façon iPhone, formats 1:1 · 16:9 · 4:5 · 5:4 ·
  Libre, rotation, miroir, taille de sortie ; appliqué en direct. Il s'applique à l'image telle qu'elle est : une
  retouche IA (embellissement, ombre…) n'est plus perdue au recadrage, et
  le recadrage survit au repositionnement. Disponible aussi sur les mises à
  plat et autres générations à sortie unique ; gratuit.
- Modèle IA par défaut : Claude Sonnet 5.5.
- Enrichissement : un produit à plusieurs couleurs dont chaque couleur a sa
  propre fiche sur le site de la marque peut recevoir une fiche
  supplémentaire par couleur (« Ajouter pour une couleur » sur un candidat
  ou une URL collée). Ses images s'ajoutent au produit, groupées par
  couleur dans la vérification ; description, meta, titre, prix et poids
  restent issus de la fiche principale (dont la couleur se précise aussi).
- Jobs de fond (enrichissement, import) : le jeton Tillin du LANCEUR du job
  est utilisé en priorité (relances comprises), avec repli sur le jeton le
  plus récent du compte — fini les échecs « session expired » ou « produit
  introuvable » quand l'utilisateur du pool a changé d'entreprise.
- Studio : pipette couleur (fond, couleur du vêtement, couleur cible) —
  pointer un pixel à l'écran (Chrome/Edge) ou sur une image du produit ;
  variable « Rayon » disponible dans le modèle de nom d'images.
- Mise à jour : une bannière propose de recharger la page quand une nouvelle
  version de Catalog a été déployée.
- Import : la catégorie est toujours rattachée à une catégorie VISIBLE de la
  boutique ; un libellé hors arbre est laissé vide (jamais transmis tel quel).
- Import : la référence corrigée en review est re-vérifiée dans Tillin
  (avertissement « déjà présente » remplacé, jamais empilé) ; une colonne
  « tags / mots-clés » du fichier fournisseur remplit désormais les tags du
  produit (cumulés avec ceux du profil) ; après transfert, l'aperçu CSV et le
  téléchargement ressortent la copie des lignes envoyées à Tillin (lecture
  seule, datée) au lieu d'un rendu vide.
- Fiabilité : les images d'enrichissement sont désormais téléchargées par
  CatalogAI et poussées en octets vérifiés vers Tillin — tout écart
  (image refusée) est signalé sur la fiche au lieu d'être perdu en
  silence ; un poids à 0 n'est plus compté comme renseigné (+ colonne
  Poids dans le panneau produit) ; les « | » sont remplacés par « / »
  dans les titres/références/variantes ; les URLs collées en résolution
  manuelle sont nettoyées (paramètres de tracking) avec repli sur le
  handle Shopify ; la case « Traduire » (sans effet) est retirée.
- Enrichissement : résolution de la page source plus fiable — références
  comparées sans tenir compte de la mise en forme, couleur du produit
  utilisée pour départager les coloris d'un même modèle (jamais de mauvais
  coloris auto-résolu), titres templatés « {titre} - {marque} - {couleur} »
  compris par la recherche, et vignettes d'aperçu sur la page source et les
  candidats dans la review (avec couleur et adresse de la fiche).
- Enrichissement : quand la page source est incertaine, la description n'est
  plus rédigée automatiquement — elle attend la validation d'une source ou le
  geste « Générer la description sans source » ; la couleur du produit précise
  la recherche de la fiche ; les tâches et le fil d'ariane affichent le titre
  du produit ; libellés de résolution neutres (marque blanche).
- Studio : la barre de zoom ne bouge plus quand « Réinitialiser » apparaît ;
  « Remplacer l'originale » est coché par défaut pour les images traitées.
- Imports : l'onglet « Par import » de la liste des produits affiche l'image
  du produit Tillin lié (capturée au lien, rafraîchie par « Lier »).
- Studio d'images : mise à plat (flat lay) et mannequin invisible (ghost
  mannequin) Photoroom, moteur de génération mannequin au choix (FASHN ou
  Photoroom Virtual Model — presets mannequin/décor/pose, multi-vues), et
  finalisation IA optionnelle (ombre, décor IA, défroissage, retouche beauté,
  agrandissement, recoloration) appliquée sur la position validée.
- Initial project setup.
