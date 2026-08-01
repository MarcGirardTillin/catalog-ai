"""Visages mannequins du compte (face swap FASHN — « Remplacer le mannequin »).

Fichiers stockés sous IMAGING_DIR/faces/ (exclus du sweep de rétention) ;
jamais d'URL publique : envoyés à FASHN en data URI.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FaceReference(Base):
    __tablename__ = "face_reference"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    # Chemin RELATIF sous IMAGING_DIR (faces/...), jamais absolu.
    file_path: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
