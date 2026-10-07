"""Measurements endpoint."""

from fastapi import APIRouter

from app.api.dependencies import FileServiceDep
from app.api.routes.files import NOT_FOUND, NOT_PROCESSED, FileId
from app.schemas.measurements import FeatureMeasurementOut, MeasurementsResponse

router = APIRouter(prefix="/api/files", tags=["measurements"])


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    summary="Get per-feature measurements of a file",
    responses=NOT_FOUND | NOT_PROCESSED,
)
def get_measurements(file_id: FileId, service: FileServiceDep) -> MeasurementsResponse:
    """Return one entry per feature, in file order.

    * Polygon / MultiPolygon → `area` in `m²`
    * LineString / MultiLineString → `length` in `m`
    * Point / MultiPoint → `status: NOT_REQUIRED`
    * anything else → `status: UNSUPPORTED` (never an error)

    Values are calculated in `measurement_crs`, never in degrees.
    """
    record, rows = service.get_features(file_id)
    return MeasurementsResponse(
        file_id=record.id,
        crs=record.source_crs,
        measurement_crs=record.measurement_crs,
        feature_count=record.feature_count,
        features=[
            FeatureMeasurementOut(
                feature_id=row.feature_index,
                geometry_type=row.geometry_type,
                measurement_type=row.measurement_type,
                value=row.measurement_value,
                unit=row.measurement_unit,
                status=row.status,
                message=row.message,
                properties=row.properties_json,
            )
            for row in rows
        ],
    )
