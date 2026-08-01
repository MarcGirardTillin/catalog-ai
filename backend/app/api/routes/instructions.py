"""Editorial instruction library routes (account-scoped CRUD).

Templates are referenced by id at job creation (``config.instruction_id``) and
snapshotted into the job's config — editing or deleting one here never changes
past jobs.
"""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.api.exceptions import AppException
from app.api.schemas.instructions import (
    InstructionCreate,
    InstructionOrder,
    InstructionPublic,
    InstructionUpdate,
)
from app.api.services.accounts import resolve_account_id
from app.models import InstructionTemplate

router = APIRouter(prefix="/instructions", tags=["instructions"])


def _get_owned(
    db: Session, *, account_id: int, instruction_id: int
) -> InstructionTemplate:
    instruction = db.get(InstructionTemplate, instruction_id)
    if instruction is None or instruction.account_id != account_id:
        raise AppException(
            status_code=404, code="not_found", message="Instruction not found"
        )
    return instruction


def _to_public(instruction: InstructionTemplate) -> InstructionPublic:
    return InstructionPublic(
        id=instruction.id,
        name=instruction.name,
        content=instruction.content,
        categories=list(instruction.categories_json or []),
        created_at=instruction.created_at,
        updated_at=instruction.updated_at,
    )


@router.get("", response_model=list[InstructionPublic])
def list_instructions(
    db: SessionDep, current_user: CurrentUserDep
) -> list[InstructionPublic]:
    """The account's instruction library, user order first then by name."""
    account_id = resolve_account_id(db, current_user)
    rows = (
        db.execute(
            select(InstructionTemplate)
            .where(InstructionTemplate.account_id == account_id)
            .order_by(
                InstructionTemplate.position.is_(None),
                InstructionTemplate.position,
                InstructionTemplate.name,
            )
        )
        .scalars()
        .all()
    )
    return [_to_public(row) for row in rows]


@router.put("/order", response_model=list[InstructionPublic])
def reorder_instructions(
    payload: InstructionOrder, db: SessionDep, current_user: CurrentUserDep
) -> list[InstructionPublic]:
    """Fixe l'ordre d'affichage (liste d'ids, du premier au dernier).

    Les instructions du compte absentes de la liste passent après (position
    NULL → tri par nom).
    """
    account_id = resolve_account_id(db, current_user)
    for index, instruction_id in enumerate(payload.ids):
        instruction = _get_owned(
            db, account_id=account_id, instruction_id=instruction_id
        )
        instruction.position = index
    db.commit()
    return list_instructions(db, current_user)


@router.post("", response_model=InstructionPublic, status_code=201)
def create_instruction(
    payload: InstructionCreate, db: SessionDep, current_user: CurrentUserDep
) -> InstructionPublic:
    account_id = resolve_account_id(db, current_user)
    instruction = InstructionTemplate(
        account_id=account_id,
        name=payload.name,
        content=payload.content,
        categories_json=payload.categories or None,
    )
    db.add(instruction)
    db.commit()
    db.refresh(instruction)
    return _to_public(instruction)


@router.put("/{instruction_id}", response_model=InstructionPublic)
def update_instruction(
    instruction_id: int,
    payload: InstructionUpdate,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> InstructionPublic:
    account_id = resolve_account_id(db, current_user)
    instruction = _get_owned(db, account_id=account_id, instruction_id=instruction_id)
    instruction.name = payload.name
    instruction.content = payload.content
    instruction.categories_json = payload.categories or None
    db.commit()
    db.refresh(instruction)
    return _to_public(instruction)


@router.delete("/{instruction_id}", status_code=204)
def delete_instruction(
    instruction_id: int, db: SessionDep, current_user: CurrentUserDep
) -> None:
    account_id = resolve_account_id(db, current_user)
    instruction = _get_owned(db, account_id=account_id, instruction_id=instruction_id)
    db.delete(instruction)
    db.commit()
