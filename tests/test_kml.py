"""KML-specific behaviour."""

import pytest

from app.core.exceptions import GeospatialReadError, NoFeaturesError
from app.services.kml_service import read_kml
from tests.fixtures import builders


def test_placemark_name_and_extended_data_are_preserved(client, upload):
    file_id = upload("survey.kml", builders.mixed_kml()).json()["id"]

    properties = client.get(f"/api/files/{file_id}/features/").json()["features"][0]["properties"]

    assert properties["Name"] == "Parcel A"
    assert properties["owner"] == "Asha"
    assert properties["zone"] == "R1"


def test_features_from_all_folders_are_read_in_document_order(measurements_of):
    """GDAL exposes each <Folder> as its own layer; none may be dropped."""
    kml = builders.kml_document(
        builders.kml_folder(
            "Parcels",
            builders.kml_placemark("Parcel A", builders.kml_polygon(builders.SQUARE_UTM)),
            builders.kml_placemark("Parcel B", builders.kml_polygon(builders.SMALL_SQUARE_UTM)),
        ),
        builders.kml_folder(
            "Roads",
            builders.kml_placemark("Access road", builders.kml_linestring(builders.LINE_UTM)),
        ),
    )

    body = measurements_of("folders.kml", kml)

    assert body["feature_count"] == 3
    assert [f["feature_id"] for f in body["features"]] == [0, 1, 2]
    assert [f["properties"]["Name"] for f in body["features"]] == [
        "Parcel A",
        "Parcel B",
        "Access road",
    ]
    assert [f["geometry_type"] for f in body["features"]] == [
        "Polygon",
        "Polygon",
        "LineString",
    ]


def test_properties_are_json_native(client, upload):
    """Null timestamps / NaN values from the KML schema must serialise as null."""
    file_id = upload("survey.kml", builders.mixed_kml()).json()["id"]

    features = client.get(f"/api/files/{file_id}/features/").json()["features"]

    for feature in features:
        for value in feature["properties"].values():
            assert value is None or isinstance(value, str | int | float | bool)
    assert features[0]["properties"]["timestamp"] is None


def test_read_kml_reports_wgs84(tmp_path):
    path = tmp_path / "survey.kml"
    path.write_bytes(builders.mixed_kml())

    gdf = read_kml(path)

    assert gdf.crs.to_epsg() == 4326
    assert list(gdf.geom_type) == ["Polygon", "LineString", "Point"]


def test_read_kml_rejects_malformed_documents_without_leaking_paths(tmp_path):
    path = tmp_path / "secret-location.kml"
    path.write_bytes(b"<kml><Document><Placemark>")

    with pytest.raises(GeospatialReadError) as error:
        read_kml(path)

    assert "secret-location" not in error.value.detail
    assert str(tmp_path) not in error.value.detail


def test_read_kml_without_placemarks(tmp_path):
    path = tmp_path / "empty.kml"
    path.write_bytes(builders.kml_document())

    with pytest.raises(NoFeaturesError):
        read_kml(path)
