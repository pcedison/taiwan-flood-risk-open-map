from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.errors import error_payload
from app.api.router import api_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_title,
        version=settings.app_version,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    application.include_router(api_router)

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: object, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=error_payload(
                "bad_request",
                "Request validation failed.",
                {"errors": _json_safe(exc.errors())},
            ),
        )

    @application.exception_handler(HTTPException)
    async def http_exception_handler(_request: object, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and {"code", "message"}.issubset(exc.detail):
            content = {"error": exc.detail}
        else:
            content = error_payload(str(exc.status_code), str(exc.detail))
        return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)

    return application


def _json_safe(value: object) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return str(value)


app = create_app()
