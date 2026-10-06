"""usage_price : grille de coûts fournisseurs commune à la plateforme.

`usage_price.account_id` devient nullable : une ligne `account_id IS NULL`
vaut pour tous les comptes, une ligne de compte devient une EXCEPTION de ce
compte. Résolution : compte exact → compte modèle NULL → commun exact →
commun modèle NULL → pas de prix.

Upgrade : les copies par compte sont fusionnées (prix majoritaire par
(provider, model, metric) → ligne commune ; les lignes de compte identiques
sont supprimées, celles qui diffèrent restent en exception). La fusion vérifie
compte par compte que la résolution est INCHANGÉE et garde en exception toute
ligne nécessaire pour cela. Puis insertion des prix communs Claude Sonnet 5.5
(2 $/10 $ par million, décision Marc 2026-10-06).

Downgrade : la grille commune est recopiée sur chaque compte (sans écraser
ses lignes, en préservant la cascade), puis account_id repasse NOT NULL.

Les fonctions de planification sont en Python pur (testées dans
tests/test_migration_common_usage_price.py) ; elles ne dépendent pas du code
applicatif pour rester rejouables quoi qu'il devienne.

Revision ID: 0027_common_usage_price
Revises: 0026_face_reference
Create Date: 2026-10-06 00:00:00.000000
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0027_common_usage_price"
down_revision: str | None = "0026_face_reference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

Key = tuple[str, str | None, str]  # (provider, model|None, metric)

# Prix Anthropic de Sonnet 5.5 répercutés tels quels (€/token, comme la ligne
# claude-sonnet-5 existante qui stocke 3 $/15 $ en 0.000003/0.000015).
SONNET_55_MODEL = "claude-sonnet-5-5"
SONNET_55_PRICES = {
    "input_tokens": Decimal("0.000002"),
    "output_tokens": Decimal("0.00001"),
}
SONNET_5_MODEL = "claude-sonnet-5"


@dataclass(frozen=True)
class PriceRow:
    id: int
    account_id: int | None
    provider: str
    model: str | None
    metric: str
    unit_price: Decimal
    currency: str
    updated_at: datetime | None = None

    @property
    def key(self) -> Key:
        return (self.provider, self.model, self.metric)


@dataclass(frozen=True)
class NewPrice:
    account_id: int | None
    provider: str
    model: str | None
    metric: str
    unit_price: Decimal
    currency: str


def _pick(table: dict[Key, Decimal], key: Key) -> Decimal | None:
    exact = table.get(key)
    if exact is not None:
        return exact
    return table.get((key[0], None, key[2]))


def _ts(value: datetime | None) -> float:
    return value.timestamp() if value is not None else float("-inf")


def plan_common_grid(rows: Iterable[PriceRow]) -> tuple[list[NewPrice], set[int]]:
    """Fusion des copies par compte → (lignes communes à créer, ids à supprimer).

    Seules les lignes de COMPTE sont considérées (une ligne commune déjà
    présente n'existe pas avant cette migration). Par compte et par clé, la
    ligne effective est la plus récente (id max) ; les doublons morts sont
    supprimés. Prix commun d'une clé = valeur (prix, devise) majoritaire parmi
    les comptes ; égalité → la plus récente `updated_at`.
    """
    effective: dict[tuple[int, Key], PriceRow] = {}
    to_delete: set[int] = set()
    for row in sorted(rows, key=lambda r: r.id):
        if row.account_id is None:
            continue
        slot = (row.account_id, row.key)
        previous = effective.get(slot)
        if previous is not None:
            to_delete.add(previous.id)  # dead duplicate (lookup kept the last)
        effective[slot] = row

    by_key: dict[Key, list[PriceRow]] = {}
    for row in effective.values():
        by_key.setdefault(row.key, []).append(row)

    common: dict[Key, tuple[Decimal, str]] = {}
    for key, key_rows in by_key.items():
        counts: Counter[tuple[Decimal, str]] = Counter(
            (r.unit_price, r.currency) for r in key_rows
        )
        latest: dict[tuple[Decimal, str], tuple[float, int]] = {}
        for r in key_rows:
            value = (r.unit_price, r.currency)
            latest[value] = max(
                latest.get(value, (float("-inf"), -1)), (_ts(r.updated_at), r.id)
            )
        common[key] = max(counts, key=lambda v: (counts[v], latest[v]))

    common_table = {key: value[0] for key, value in common.items()}
    account_rows: dict[int, dict[Key, PriceRow]] = {}
    for (account_id, key), row in effective.items():
        account_rows.setdefault(account_id, {})[key] = row

    # Clés témoins : toutes les clés connues + le repli (provider, NULL,
    # metric), qui représente aussi tout modèle absent de la grille.
    probe_keys: set[Key] = set(by_key)
    probe_keys |= {(k[0], None, k[2]) for k in by_key}

    for own in account_rows.values():
        removable = {
            key
            for key, row in own.items()
            if (row.unit_price, row.currency) == common[key]
        }
        before_table = {key: row.unit_price for key, row in own.items()}
        changed = True
        while changed:
            changed = False
            kept_table = {
                key: price
                for key, price in before_table.items()
                if key not in removable
            }
            for probe in probe_keys:
                before = _pick(before_table, probe)
                if before is None:
                    continue  # no price before: the account gains the common one
                after = _pick(kept_table, probe)
                if after is None:
                    after = _pick(common_table, probe)
                if after == before:
                    continue
                source = probe if probe in before_table else (probe[0], None, probe[2])
                if source in removable:
                    removable.discard(source)
                    changed = True
        to_delete |= {own[key].id for key in removable}

    new_rows = [
        NewPrice(None, key[0], key[1], key[2], value[0], value[1])
        for key, value in sorted(
            common.items(), key=lambda i: (i[0][0], i[0][1] or "", i[0][2])
        )
    ]
    return new_rows, to_delete


def plan_sonnet_55(rows: Iterable[PriceRow]) -> list[NewPrice]:
    """Prix communs claude/claude-sonnet-5-5 absents de la grille commune.
    Devise : celle de la ligne claude-sonnet-5 (commune d'abord), EUR sinon."""
    rows = list(rows)
    common_keys = {r.key for r in rows if r.account_id is None}
    currency = "EUR"
    sonnet5 = sorted(
        (r for r in rows if r.provider == "claude" and r.model == SONNET_5_MODEL),
        key=lambda r: (r.account_id is not None, r.id),
    )
    if sonnet5:
        currency = sonnet5[0].currency
    return [
        NewPrice(None, "claude", SONNET_55_MODEL, metric, price, currency)
        for metric, price in SONNET_55_PRICES.items()
        if ("claude", SONNET_55_MODEL, metric) not in common_keys
    ]


def plan_account_copies(
    rows: Iterable[PriceRow], account_ids: Iterable[int]
) -> list[NewPrice]:
    """Downgrade : recopie de la grille commune sur chaque compte.

    Une clé déjà présente sur le compte n'est pas copiée (l'exception gagne).
    Une ligne commune « modèle exact » n'est pas copiée si le compte a sa
    propre ligne modèle NULL : dans la cascade, l'exception NULL du compte
    passait avant le commun exact — la recopier inverserait la priorité.
    """
    rows = list(rows)
    common = [r for r in rows if r.account_id is None]
    own_keys: dict[int, set[Key]] = {}
    for r in rows:
        if r.account_id is not None:
            own_keys.setdefault(r.account_id, set()).add(r.key)
    copies: list[NewPrice] = []
    for account_id in account_ids:
        keys = own_keys.get(account_id, set())
        for c in common:
            if c.key in keys:
                continue
            if c.model is not None and (c.provider, None, c.metric) in keys:
                continue
            copies.append(
                NewPrice(
                    account_id, c.provider, c.model, c.metric, c.unit_price, c.currency
                )
            )
    return copies


_usage_price = sa.table(
    "usage_price",
    sa.column("id", sa.Integer()),
    sa.column("account_id", sa.Integer()),
    sa.column("provider", sa.String()),
    sa.column("model", sa.String()),
    sa.column("metric", sa.String()),
    sa.column("unit_price", sa.Numeric(16, 10)),
    sa.column("currency", sa.String()),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def _load_rows(bind: sa.engine.Connection) -> list[PriceRow]:
    t = _usage_price
    result = bind.execute(
        sa.select(
            t.c.id,
            t.c.account_id,
            t.c.provider,
            t.c.model,
            t.c.metric,
            t.c.unit_price,
            t.c.currency,
            t.c.updated_at,
        ).order_by(t.c.id)
    )
    return [
        PriceRow(
            id=row.id,
            account_id=row.account_id,
            provider=row.provider,
            model=row.model,
            metric=row.metric,
            unit_price=Decimal(str(row.unit_price)),
            currency=row.currency,
            updated_at=row.updated_at,
        )
        for row in result
    ]


def _insert(bind: sa.engine.Connection, prices: list[NewPrice]) -> None:
    if not prices:
        return
    bind.execute(
        _usage_price.insert(),
        [
            {
                "account_id": p.account_id,
                "provider": p.provider,
                "model": p.model,
                "metric": p.metric,
                "unit_price": p.unit_price,
                "currency": p.currency,
            }
            for p in prices
        ],
    )


def upgrade() -> None:
    with op.batch_alter_table("usage_price") as batch:
        batch.alter_column("account_id", existing_type=sa.Integer(), nullable=True)

    bind = op.get_bind()
    common, delete_ids = plan_common_grid(_load_rows(bind))
    _insert(bind, common)
    if delete_ids:
        bind.execute(
            _usage_price.delete().where(_usage_price.c.id.in_(sorted(delete_ids)))
        )
    _insert(bind, plan_sonnet_55(_load_rows(bind)))


def downgrade() -> None:
    bind = op.get_bind()
    account_ids = [
        row[0] for row in bind.execute(sa.text("SELECT id FROM account ORDER BY id"))
    ]
    _insert(bind, plan_account_copies(_load_rows(bind), account_ids))
    bind.execute(_usage_price.delete().where(_usage_price.c.account_id.is_(None)))
    with op.batch_alter_table("usage_price") as batch:
        batch.alter_column("account_id", existing_type=sa.Integer(), nullable=False)
