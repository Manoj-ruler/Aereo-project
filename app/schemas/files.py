"""Response models for file-level endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import FileStatus, FileType


class FileInfo(BaseModel):
    """Metadata and processing outcome of an uploaded file."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "3f0c5a0e-6f0b-4b43-9d5f-1f6f2f1f7c11",
                "filename": "survey.kml",
                "file_type": "kml",
                "size_bytes": 2048,
                "feature_count": 3,
                "crs": "EPSG:4326",
                "measurement_crs": "EPSG:32644",
                "status": "COMPLETED",
                "error_message": None,
                "measurement_summary": {"MEASURED": 2, "NOT_REQUIRED": 1},
                "created_at": "2026-01-01T10:00:00Z",
                "processed_at": "2026-01-01T10:00:01Z",
            }
        }
    )

    id: str = Field(description="Server-generated UUID of the file.")
    filename: str = Field(description="Original (sanitised) name of the uploaded file.")
    file_type: FileType
    size_bytes: int = Field(description="Size of the uploaded file in bytes.")
    feature_count: int = Field(description="Number of features extracted from the file.")
    crs: str | None = Field(description="Source CRS of the file, e.g. `EPSG:4326`.")
    measurement_crs: str | None = Field(
        description="Projected CRS in which areas and lengths were calculated."
    )
    status: FileStatus
    error_message: str | None = Field(description="Why processing failed, if it did.")
    measurement_summary: dict[str, int] = Field(
        description="Number of features per measurement status."
    )
    created_at: datetime
    processed_at: datetime | None


class FeatureDetail(BaseModel):
    """A feature as read from the file."""

    feature_id: int = Field(description="Zero-based index of the feature within the file.")
    geometry_type: str | None = Field(description="e.g. `Polygon`; null if there is no geometry.")
    geometry: dict[str, Any] | None = Field(
        description="GeoJSON-style geometry in the file's source CRS."
    )
    properties: dict[str, Any] = Field(description="Attributes of the feature.")


class FeaturesResponse(BaseModel):
    file_id: str
    crs: str | None = Field(description="CRS of the returned geometries (the source CRS).")
    feature_count: int
    features: list[FeatureDetail]


class ErrorResponse(BaseModel):
    """Body returned for every handled error."""

    detail: str = Field(description="Human-readable explanation.")
    code: str = Field(description="Stable machine-readable error code.")
    file_id: str | None = Field(
        default=None,
        description="Present when the upload was stored and recorded as FAILED.",
    )
