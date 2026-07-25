"""Claude (Anthropic SDK) client — copy generation for Leg A.

Uses the official `anthropic` SDK with structured outputs
(`output_config.format`) so the response is guaranteed-parseable JSON. The
model defaults to settings.AI_DEFAULT_MODEL (`claude-sonnet-5` per plan);
Sonnet 5 rejects sampling parameters, so none are sent. An `http_client` is
injectable for tests (httpx.MockTransport) — no real API calls in the suite.
"""

import json
from typing import Any

import anthropic
import httpx
from pydantic import BaseModel, ValidationError

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.core.config import settings

MAX_TOKENS = 2048

# Le SDK Anthropic rejoue nativement 429/5xx/timeouts avec backoff exponentiel
# en honorant Retry-After ; 5 tentatives absorbent les pics de rate-limit des
# jobs batch sans code maison (défaut SDK : 2).
MAX_RETRIES = 5

COPY_SCHEMA = {
    "type": "object",
    "properties": {
        "description_fr": {"type": "string"},
        # Version riche (HTML léger) écrite dans `description_html` côté
        # Tillin — décision Marc 2026-07-18 (style/emojis perdus en brut).
        "description_html_fr": {"type": "string"},
        "meta_description_fr": {"type": "string"},
    },
    "required": ["description_fr", "description_html_fr", "meta_description_fr"],
    "additionalProperties": False,
}

# Schéma de l'étage « sélection » de la résolution de page source (rapport
# deep-research 2026-07-18 : choisir parmi les candidats ENSEMBLE bat le
# matching par paires) : index du candidat, -1 = aucun ne correspond.
SELECT_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["choice", "reason"],
    "additionalProperties": False,
}

DEFAULT_META_MAX_LENGTH = 160


def _system_prompt(meta_max_length: int) -> str:
    return (
        "Tu rédiges des fiches produit pour une boutique de mode multimarques. "
        "À partir du contexte produit fourni, écris une description FR engageante "
        "et fidèle (pas d'invention de caractéristiques) et une meta description "
        f"FR de {meta_max_length} caractères maximum. Intègre naturellement les "
        "détails techniques fournis quand ils existent — caractéristiques "
        "(source_features), composition, pays de fabrication, entretien — sans "
        "jamais compléter un détail absent du contexte.\n"
        "Fournis DEUX versions de la description : description_fr en texte "
        "brut (paragraphes séparés par une ligne vide), et description_html_fr "
        "en HTML léger STRICTEMENT limité aux balises <p>, <br>, <ul>, <li>, "
        "<strong> et <em> — même contenu, mis en forme (paragraphes, liste "
        "des caractéristiques), quelques emojis sobres autorisés si le ton "
        "s'y prête. Jamais de <script>, de style inline ni d'attributs."
    )


class ClaudeUsage(BaseModel):
    """Token usage of one Claude call (feeds the usage metering brick, M1)."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class CopyResult(BaseModel):
    description_fr: str
    meta_description_fr: str
    # HTML léger (balises p/br/ul/li/strong/em) — None sur les fakes/legacy.
    description_html_fr: str | None = None
    # Filled by the client from the API response; None on fakes/legacy paths.
    usage: ClaudeUsage | None = None


class CandidateChoice(BaseModel):
    """Résultat de l'étage de sélection : index choisi (-1 = aucun)."""

    choice: int
    reason: str = ""
    usage: ClaudeUsage | None = None


class ClaudeClient:
    def __init__(
        self,
        api_key: str,
        *,
        model: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise NotConfiguredError("claude")
        self._model = model or settings.AI_DEFAULT_MODEL
        self._client = anthropic.Anthropic(
            api_key=api_key, http_client=http_client, max_retries=MAX_RETRIES
        )

    @classmethod
    def from_settings(
        cls, *, http_client: httpx.Client | None = None
    ) -> "ClaudeClient":
        return cls(settings.ANTHROPIC_API_KEY, http_client=http_client)

    def generate_copy(
        self,
        product_ctx: dict[str, Any],
        *,
        editorial_instructions: str = "",
        model: str | None = None,
        meta_max_length: int = DEFAULT_META_MAX_LENGTH,
    ) -> CopyResult:
        """Generate FR description + meta description for one product."""
        user_content = "Contexte produit (JSON) :\n" + json.dumps(
            product_ctx, ensure_ascii=False, sort_keys=True
        )
        if editorial_instructions:
            user_content += f"\n\nConsignes éditoriales :\n{editorial_instructions}"

        try:
            response = self._client.messages.create(
                model=model or self._model,
                max_tokens=MAX_TOKENS,
                system=_system_prompt(meta_max_length),
                output_config={
                    "format": {"type": "json_schema", "schema": COPY_SCHEMA}
                },
                messages=[{"role": "user", "content": user_content}],
            )
        except anthropic.APIConnectionError as exc:
            raise ExternalServiceError("claude", "Claude is unreachable") from exc
        except anthropic.APIStatusError as exc:
            raise ExternalServiceError(
                "claude",
                "Claude returned an error response",
                detail={"upstream_status": exc.status_code},
            ) from exc

        if response.stop_reason == "refusal":
            raise ExternalServiceError("claude", "Claude refused the request")

        text = next(
            (block.text for block in response.content if block.type == "text"), ""
        )
        try:
            result = CopyResult.model_validate_json(text)
        except ValidationError as exc:
            raise ExternalServiceError(
                "claude", "Claude returned an unparseable copy payload"
            ) from exc
        result.usage = ClaudeUsage(
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return result

    def select_candidate(
        self,
        product_ctx: dict[str, Any],
        candidates: list[dict[str, Any]],
        *,
        model: str | None = None,
    ) -> CandidateChoice:
        """Choisit LA page candidate correspondant au produit (ou aucune).

        Étage « selecting » de la résolution (rapport deep-research
        2026-07-18) : présenter tous les candidats ENSEMBLE — coloris frères
        compris — avec l'option « aucun » bat le scoring par paires. Le
        prompt exige la correspondance exacte du coloris.
        """
        user_content = (
            "Produit du catalogue (JSON) :\n"
            + json.dumps(product_ctx, ensure_ascii=False, sort_keys=True)
            + "\n\nPages candidates (JSON, indexées) :\n"
            + json.dumps(candidates, ensure_ascii=False)
        )
        system = (
            "Tu identifies la page produit OFFICIELLE correspondant EXACTEMENT "
            "au produit du catalogue (même modèle ET même coloris — un coloris "
            "différent n'est PAS le bon produit, même si la référence "
            "correspond). Réponds par l'index du candidat correspondant, ou "
            "-1 si aucun ne correspond avec certitude. Justifie en une phrase."
        )
        try:
            response = self._client.messages.create(
                model=model or self._model,
                max_tokens=512,
                system=system,
                output_config={
                    "format": {"type": "json_schema", "schema": SELECT_SCHEMA}
                },
                messages=[{"role": "user", "content": user_content}],
            )
        except anthropic.APIConnectionError as exc:
            raise ExternalServiceError("claude", "Claude is unreachable") from exc
        except anthropic.APIStatusError as exc:
            raise ExternalServiceError(
                "claude",
                "Claude returned an error response",
                detail={"upstream_status": exc.status_code},
            ) from exc
        if response.stop_reason == "refusal":
            raise ExternalServiceError("claude", "Claude refused the request")
        text = next(
            (block.text for block in response.content if block.type == "text"), ""
        )
        try:
            result = CandidateChoice.model_validate_json(text)
        except ValidationError as exc:
            raise ExternalServiceError(
                "claude", "Claude returned an unparseable selection payload"
            ) from exc
        result.usage = ClaudeUsage(
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return result
