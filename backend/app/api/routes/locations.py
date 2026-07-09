"""Location routes — the Tillin boutiques an import can be transferred to.

Third-party locations (marketplaces synced from elsewhere) are excluded by
the client: products must only be imported into locations Tillin owns.
"""

from fastapi import APIRouter, Depends

from app.api.deps import XanoDep, get_current_user
from app.api.schemas.locations import LocationPublic

router = APIRouter(
    prefix="/locations",
    tags=["locations"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[LocationPublic])
def list_locations(xano: XanoDep) -> list[LocationPublic]:
    """Return the Tillin-owned locations (no third-party), sorted by title."""
    return [
        LocationPublic(id=location["id"], title=location["title"])
        for location in xano.list_locations()
    ]
