"""The processing pipeline: file on disk -> features with measurements.

This module is pure (no HTTP, no database), so the same function can be
called from a request handler today or from a background worker later.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd

from app.core.config import Settings
from app.core.enums import FileType
from app.services import crs_service, measurement_service
from app.services.kml_service import read_kml
from app.services.measurement_service import Measurement
from app.services.shapefile_service import read_shapefile_zip
from app.utils.serialization import geometry_to_geojson, serialize_properties

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractedFeature:
    """One feature, already converted to JSON-compatible data."""

    index: int
    geometry_type: str | None
    geometry: dict[str, Any] | None
    properties: dict[str, Any]
    measurement: Measurement


@dataclass(frozen=True)
class ProcessingResult:
    source_crs: str
    measurement_crs: str | None
    features: list[ExtractedFeature]


def read_features(path: Path, file_type: FileType, settings: Settings) -> gpd.GeoDataFrame:
    """Read the uploaded file with the reader for its type."""
    if file_type is FileType.KML:
        return read_kml(path)
    return read_shapefile_zip(path, settings)


def process_file(path: Path, file_type: FileType, settings: Settings) -> ProcessingResult:
    """Read a file, choose its measurement CRS and measure every feature."""
    gdf = read_features(path, file_type, settings)

    plan = crs_service.plan_measurement(gdf)
    source_crs = crs_service.describe_crs(plan.source_crs)
    measurement_crs = (
        crs_service.describe_crs(plan.measurement_crs) if plan.measurement_crs else None
    )
    logger.info(
        "CRS resolved: source_crs=%s measurement_crs=%s strategy=%s",
        source_crs, measurement_crs, plan.strategy,
    )  # fmt: skip

    measurements = measurement_service.measure_features(gdf.geometry, plan)
    return ProcessingResult(source_crs, measurement_crs, _build_features(gdf, measurements))


def _build_features(
    gdf: gpd.GeoDataFrame, measurements: list[Measurement]
) -> list[ExtractedFeature]:
    """Pair each feature's geometry (in the source CRS) and attributes with its measurement."""
    attribute_rows = gdf.drop(columns=gdf.geometry.name).to_dict(orient="records")
    features = []
    for index, (geometry, attributes, measurement) in enumerate(
        zip(gdf.geometry, attribute_rows, measurements, strict=True)
    ):
        has_geometry = geometry is not None and not geometry.is_empty
        features.append(
            ExtractedFeature(
                index=index,
                geometry_type=geometry.geom_type if has_geometry else None,
                geometry=geometry_to_geojson(geometry) if has_geometry else None,
                properties=serialize_properties(attributes),
                measurement=measurement,
            )
        )
    return features
