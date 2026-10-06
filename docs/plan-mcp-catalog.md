# Plan — serveur MCP CatalogAI (Claude & Codex)

Statut : **phases 1 et 2 implémentées** (2026-10-06 ; phase 2 = OAuth par
enregistrement dynamique, CIMD non fait — Claude se replie sur DCR) — guide de connexion : [mcp.md](mcp.md).
Écarts au plan : 12 outils (+ `catalogai_list_locations`), mode sans état
(plusieurs workers en prod), montage à la racine après les routes de l'API.
Décision Marc : phase 1 avec un jeton personnel ; l'expiration du jeton
Tillin (72 h) est acceptée pour l'instant.

## Objectif

Piloter CatalogAI depuis Claude (Claude Code, puis connecteur claude.ai) et
OpenAI Codex (CLI/IDE) : chercher des produits, lancer et suivre un
enrichissement, valider/appliquer, suivre les imports — avec **exactement les
mêmes droits que l'app web** (modules par compte, scoping `account_id`,
crédits, bypass admin limité aux modules).

## Choix techniques

| Sujet | Choix | Pourquoi |
|---|---|---|
| Transport | Streamable HTTP (spec MCP 2026-07-28) | seul transport distant recommandé ; SSE déprécié |
| Hébergement | monté dans l'app FastAPI existante, sur `/mcp` | même process, mêmes services, même DB, un seul déploiement (`api-catalog.tillin.fr/mcp`) |
| SDK | FastMCP 4.x, **version figée** dans `pyproject.toml` | négocie les versions de protocole, auth complète (JWT/PAT, OAuth plus tard) |
| Outils | écrits à la main (pas `from_fastapi`/`fastapi-mcp`) | les agents marchent mieux avec peu d'outils orientés tâches ; `fastapi-mcp` n'est plus maintenu et notre auth est par cookie |
| Auth phase 1 | jeton d'API personnel (bearer) | suffit pour Claude Code et Codex ; OAuth 2.1 seulement en phase 2 (connecteur claude.ai) |

Points d'intégration repérés :
- `backend/app/main.py` : `lifespan` existant (ping DB, purge staging) à
  **combiner** avec celui de FastMCP (`mcp.http_app(path="/")` monté sur
  `/mcp`), sinon le gestionnaire de sessions ne démarre pas.
- `backend/app/api/deps.py` : `get_current_user` lit **uniquement** le cookie
  de session → les outils n'utilisent pas les `Depends` ; un helper commun
  résout l'utilisateur depuis le bearer.
- Routes synchrones (`def`) : les outils (async) appellent la **couche de
  service** via `anyio.to_thread.run_sync`, jamais les fonctions de route.
- `BackgroundTasks` n'existe pas côté MCP : lancer les runners
  (`run_job`, `run_import`) dans un thread, comme le fait le worker.
- CORS : `/mcp` ne porte jamais de cookie (bearer uniquement).

## Phase 1 — jeton personnel + outils (≈ 3-4 jours)

### 1. Jetons d'API
- Table `api_token` (migration Alembic) : `id`, `user_id`, `account_id`,
  `name`, `token_hash` (SHA-256), `prefix` (8 car. affichés), `scopes`
  (JSON), `created_at`, `last_used_at`, `expires_at` (défaut 90 j),
  `revoked_at`.
- Format : `cat_<prefix>_<secret>` (secret 32 octets urlsafe) ; seul le
  hachage est stocké, le jeton est affiché **une seule fois**.
- Routes `/settings/api-tokens` (GET liste, POST créer, DELETE révoquer),
  scopées sur l'utilisateur courant ; UI dans Réglages (onglet « Accès
  API / MCP ») avec la commande à copier pour Claude Code et le bloc
  `config.toml` pour Codex.
- `TokenVerifier` FastMCP : hachage → jeton actif, non expiré, non révoqué →
  `User` actif → mêmes contrôles que `get_current_user` ; met à jour
  `last_used_at`. 401 avec `WWW-Authenticate` sinon (prépare la phase 2).

### 2. Garde commune `mcp_guard`
Un seul point d'entrée par outil :
`user, account_id = mcp_guard(ctx, feature="feature_enrich", credits=n)`
- `resolve_account_id(db, user)` (scoping) ;
- même logique que `require_feature` (flags du compte ; **bypass admin sur
  les modules uniquement**) ;
- `require_credits` avant tout lancement facturable (pas de bypass admin) ;
- Xano interactif via `xano_client_for_user` (token de l'utilisateur), jamais
  l'identité de service ; jobs de fond inchangés (`launcher_user_id`).
- Jeton Tillin expiré (72 h) → erreur explicite : « Session Tillin expirée —
  reconnectez-vous sur catalog.tillin.fr » (accepté par Marc en phase 1).
- Aucun outil admin (`/admin/*`, grille tarifaire, coefficient,
  `ADMIN_ONLY_SETTINGS`).

### 3. Outils (préfixe `catalogai_`, annotations MCP sur chacun)

| Outil | Service réutilisé | Garde | Annotation |
|---|---|---|---|
| `get_account_overview` — modules actifs, solde de crédits, état de la connexion Tillin | stats/credits/settings | scoping | lecture |
| `search_products` — texte, marque, catégorie, page ; `response_format` concis/détaillé | `XanoClient.list_products` | scoping, Xano utilisateur | lecture |
| `get_product` — fiche, variantes, images (concis par défaut) | `get_product` | scoping | lecture |
| `start_enrichment` — ids + options ; renvoie `job_id` et coût estimé | `create_job` | `feature_enrich` + crédits | écriture |
| `get_job_status` — compteurs, items en échec | `get_job`, `job_counts` | `feature_enrich` | lecture |
| `list_items_to_review` — items à vérifier avec le diff proposé | items du job | `feature_enrich` | lecture |
| `review_item` — approuver / écarter / relancer | services items | `feature_enrich` | écriture |
| `apply_item` — pousse vers Tillin ; **aperçu sans `confirm: true`** | destination Xano | `feature_enrich` | destructif |
| `list_imports` — filtres statut, suivi produits, fournisseur | `list_imports` | `feature_import` | lecture |
| `get_import_review` — produits, alertes, aperçu des lignes CSV paginé | imports | `feature_import` | lecture |
| `transfer_import` — **aperçu sans `confirm: true`**, puis transfert + rapprochement | transfert | `feature_import` | destructif, non idempotent |

Hors phase 1 : `create_import` (fichier en base64 peu pratique via MCP), studio
(`generate_product_visual`), suppressions et réglages.

Règles de conception : traitements longs = renvoyer un identifiant tout de
suite puis interroger (Codex coupe un appel à 60 s) ; réponses paginées et
tronquées (< 25 000 tokens) ; erreurs qui disent quoi faire ; journal par appel
(utilisateur, compte, outil, durée, résultat — sans données sensibles) ;
limite de débit par jeton.

### 4. Tests (avant le code des outils)
- 401 sans jeton / jeton révoqué / expiré.
- 403 module désactivé (par outil), bypass admin sur les modules mais **pas**
  sur les crédits.
- Scoping : un jeton du compte A ne voit ni ne modifie rien du compte B.
- Crédits insuffisants → refus avant toute écriture.
- `apply_item` / `transfer_import` sans `confirm` → aperçu, aucun appel Xano.
- Client MCP en mémoire de FastMCP pour les tests de bout en bout des outils.

### 5. Déploiement et docs
- Caddy : rien à changer si `/mcp` passe par le backend existant (à vérifier
  dans la config) ; timeouts adaptés au streaming.
- `docs/mcp.md` : connexion Claude Code
  (`claude mcp add --transport http catalogai https://api-catalog.tillin.fr/mcp --header "Authorization: Bearer $CATALOGAI_TOKEN"`)
  et Codex :
  ```toml
  [mcp_servers.catalogai]
  url = "https://api-catalog.tillin.fr/mcp"
  bearer_token_env_var = "CATALOGAI_TOKEN"
  default_tools_approval_mode = "writes"
  ```
- `.claude/DECISIONS.md` : SDK figé, PAT, garde commune.
- Validation live : Claude Code + Codex sur la boutique de test (compte 8),
  scénario recherche → enrichissement → suivi → application.

## Phase 2 — OAuth 2.1 pour le connecteur claude.ai (plus tard)

- CatalogAI serveur d'autorisation (FastMCP `OAuthProvider`) : page de
  consentement = login existant ; métadonnées RFC 8414 + Protected Resource
  Metadata (RFC 9728) ; PKCE S256 ; Client ID Metadata Documents (CIMD) avec
  DCR en repli ; callbacks `https://claude.ai/api/mcp/auth_callback` et
  loopback `http://localhost/callback` (tout port).
- Jeton PAT conservé en parallèle (MultiAuth). Scopes : `catalog:read`,
  `enrich:write`, `import:write`, `studio:write`.
- Annotations `title` + `readOnlyHint`/`destructiveHint` obligatoires pour
  une publication dans l'annuaire des connecteurs.
- À régler alors : renouvellement du jeton Tillin sans passage par l'app web.

## Points ouverts
- Compatibilité de FastMCP 4.x avec les versions FastAPI/Starlette figées dans
  `uv.lock` (à vérifier au premier jour).
- Robustesse de l'OAuth MCP dans Codex (tickets ouverts) — le bearer suffit
  en phase 1.
