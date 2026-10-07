"""Conversion of geospatial / pandas / NumPy values to plain JSON-compatible data."""

import json
import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
import shapely
from shapely.geometry.base import BaseGeometry


def to_json_value(value: Any) -> Any:
    """Convert a single attribute value to something ``json.dumps`` accepts.

    NaN/NaT/NA and non-finite floats become ``None``; NumPy scalars become
    Python scalars; dates and timestamps become ISO-8601 strings.
    """
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | np.ndarray):
        return [to_json_value(item) for item in value]
    return str(value)


def serialize_properties(properties: dict[Any, Any]) -> dict[str, Any]:
    """Convert a feature's attribute mapping to a JSON-compatible dict."""
    return {str(key): to_json_value(value) for key, value in properties.items()}


def geometry_to_geojson(geometry: BaseGeometry | None) -> dict[str, Any] | None:
    """Return the geometry as a GeoJSON-style dict (``type`` + ``coordinates``)."""
    if geometry is None:
        return None
    return json.loads(shapely.to_geojson(geometry))
