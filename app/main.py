"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, Response

from app.api.routes import files, measurements
from app.core.config import BYTES_PER_MB, Settings, get_settings
from app.core.exceptions import FileTooLargeError, register_exception_handlers
from app.core.logging import configure_logging
from app.db.database import create_db_engine, create_session_factory, init_db

logger = logging.getLogger(__name__)

# Multipart framing (boundaries, part headers) adds a little to the body size.
MULTIPART_OVERHEAD_BYTES = BYTES_PER_MB

API_DESCRIPTION = """
Upload a **KML** file or a **zipped Shapefile** and get per-feature measurements.

* Polygons → area in m², lines → length in m, points → no measurement.
* Geographic coordinates (e.g. EPSG:4326) are never measured in degrees: features
  are first transformed to a projected CRS (the local UTM zone).
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass their own ``settings``."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = create_db_engine(settings.database_url)
    init_db(engine)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info("Application started: env=%s", settings.app_env)
        yield
        engine.dispose()

    app = FastAPI(
        title="Geospatial File Measurement API",
        version="1.0.0",
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.session_factory = create_session_factory(engine)

    @app.middleware("http")
    async def reject_oversized_requests(request: Request, call_next) -> Response:
        """Refuse clearly oversized uploads before the body is read.

        The authoritative limit is enforced while streaming the file to disk;
        this is an early exit for clients that declare a Content-Length.
        """
        declared = request.headers.get("content-length", "")
        limit = settings.max_upload_size_bytes + MULTIPART_OVERHEAD_BYTES
        if declared.isdigit() and int(declared) > limit:
            return JSONResponse(
                status_code=FileTooLargeError.status_code,
                content={
                    "detail": "The uploaded file exceeds the maximum allowed size of "
                    f"{settings.max_upload_size_mb} MB.",
                    "code": FileTooLargeError.code,
                },
            )
        return await call_next(request)

    register_exception_handlers(app)
    app.include_router(files.router)
    app.include_router(measurements.router)

    @app.get("/health", tags=["health"], summary="Liveness check")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False, status_code=status.HTTP_200_OK)
    def root() -> dict[str, str]:
        return {"name": app.title, "docs": "/docs", "openapi": "/openapi.json"}

    return app


app = create_app()
