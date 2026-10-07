"""JSON normalisation of attribute values and geometries."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

from app.utils.file_validation import sanitize_filename
from app.utils.serialization import geometry_to_geojson, serialize_properties, to_json_value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (float("nan"), None),
        (float("inf"), None),
        (np.nan, None),
        (pd.NaT, None),
        (pd.NA, None),
        (np.int64(7), 7),
        (np.float32(1.5), 1.5),
        (np.bool_(True), True),
        (np.float64("nan"), None),
        ("text", "text"),
        (3, 3),
        (2.5, 2.5),
        (Decimal("1.25"), 1.25),
        (b"bytes", "bytes"),
        (pd.Timestamp("2024-03-01 12:30:00"), "2024-03-01T12:30:00"),
        (datetime(2024, 3, 1, 12, 30, tzinfo=UTC), "2024-03-01T12:30:00+00:00"),
        (date(2024, 3, 1), "2024-03-01"),
        (np.datetime64("2024-03-01T12:30:00"), "2024-03-01T12:30:00"),
        (np.array([1, 2]), [1, 2]),
        ({"a": np.int32(1), 2: [np.nan]}, {"a": 1, "2": [None]}),
    ],
)
def test_to_json_value(value, expected):
    result = to_json_value(value)

    assert result == expected
    assert type(result) is type(expected)
    json.dumps(result, allow_nan=False)


def test_serialize_properties_produces_strict_json():
    properties = {"count": np.int64(3), "ratio": np.nan, "when": pd.NaT, 5: "numeric key"}

    result = serialize_properties(properties)

    assert result == {"count": 3, "ratio": None, "when": None, "5": "numeric key"}
    json.dumps(result, allow_nan=False)


def test_geometry_to_geojson_returns_plain_lists():
    geojson = geometry_to_geojson(Polygon([(0, 0), (1, 0), (1, 1), (0, 0)]))

    assert geojson == {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
    }


def test_geometry_to_geojson_keeps_z_and_handles_none():
    assert geometry_to_geojson(Point(1, 2, 3)) == {"type": "Point", "coordinates": [1.0, 2.0, 3.0]}
    assert geometry_to_geojson(None) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("survey.kml", "survey.kml"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\data.zip", "data.zip"),
        ("na\x00me\n.kml", "name.kml"),
        ("", "upload"),
        (None, "upload"),
        ("a" * 300 + ".kml", "a" * 255),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected
