"""POST /api/files/ — accepted uploads and validation failures."""

import uuid

import pytest

from tests.fixtures import builders


def test_upload_valid_kml(upload):
    response = upload("survey.kml", builders.mixed_kml(), "application/vnd.google-earth.kml+xml")

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["filename"] == "survey.kml"
    assert body["file_type"] == "kml"
    assert body["feature_count"] == 3
    assert body["crs"] == "EPSG:4326"
    assert body["measurement_crs"] == "EPSG:32644"
    assert body["status"] == "COMPLETED"
    assert body["error_message"] is None
    assert body["measurement_summary"] == {"MEASURED": 2, "NOT_REQUIRED": 1}
    assert body["size_bytes"] == len(builders.mixed_kml())


def test_upload_valid_shapefile_zip(upload, polygons_wgs84):
    response = upload("parcels.zip", builders.shapefile_zip(polygons_wgs84), "application/zip")

    assert response.status_code == 201
    body = response.json()
    assert body["file_type"] == "shapefile"
    assert body["feature_count"] == 2
    assert body["crs"] == "EPSG:4326"
    assert body["measurement_crs"] == "EPSG:32644"
    assert body["status"] == "COMPLETED"


def test_extension_check_is_case_insensitive(upload):
    assert upload("SURVEY.KML", builders.mixed_kml()).status_code == 201


@pytest.mark.parametrize("filename", ["data.geojson", "data.txt", "data.kmz", "data.shp", "noext"])
def test_unsupported_extension_is_rejected(upload, filename):
    response = upload(filename, b'{"type": "FeatureCollection", "features": []}')

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Unsupported file format. Expected .kml or .zip.",
        "code": "unsupported_file_format",
    }


def test_content_type_header_is_not_trusted(upload):
    """A .zip extension with a ZIP content type but non-ZIP bytes is still rejected."""
    response = upload("data.zip", b"this is definitely not a zip archive", "application/zip")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_archive"


def test_kml_extension_with_non_kml_content_is_rejected(upload):
    response = upload("data.kml", b"just some text, no markup at all")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_file"


def test_zip_bytes_with_kml_extension_are_rejected(upload, polygons_wgs84):
    response = upload("data.kml", builders.shapefile_zip(polygons_wgs84))

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_file"


def test_empty_file_is_rejected(upload):
    response = upload("empty.kml", b"")

    assert response.status_code == 400
    assert response.json()["detail"] == "The uploaded file is empty."


def test_empty_zip_is_rejected(upload):
    response = upload("empty.zip", builders.raw_zip({}))

    assert response.status_code == 400
    assert response.json()["detail"] == "The ZIP archive is empty."


def test_truncated_zip_is_rejected(upload, polygons_wgs84):
    content = builders.shapefile_zip(polygons_wgs84)

    response = upload("broken.zip", content[: len(content) // 2])

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_archive"


def test_zip_without_shapefile(upload):
    response = upload("docs.zip", builders.raw_zip({"readme.txt": b"hello"}))

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_shapefile"
    assert ".shp" in response.json()["detail"]


@pytest.mark.parametrize("missing", [".dbf", ".shx"])
def test_zip_missing_required_component(upload, polygons_wgs84, missing):
    response = upload("parcels.zip", builders.shapefile_zip(polygons_wgs84, omit={missing}))

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_shapefile"
    assert missing in response.json()["detail"]


def test_zip_with_multiple_shapefiles_is_rejected_not_guessed(upload, polygons_wgs84):
    members = builders.shapefile_members(polygons_wgs84, "first")
    members |= builders.shapefile_members(polygons_wgs84, "second")

    response = upload("two.zip", builders.raw_zip(members))

    assert response.status_code == 422
    assert "exactly one .shp" in response.json()["detail"]


def test_malformed_kml_fails_with_controlled_error(upload):
    response = upload("broken.kml", b"<kml><Document><Placemark><Polygon>")

    assert response.status_code == 422
    assert response.json()["code"] == "unreadable_geospatial_file"


def test_kml_without_features(upload):
    response = upload("empty.kml", builders.kml_document())

    assert response.status_code == 422
    assert response.json()["code"] == "no_features"


def test_missing_file_field_is_a_validation_error(client):
    response = client.post("/api/files/", files={"other": ("a.kml", b"x")})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"][0]["loc"] == ["body", "file"]


def test_client_filename_is_reduced_to_a_basename(upload):
    response = upload("../../etc/passwd/..\\evil name.kml", builders.mixed_kml())

    assert response.status_code == 201
    assert response.json()["filename"] == "evil name.kml"


def test_rejected_uploads_leave_nothing_in_storage(upload, settings):
    upload("data.zip", b"not a zip")
    upload("data.txt", b"nope")
    upload("empty.kml", b"")

    assert list(settings.storage_dir.iterdir()) == []


def test_accepted_upload_is_stored_under_its_generated_id(upload, settings):
    file_id = upload("my survey.kml", builders.mixed_kml()).json()["id"]

    assert [path.name for path in settings.storage_dir.iterdir()] == [f"{file_id}.kml"]
