from fastapi import APIRouter, HTTPException, Path, Response

from app.api.errors import error_payload
from app.domain import tiles as tile_domain

fetch_vector_tile = tile_domain.fetch_vector_tile

router = APIRouter(prefix="/v1", tags=["Tiles"])


@router.get(
    "/tiles/{layer_id}/{z}/{x}/{y}.mvt",
    include_in_schema=False,
    responses={
        200: {"content": {"application/vnd.mapbox-vector-tile": {}}},
        404: {"description": "Unknown tile layer."},
        503: {"description": "Tile database unavailable."},
    },
)
def get_vector_tile(
    layer_id: str = Path(pattern=r"^[a-z0-9][a-z0-9.-]{0,79}$"),
    z: int = Path(ge=0, le=24),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
) -> Response:
    del layer_id, z, x, y
    raise HTTPException(
        status_code=404,
        detail=error_payload("not_found", "Tile was not found.")["error"],
    )
