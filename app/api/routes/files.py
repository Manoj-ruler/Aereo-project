"""File upload and file information endpoints."""

from typing import Annotated

from fastapi import APIRouter, File, Path, UploadFile, status

from app.api.dependencies import FileServiceDep
from app.db.models import FileRecord
from app.schemas.files import ErrorResponse, FeatureDetail, FeaturesResponse, FileInfo
from app.services.file_service import FileService

router = APIRouter(prefix="/api/files", tags=["files"])

FileId = Annotated[str, Path(description="ID returned by `POST /api/files/`.")]

NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Unknown ID."}}
NOT_PROCESSED = {
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": "The file exists but was not processed successfully.",
    }
}


def _file_info(record: FileRecord, service: FileService) -> FileInfo:
    return FileInfo(
        id=record.id,
        filename=record.filename,
        file_type=record.file_type,
        size_bytes=record.size_bytes,
        feature_count=record.feature_count,
        crs=record.source_crs,
        measurement_crs=record.measurement_crs,
        status=record.status,
        error_message=record.error_message,
        measurement_summary=service.get_status_counts(record.id),
        created_at=record.created_at,
        processed_at=record.processed_at,
    )


@router.post(
    "/",
    response_model=FileInfo,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and process a geospatial file",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "Unsupported format, empty file, or invalid/unsafe ZIP archive.",
        },
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "model": ErrorResponse,
            "description": "Upload exceeds `MAX_UPLOAD_SIZE_MB`.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": (
                "The file was accepted but cannot be processed: incomplete Shapefile, "
                "unparseable data, no features, or missing/invalid CRS."
            ),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
            "description": "Unexpected processing failure.",
        },
    },
)
def upload_file(
    service: FileServiceDep,
    file: Annotated[
        UploadFile,
        File(description="A `.kml` file, or a `.zip` containing exactly one Shapefile."),
    ],
) -> FileInfo:
    """Upload a `.kml` file or a `.zip` containing a Shapefile.

    The file is validated, its features are extracted, and the area of every
    polygon and the length of every line is calculated in a projected CRS
    (metres). Processing is synchronous: the response already contains the
    final status.
    """
    record = service.ingest(file.file, file.filename)
    return _file_info(record, service)


@router.get(
    "/{file_id}/",
    response_model=FileInfo,
    summary="Get information about an uploaded file",
    responses=NOT_FOUND,
)
def get_file(file_id: FileId, service: FileServiceDep) -> FileInfo:
    """Return metadata, CRS information and processing status of a file.

    Files whose processing failed are also returned, with `status: FAILED`
    and an `error_message`.
    """
    return _file_info(service.get_file(file_id), service)


@router.get(
    "/{file_id}/features/",
    response_model=FeaturesResponse,
    summary="Get the features of a file (geometry and properties)",
    responses=NOT_FOUND | NOT_PROCESSED,
)
def get_features(file_id: FileId, service: FileServiceDep) -> FeaturesResponse:
    """Return every feature with its GeoJSON-style geometry and attributes.

    Geometries are returned unmodified, in the file's source CRS (`crs`).
    """
    record, rows = service.get_features(file_id)
    return FeaturesResponse(
        file_id=record.id,
        crs=record.source_crs,
        feature_count=record.feature_count,
        features=[
            FeatureDetail(
                feature_id=row.feature_index,
                geometry_type=row.geometry_type,
                geometry=row.geometry_json,
                properties=row.properties_json,
            )
            for row in rows
        ],
    )
