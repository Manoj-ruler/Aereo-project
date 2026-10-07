"""Shapefile ZIP specific behaviour."""

import tempfile
from datetime import date
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import MultiLineString, MultiPolygon, Polygon

from tests.fixtures import builders


def test_attributes_are_preserved_with_their_types(client, upload, polygons_wgs84):
    polygons_wgs84["surveyed"] = [date(2024, 3, 1), None]
    file_id = upload("parcels.zip", builders.shapefile_zip(polygons_wgs84)).json()["id"]

    features = client.get(f"/api/files/{file_id}/features/").json()["features"]

    properties = features[0]["properties"]
    assert properties["name"] == "Parcel A"
    assert properties["parcel_no"] == 101
    assert properties["rate"] == 12.5
    # ISO-8601 string; whether a midnight time part is included depends on pandas.
    assert properties["surveyed"].startswith("2024-03-01")
    assert features[1]["properties"]["surveyed"] is None
    assert features[0]["geometry"]["type"] == "Polygon"


def test_polygon_areas(measurements_of, polygons_wgs84):
    body = measurements_of("parcels.zip", builders.shapefile_zip(polygons_wgs84))

    assert [f["value"] for f in body["features"]] == [
        pytest.approx(builders.SQUARE_AREA_M2, rel=1e-6),
        pytest.approx(builders.SMALL_SQUARE_AREA_M2, rel=1e-6),
    ]


def test_line_length(measurements_of, lines_wgs84):
    body = measurements_of("roads.zip", builders.shapefile_zip(lines_wgs84))

    assert body["features"][0]["geometry_type"] == "LineString"
    assert body["features"][0]["value"] == pytest.approx(builders.LINE_LENGTH_M, rel=1e-6)


def test_points(measurements_of, points_wgs84):
    body = measurements_of("markers.zip", builders.shapefile_zip(points_wgs84))

    assert body["features"][0]["geometry_type"] == "Point"
    assert body["features"][0]["status"] == "NOT_REQUIRED"
    assert body["measurement_crs"] == "EPSG:32644"


def test_multipolygon_and_multilinestring(measurements_of):
    estate = gpd.GeoDataFrame(
        {"name": ["Estate"]},
        geometry=[MultiPolygon([Polygon(builders.SQUARE_UTM), Polygon(builders.SMALL_SQUARE_UTM)])],
        crs=builders.UTM_44N,
    )
    network = gpd.GeoDataFrame(
        {"name": ["Network"]},
        geometry=[MultiLineString([builders.LINE_UTM, builders.SHORT_LINE_UTM])],
        crs=builders.UTM_44N,
    )

    estate_feature = measurements_of("estate.zip", builders.shapefile_zip(estate))["features"][0]
    network_feature = measurements_of("net.zip", builders.shapefile_zip(network))["features"][0]

    assert estate_feature["geometry_type"] == "MultiPolygon"
    assert estate_feature["value"] == pytest.approx(1_250_000.0, rel=1e-9)
    assert network_feature["geometry_type"] == "MultiLineString"
    assert network_feature["value"] == pytest.approx(7_000.0, rel=1e-9)


def test_shapefile_inside_a_folder_is_found(upload, polygons_wgs84):
    response = upload("nested.zip", builders.shapefile_zip(polygons_wgs84, folder="data/v1/"))

    assert response.status_code == 201
    assert response.json()["feature_count"] == 2


def test_unrelated_files_in_the_archive_are_ignored(upload, polygons_wgs84):
    content = builders.shapefile_zip(
        polygons_wgs84,
        extra_members={"README.txt": b"notes", "__MACOSX/._layer.shp": b"resource fork"},
    )

    response = upload("parcels.zip", content)

    assert response.status_code == 201
    assert response.json()["feature_count"] == 2


def test_shapefile_without_features(upload, polygons_wgs84):
    response = upload("empty.zip", builders.shapefile_zip(polygons_wgs84.iloc[0:0]))

    assert response.status_code == 422
    assert response.json()["code"] == "no_features"


def test_corrupted_shp_fails_with_controlled_error(upload, polygons_wgs84):
    content = builders.shapefile_zip(polygons_wgs84, overrides={".shp": b"\x00" * 64})

    response = upload("corrupt.zip", content)

    assert response.status_code == 422
    assert response.json()["code"] in {"unreadable_geospatial_file", "no_features"}


def test_temporary_extraction_directory_is_removed(upload, polygons_wgs84, monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    ok = upload("parcels.zip", builders.shapefile_zip(polygons_wgs84))
    failed = upload("parcels.zip", builders.shapefile_zip(polygons_wgs84, omit={".dbf"}))

    assert ok.status_code == 201
    assert failed.status_code == 422
    assert list(Path(scratch).iterdir()) == []
