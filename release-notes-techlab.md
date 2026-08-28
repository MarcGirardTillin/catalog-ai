# Release Notes

## Latest Changes

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
