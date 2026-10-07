"""Area and length calculation for individual geometries."""

import logging
import math
from dataclasses import dataclass

import geopandas as gpd
import shapely
from shapely.errors import ShapelyError
from shapely.geometry.base import BaseGeometry

from app.core.enums import MeasurementStatus, MeasurementType
from app.services.crs_service import MeasurementPlan, to_measurement_crs

logger = logging.getLogger(__name__)

AREA_GEOMETRY_TYPES = frozenset({"Polygon", "MultiPolygon"})
LENGTH_GEOMETRY_TYPES = frozenset({"LineString", "MultiLineString", "LinearRing"})
POINT_GEOMETRY_TYPES = frozenset({"Point", "MultiPoint"})

UNIT_METRE = "m"
UNIT_SQUARE_METRE = "m²"


@dataclass(frozen=True)
class Measurement:
    """Outcome of measuring one feature."""

    status: MeasurementStatus
    measurement_type: MeasurementType | None = None
    value: float | None = None
    unit: str | None = None
    message: str | None = None


def measure_features(geometries: gpd.GeoSeries, plan: MeasurementPlan) -> list[Measurement]:
    """Measure every geometry, in file order.

    The whole series is reprojected once; each feature is then measured
    independently so a single bad geometry cannot affect the others.
    """
    if plan.measurement_crs is None:
        # No feature has coordinates, so there is nothing to project or measure.
        return [measure_geometry(None) for _ in range(len(geometries))]
    projected = to_measurement_crs(geometries, plan)
    return [_measure_safely(geometry, plan.unit_to_metre) for geometry in projected]


def measure_geometry(geometry: BaseGeometry | None, unit_to_metre: float = 1.0) -> Measurement:
    """Measure one geometry whose coordinates are in a *projected* CRS.

    ``unit_to_metre`` converts the CRS's linear unit (e.g. US survey feet) so
    that results are always metres / square metres.
    """
    if geometry is None or geometry.is_empty:
        return Measurement(MeasurementStatus.NO_GEOMETRY, message="Feature has no geometry.")

    geometry_type = geometry.geom_type
    if geometry_type in POINT_GEOMETRY_TYPES:
        return Measurement(MeasurementStatus.NOT_REQUIRED)
    if geometry_type in LENGTH_GEOMETRY_TYPES:
        return _measured(MeasurementType.LENGTH, geometry.length * unit_to_metre, UNIT_METRE)
    if geometry_type in AREA_GEOMETRY_TYPES:
        if not geometry.is_valid:
            # A self-intersecting ring yields a meaningless area; report it
            # instead of silently repairing the user's geometry.
            reason = shapely.is_valid_reason(geometry).split("[")[0].strip()
            return Measurement(
                MeasurementStatus.INVALID_GEOMETRY,
                message=f"Area not calculated: invalid polygon ({reason}).",
            )
        return _measured(MeasurementType.AREA, geometry.area * unit_to_metre**2, UNIT_SQUARE_METRE)
    return Measurement(
        MeasurementStatus.UNSUPPORTED,
        message=f"Measurement is not supported for geometry type '{geometry_type}'.",
    )


def _measured(measurement_type: MeasurementType, value: float, unit: str) -> Measurement:
    if not math.isfinite(value):
        return Measurement(
            MeasurementStatus.FAILED,
            message="Measurement produced a non-finite value; check the coordinates.",
        )
    return Measurement(MeasurementStatus.MEASURED, measurement_type, float(value), unit)


def _measure_safely(geometry: BaseGeometry | None, unit_to_metre: float) -> Measurement:
    try:
        return measure_geometry(geometry, unit_to_metre)
    except (ShapelyError, ValueError, ArithmeticError) as exc:
        logger.warning("Feature measurement failed: %s", type(exc).__name__)
        return Measurement(MeasurementStatus.FAILED, message="Measurement failed for this feature.")
