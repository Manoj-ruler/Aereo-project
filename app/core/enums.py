"""Enumerations shared across layers."""

from enum import StrEnum


class FileType(StrEnum):
    KML = "kml"
    SHAPEFILE = "shapefile"


class FileStatus(StrEnum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MeasurementType(StrEnum):
    AREA = "area"
    LENGTH = "length"


class MeasurementStatus(StrEnum):
    MEASURED = "MEASURED"
    """An area or length was calculated."""

    NOT_REQUIRED = "NOT_REQUIRED"
    """Point geometries: nothing to measure."""

    UNSUPPORTED = "UNSUPPORTED"
    """Geometry type has no defined measurement (e.g. GeometryCollection)."""

    INVALID_GEOMETRY = "INVALID_GEOMETRY"
    """Polygon is topologically invalid, so its area would be unreliable."""

    NO_GEOMETRY = "NO_GEOMETRY"
    """Feature has a null or empty geometry."""

    FAILED = "FAILED"
    """Measurement of this single feature failed unexpectedly."""
