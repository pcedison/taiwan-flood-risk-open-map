from fastapi import APIRouter

from app.api.routes.admin import router as admin_router
from app.api.routes.health import router as health_router
from app.api.routes.public import router as public_router
from app.api.routes.reports import router as reports_router
from app.api.routes.tiles import router as tiles_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(public_router)
api_router.include_router(reports_router)
api_router.include_router(tiles_router)
api_router.include_router(admin_router)
