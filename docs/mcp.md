# Serveur MCP CatalogAI — connexion Claude Code et Codex

CatalogAI expose un serveur MCP (Model Context Protocol) sur
`https://api-catalog.tillin.fr/mcp` (Streamable HTTP, sans état, réponses
JSON). Il permet de piloter la boutique depuis Claude Code ou OpenAI Codex
avec **exactement les droits de l'utilisateur** : modules activés du compte,
solde de crédits, données de son entreprise uniquement.

## 1. Créer un jeton

CatalogAI → **Paramètres → Claude & Codex** → « Créer un jeton » (validité 30
jours, 90 jours ou 1 an). Le jeton (`cat_…`) n'est affiché qu'une fois : le
copier tout de suite. On peut le révoquer à tout moment depuis la même page.

## 2. Brancher le client

**Claude Code**

```bash
claude mcp add --transport http catalogai https://api-catalog.tillin.fr/mcp \
  --header "Authorization: Bearer cat_xxxxxxxx_…"
```

**OpenAI Codex** (`~/.codex/config.toml`, jeton dans la variable
d'environnement `CATALOGAI_TOKEN`)

```toml
[mcp_servers.catalogai]
url = "https://api-catalog.tillin.fr/mcp"
bearer_token_env_var = "CATALOGAI_TOKEN"
default_tools_approval_mode = "writes"
```

La page Paramètres affiche ces deux blocs prêts à copier (jeton inclus juste
après sa création).

### claude.ai (web, Desktop, mobile) — connecteur, sans jeton

claude.ai → **Paramètres → Connecteurs → Ajouter un connecteur personnalisé**,
URL `https://api-catalog.tillin.fr/mcp`. Claude ouvre la page de
consentement de CatalogAI (connexion si besoin) : « Autoriser » donne
l'accès en votre nom. L'accès peut être limité à la lecture (scope
`catalogai:read`) ; les actions (lancer, valider, appliquer, transférer)
demandent `catalogai:write`. Côté Codex, `codex mcp login catalogai` suit le
même parcours si l'on préfère OAuth au jeton personnel.

Sous le capot : OAuth 2.1 (enregistrement dynamique RFC 7591, PKCE S256,
jeton d'accès 1 h, rafraîchissement 30 jours avec rotation), métadonnées sur
`/.well-known/oauth-protected-resource/mcp` et
`/.well-known/oauth-authorization-server`.

## 3. Outils disponibles

| Outil | Rôle | Module | Écrit dans Tillin |
|---|---|---|---|
| `catalogai_get_account_overview` | modules, crédits, coûts par action, session Tillin | — | non |
| `catalogai_search_products` | recherche catalogue (texte, marque par nom ou id) | — | non |
| `catalogai_list_brands` | marques (recherche par nom) | — | non |
| `catalogai_get_product` | fiche, variantes, images | — | non |
| `catalogai_start_enrichment` | lance un enrichissement (renvoie le job) | enrichissement | non (débite des crédits) |
| `catalogai_list_enrichments` | enrichissements lancés (filtre par jour, statut) | enrichissement | non |
| `catalogai_list_enriched_products` | fiches traitées sur une période, par marque et statut | enrichissement | non |
| `catalogai_get_job_status` | suivi d'un enrichissement | enrichissement | non |
| `catalogai_list_items_to_review` | fiches et propositions de l'IA | enrichissement | non |
| `catalogai_review_item` | valider / écarter / relancer | enrichissement | non |
| `catalogai_apply_item` | applique une fiche validée — aperçu sans `confirm=true` | enrichissement | **oui** |
| `catalogai_list_imports` | imports (statut, suivi produits, fournisseur) | import | non |
| `catalogai_get_import_review` | produits extraits d'un import | import | non |
| `catalogai_list_locations` | magasins Tillin | import | non |
| `catalogai_transfer_import` | crée les produits et la réception — aperçu sans `confirm=true` | import | **oui** |

## 4. Bon à savoir

- **Session Tillin (72 h)** : les outils qui lisent ou écrivent dans Tillin
  utilisent la session Tillin de l'utilisateur, renouvelée à chaque connexion
  à l'app web. Si Claude ou Codex répond « session Tillin expirée »,
  se reconnecter sur catalog.tillin.fr puis relancer.
- **Traitements longs** : un enrichissement renvoie son identifiant tout de
  suite ; le suivre avec `catalogai_get_job_status`.
- **Sécurité** : seul le hachage du jeton est stocké ; chaque appel revérifie
  le compte, les modules et les crédits (le bypass admin ne vaut que pour les
  modules). Aucun outil d'administration n'est exposé.
- Plan et phase 2 (OAuth pour le connecteur claude.ai) :
  [plan-mcp-catalog.md](plan-mcp-catalog.md).
