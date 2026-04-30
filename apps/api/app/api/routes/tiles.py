from fastapi import APIRouter, HTTPException, Path, Response

from app.api.errors import error_payload
from app.core.config import get_settings
from app.domain.tiles import TileLayerNotFound, TileRepositoryUnavailable, fetch_vector_tile

router = APIRouter(prefix="/v1", tags=["Tiles"])


@router.get(
    "/tiles/{layer_id}/{z}/{x}/{y}.mvt",
    responses={
        200: {"content": {"application/vnd.mapbox-vector-tile": {}}},
        404: {"description": "Unknown tile layer."},
        503: {"description": "Tile database unavailable."},
    },
)
async def get_vector_tile(
    layer_id: str = Path(pattern=r"^[a-z0-9][a-z0-9.-]{0,79}$"),
    z: int = Path(ge=0, le=24),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
) -> Response:
    if x >= 2**z or y >= 2**z:
        raise HTTPException(
            status_code=404,
            detail=error_payload("not_found", "Tile coordinate is outside the zoom bounds.")[
                "error"
            ],
        )

    try:
        tile = fetch_vector_tile(
            database_url=get_settings().database_url,
            layer_id=layer_id,
            z=z,
            x=x,
            y=y,
        )
    except TileLayerNotFound:
        raise HTTPException(
            status_code=404,
            detail=error_payload("not_found", f"Layer '{layer_id}' was not found.")["error"],
        ) from None
    except TileRepositoryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "tiles_unavailable",
                "Tile storage is unavailable.",
                {"reason": str(exc)},
            )["error"],
        ) from exc

    return Response(
        content=tile,
        media_type="application/vnd.mapbox-vector-tile",
        headers={
            "Cache-Control": "public, max-age=60",
            "X-Tile-Layer": layer_id,
        },
    )
