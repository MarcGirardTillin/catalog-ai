# Spec — Filtrer les produits incomplets

Statut : **à faire plus tard** (demande Marc du 2026-10-19, reportée).
Dépend d'une évolution Xano de l'endpoint de recherche produits.

## Besoin

Dans la liste produits de CatalogAI, pouvoir afficher les produits auxquels il
manque une information, pour savoir quoi enrichir ou compléter :

- sans description ;
- sans image ;
- sans poids (aucune variante n'a de poids) ;
- et éventuellement : sans catégorie, sans saison, sans composition, sans
  code-barres sur au moins une variante, sans prix (ou à 0 €), sans meta
  description.

Ces filtres se combinent avec ceux qui existent déjà (texte, fournisseur,
marque, catégorie, saison, tag, statut, site e-commerce) et avec la
pagination.

## Pourquoi côté Xano

La liste vient directement de `GET /products_with_pagination` (Xano), page par
page, avec le total `itemsTotal`. CatalogAI ne voit qu'une page à la fois :

- filtrer la page reçue fausserait le total et le nombre de pages ;
- relire tout le catalogue à chaque recherche (pages de 100 puis tri côté
  CatalogAI) serait lent et coûteux en appels Xano.

Le filtre doit donc être appliqué **dans la requête Xano**, comme
`search_query_ecommerce` aujourd'hui.

> Avant de développer : vérifier les inputs déjà déclarés sur l'endpoint.
> Un paramètre ignoré ne prouve pas que la capacité manque (voir
> `.claude/MISTAKES.md`, filtre e-commerce, 2026-07-16).

## Évolution Xano proposée

Sur `products_with_pagination`, ajouter des inputs booléens optionnels (absents
ou `false` = pas de filtre) :

| Input | Produit retenu quand… |
|---|---|
| `search_query_missing_description` | `description` (et `description_html`) vide ou null |
| `search_query_missing_image` | aucune ligne active dans `product_image` pour le produit, ni image de variante |
| `search_query_missing_weight` | aucune variante avec `weight` > 0 |
| `search_query_missing_category` | `category_id` null/0 et `category_ids` vide |
| `search_query_missing_season` | `season_id` null/0 |
| `search_query_missing_composition` | `composition_id` null/0 |
| `search_query_missing_barcode` | au moins une variante sans `barcode` |
| `search_query_missing_price` | au moins une variante sans prix ou à 0 € |
| `search_query_missing_meta` | `meta_description` vide ou null |

Règles :

- les inputs se combinent en **ET** entre eux et avec les filtres existants ;
- `itemsTotal` reflète le résultat filtré (pagination juste) ;
- « vide » = null, chaîne vide ou uniquement des espaces (et `<p></p>` pour le
  HTML) ;
- seules les images **actives** comptent (une image désactivée par un
  remplacement Studio ne compte pas) ;
- seules les variantes non supprimées comptent.

Priorité si tout ne peut pas être fait d'un coup : description, image, poids.

## Côté CatalogAI (une fois Xano prêt)

- `XanoClient.search_products` : nouveaux paramètres `missing: set[str]`
  traduits en `search_query_missing_*` = `true`.
- `GET /products` : paramètre `missing` (liste, valeurs fermées : `description`,
  `image`, `weight`, `category`, `season`, `composition`, `barcode`, `price`,
  `meta`).
- Liste produits : un filtre « Informations manquantes » (sélection multiple)
  à côté des filtres existants, une puce par critère actif, persistance dans
  l'URL comme les autres filtres.
- MCP : option `missing` sur `catalogai_search_products` (« produits sans
  image de la marque X »).
- Hors périmètre : le filtre « Enrichis » (vue locale, déjà livré) ne se
  combine pas avec ces filtres.

## Critères d'acceptation

1. « Sans image » + marque X renvoie exactement les produits actifs de X sans
   image active, avec un total et des pages justes.
2. Deux critères cochés = produits auxquels il manque les deux.
3. Sans critère, la liste est identique à aujourd'hui.
4. Temps de réponse comparable à une recherche actuelle.
