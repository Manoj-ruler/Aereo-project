"""CRS inspection and selection of the CRS used for measurement.

This module is the single place that decides *in which coordinate system*
areas and lengths are computed. The rule is: measurements are only ever taken
in a projected CRS, and the result is always expressed in metres.
"""

import logging
import math
from dataclasses import dataclass

import geopandas as gpd
from pyproj import CRS
from pyproj.exceptions import CRSError, ProjError

from app.core.exceptions import CRSTransformError, InvalidCRSError, MissingCRSError

logger = logging.getLogger(__name__)

WEB_MERCATOR_METHOD = "Popular Visualisation Pseudo Mercator"
AUTHORITY_MIN_CONFIDENCE = 70

STRATEGY_SOURCE_PROJECTED = "source_projected_crs"
STRATEGY_ESTIMATED_UTM = "estimated_utm_zone"
STRATEGY_NOT_APPLICABLE = "no_measurable_geometry"


@dataclass(frozen=True)
class MeasurementPlan:
    """How the geometries of one file will be measured."""

    source_crs: CRS
    measurement_crs: CRS | None
    """Projected CRS to measure in; ``None`` only if no feature has coordinates."""
    unit_to_metre: float
    """Factor converting the measurement CRS's linear unit to metres."""
    strategy: str


def describe_crs(crs: CRS) -> str:
    """Return a compact identifier such as ``EPSG:4326`` (or the CRS name)."""
    authority = crs.to_authority(min_confidence=AUTHORITY_MIN_CONFIDENCE)
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.name or "unknown"


def plan_measurement(gdf: gpd.GeoDataFrame) -> MeasurementPlan:
    """Decide which projected CRS to measure the features of ``gdf`` in.

    * no CRS                         -> :class:`MissingCRSError` (never guessed)
    * projected, suitable            -> measure in the source CRS
    * geographic (lat/lon degrees)   -> estimate the local UTM zone
    * Web Mercator (EPSG:3857)       -> estimate the local UTM zone, because its
                                        scale distortion grows with latitude
    * anything else (geocentric...)  -> :class:`InvalidCRSError`
    """
    source_crs = gdf.crs
    if source_crs is None:
        raise MissingCRSError()

    if source_crs.is_projected and not _is_web_mercator(source_crs):
        measurement_crs, strategy = source_crs, STRATEGY_SOURCE_PROJECTED
    elif source_crs.is_geographic or source_crs.is_projected:
        measurement_crs = _estimate_utm_crs(gdf)
        strategy = STRATEGY_ESTIMATED_UTM if measurement_crs else STRATEGY_NOT_APPLICABLE
    else:
        raise InvalidCRSError(
            f"CRS '{describe_crs(source_crs)}' is neither geographic nor projected and "
            "is not supported for measurement."
        )

    unit_to_metre = _metre_conversion_factor(measurement_crs) if measurement_crs else 1.0
    return MeasurementPlan(source_crs, measurement_crs, unit_to_metre, strategy)


def to_measurement_crs(geometries: gpd.GeoSeries, plan: MeasurementPlan) -> gpd.GeoSeries:
    """Return the geometries in the plan's projected measurement CRS."""
    if plan.measurement_crs is None or not plan.measurement_crs.is_projected:
        # Defensive: guarantees degrees can never reach the area/length maths.
        raise CRSTransformError()
    if plan.measurement_crs == plan.source_crs:
        return geometries
    try:
        return geometries.to_crs(plan.measurement_crs)
    except (CRSError, ProjError, ValueError) as exc:
        logger.warning("CRS transformation failed: %s", exc)
        raise CRSTransformError() from exc


def _is_web_mercator(crs: CRS) -> bool:
    operation = crs.coordinate_operation
    return operation is not None and operation.method_name == WEB_MERCATOR_METHOD


def _estimate_utm_crs(gdf: gpd.GeoDataFrame) -> CRS | None:
    """Estimate the UTM zone covering the dataset, or ``None`` if it has no coordinates."""
    geometries = gdf.geometry
    with_coordinates = geometries[~(geometries.isna() | geometries.is_empty)]
    if with_coordinates.empty:
        return None
    try:
        return with_coordinates.estimate_utm_crs()
    except (CRSError, ProjError, ValueError, RuntimeError) as exc:
        logger.warning("UTM zone estimation failed: %s", exc)
        raise CRSTransformError() from exc


def _metre_conversion_factor(crs: CRS) -> float:
    """Return how many metres one linear unit of the projected CRS represents."""
    factor = crs.axis_info[0].unit_conversion_factor if crs.axis_info else math.nan
    if not math.isfinite(factor) or factor <= 0:
        raise InvalidCRSError(
            f"The linear unit of CRS '{describe_crs(crs)}' could not be determined."
        )
    return factor
