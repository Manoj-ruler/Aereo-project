"""Domain exceptions and their mapping to HTTP responses.

Every error the API deliberately returns derives from :class:`AppError`. The
``detail`` of an ``AppError`` is always safe to show to a client: it never
contains stack traces or server filesystem paths.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors with a client-safe message."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    default_detail: str = "Internal server error."

    def __init__(self, detail: str | None = None, *, file_id: str | None = None) -> None:
        self.detail = detail or self.default_detail
        self.file_id = file_id
        super().__init__(self.detail)


class UnsupportedFileFormatError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "unsupported_file_format"
    default_detail = "Unsupported file format. Expected .kml or .zip."


class InvalidFileError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_file"
    default_detail = "The uploaded file is not valid."


class FileTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "file_too_large"
    default_detail = "The uploaded file exceeds the maximum allowed size."


class InvalidArchiveError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_archive"
    default_detail = "The uploaded file is not a valid ZIP archive."


class UnsafeArchiveError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "unsafe_archive"
    default_detail = "The ZIP archive was rejected because its contents are unsafe."


class ShapefileValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_shapefile"
    default_detail = "The ZIP archive does not contain a valid Shapefile."


class GeospatialReadError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "unreadable_geospatial_file"
    default_detail = "The file could not be parsed as geospatial data."


class NoFeaturesError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "no_features"
    default_detail = "The file does not contain any features."


class MissingCRSError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "missing_crs"
    default_detail = (
        "The source CRS could not be determined. Measurements cannot be calculated "
        "without knowing the coordinate reference system."
    )


class InvalidCRSError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_crs"
    default_detail = "The source CRS is invalid or not supported for measurement."


class CRSTransformError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "crs_transformation_failed"
    default_detail = (
        "The geometries could not be transformed to a projected CRS for measurement. "
        "Check that the coordinates are valid for the declared CRS "
        "(polar regions outside UTM coverage are not supported)."
    )


class ProcessingError(AppError):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "processing_failed"
    default_detail = "An unexpected error occurred while processing the file."


class FileRecordNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "file_not_found"
    default_detail = "File not found."


class FileNotProcessedError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "file_not_processed"
    default_detail = "The file has not been processed successfully."


def _error_body(detail: str, code: str, file_id: str | None = None) -> dict[str, str]:
    body = {"detail": detail, "code": code}
    if file_id is not None:
        body["file_id"] = file_id
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers so every error leaves the API as consistent JSON."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.detail, exc.code, exc.file_id),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        body = _error_body("Request validation failed.", "validation_error")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=jsonable_encoder({**body, "errors": errors}),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(AppError.default_detail, AppError.code),
        )
