"""Response models for the measurements endpoint."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import MeasurementStatus, MeasurementType


class FeatureMeasurementOut(BaseModel):
    feature_id: int = Field(description="Zero-based index of the feature within the file.")
    geometry_type: str | None
    measurement_type: MeasurementType | None = Field(
        description="`area` for polygons, `length` for lines, null otherwise."
    )
    value: float | None = Field(description="Measured value, in `unit`.")
    unit: str | None = Field(description="`m²` for area, `m` for length.")
    status: MeasurementStatus
    message: str | None = Field(description="Explanation when no value was calculated.")
    properties: dict[str, Any]


class MeasurementsResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_id": "3f0c5a0e-6f0b-4b43-9d5f-1f6f2f1f7c11",
                "crs": "EPSG:4326",
                "measurement_crs": "EPSG:32644",
                "feature_count": 3,
                "features": [
                    {
                        "feature_id": 0,
                        "geometry_type": "Polygon",
                        "measurement_type": "area",
                        "value": 1000000.0,
                        "unit": "m²",
                        "status": "MEASURED",
                        "message": None,
                        "properties": {"Name": "Parcel A"},
                    },
                    {
                        "feature_id": 1,
                        "geometry_type": "LineString",
                        "measurement_type": "length",
                        "value": 5000.0,
                        "unit": "m",
                        "status": "MEASURED",
                        "message": None,
                        "properties": {"Name": "Access road"},
                    },
                    {
                        "feature_id": 2,
                        "geometry_type": "Point",
                        "measurement_type": None,
                        "value": None,
                        "unit": None,
                        "status": "NOT_REQUIRED",
                        "message": None,
                        "properties": {"Name": "Survey marker"},
                    },
                ],
            }
        }
    )

    file_id: str
    crs: str | None = Field(description="Source CRS of the file.")
    measurement_crs: str | None = Field(
        description="Projected CRS in which the values were calculated."
    )
    feature_count: int
    features: list[FeatureMeasurementOut]
