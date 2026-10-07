"""GET /api/files/{id}/ and GET /api/files/{id}/features/."""

import uuid
from datetime import datetime

import pytest

from tests.fixtures import builders


def test_file_information_matches_upload_response(client, upload):
    created = upload("survey.kml", builders.mixed_kml()).json()

    response = client.get(f"/api/files/{created['id']}/")

    assert response.status_code == 200
    assert response.json() == created


def test_file_information_contains_the_assessment_fields(client, upload):
    file_id = upload("survey.kml", builders.mixed_kml()).json()["id"]

    body = client.get(f"/api/files/{file_id}/").json()

    assert {
        "id": body["id"],
        "filename": body["filename"],
        "feature_count": body["feature_count"],
        "crs": body["crs"],
        "status": body["status"],
    } == {
        "id": file_id,
        "filename": "survey.kml",
        "feature_count": 3,
        "crs": "EPSG:4326",
        "status": "COMPLETED",
    }
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None
    assert datetime.fromisoformat(body["processed_at"]).tzinfo is not None


@pytest.mark.parametrize("suffix", ["", "measurements/", "features/"])
def test_unknown_file_id_returns_404(client, suffix):
    response = client.get(f"/api/files/{uuid.uuid4()}/{suffix}")

    assert response.status_code == 404
    assert response.json() == {"detail": "File not found.", "code": "file_not_found"}


def test_non_uuid_file_id_returns_404(client):
    assert client.get("/api/files/not-a-real-id/").status_code == 404


def test_failed_processing_is_recorded_and_retrievable(client, upload, polygons_wgs84):
    """A stored-but-unprocessable file is kept as FAILED and explains why."""
    failed = upload("parcels.zip", builders.shapefile_zip(polygons_wgs84, omit={".prj"}))
    assert failed.status_code == 422
    file_id = failed.json()["file_id"]

    info = client.get(f"/api/files/{file_id}/")

    assert info.status_code == 200
    body = info.json()
    assert body["status"] == "FAILED"
    assert body["feature_count"] == 0
    assert body["crs"] is None
    assert body["error_message"] == failed.json()["detail"]


@pytest.mark.parametrize("suffix", ["measurements/", "features/"])
def test_results_of_a_failed_file_return_409(client, upload, polygons_wgs84, suffix):
    failed = upload("parcels.zip", builders.shapefile_zip(polygons_wgs84, omit={".prj"}))
    file_id = failed.json()["file_id"]

    response = client.get(f"/api/files/{file_id}/{suffix}")

    assert response.status_code == 409
    assert response.json()["code"] == "file_not_processed"
    assert "FAILED" in response.json()["detail"]


def test_features_endpoint_returns_geojson_geometry_and_properties(client, upload):
    file_id = upload("survey.kml", builders.mixed_kml()).json()["id"]

    response = client.get(f"/api/files/{file_id}/features/")

    assert response.status_code == 200
    body = response.json()
    assert body["crs"] == "EPSG:4326"
    assert body["feature_count"] == 3
    assert [feature["feature_id"] for feature in body["features"]] == [0, 1, 2]
    assert [feature["geometry_type"] for feature in body["features"]] == [
        "Polygon",
        "LineString",
        "Point",
    ]

    polygon = body["features"][0]["geometry"]
    assert polygon["type"] == "Polygon"
    ring = polygon["coordinates"][0]
    expected = builders.to_lonlat(builders.SQUARE_UTM)
    assert len(ring) == len(expected)
    for (lon, lat, *_), (expected_lon, expected_lat) in zip(ring, expected, strict=True):
        assert lon == pytest.approx(expected_lon, abs=1e-9)
        assert lat == pytest.approx(expected_lat, abs=1e-9)

    point = body["features"][2]["geometry"]
    assert point["type"] == "Point"
    assert body["features"][0]["properties"]["Name"] == "Parcel A"


def test_health_and_docs_are_available(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200

    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) >= {
        "/api/files/",
        "/api/files/{file_id}/",
        "/api/files/{file_id}/measurements/",
        "/api/files/{file_id}/features/",
    }
