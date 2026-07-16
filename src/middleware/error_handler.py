import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("analytics.errors")

class CatchAllMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request:Request, call_next):
        """Last-resort safety net: never leak a raw stack trace to the client."""
        try:
            return await call_next(request)
        except Exception:
            request_id = getattr(request.state, "request_id","unkown")
            logger.exception(
                "unhandled exception",
                extra={"request_id": request_id, "path": request.url.path}
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error_code": "INTERNAL_ERROR",
                    "message" : "An unexpected error occurred. Please try again later.",
                    "request_id": request_id,
                },
            )

def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code = 422,
            content = {
                "error_code": "VALIDATION_ERROR",
                "message": "Request payload failed validation",
                "details": exc.errors(),
                "request_id": getattr(request.state, "request_id", "unknown"),

            },
        )