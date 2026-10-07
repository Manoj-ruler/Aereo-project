"""Measurement correctness, through the API and at unit level."""

import math

import pytest
from shapely.geometry import (
    GeometryCollection,
    LinearRing,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from app.core.enums import MeasurementStatus, MeasurementType
from app.services.measurement_service import measure_geometry
from tests.fixtures import builders

# Coordinates are written to KML with 10 decimal places (~0.01 mm), so the
# round trip through WGS84 reproduces the reference shapes almost exactly.
REL_TOLERANCE = 1e-6


def _by_name(body: dict) -> dict[str, dict]:
    return {feature["properties"]["Name"]: feature for feature in body["features"]}


class TestMeasurementsEndpoint:
    def test_response_shape(self, measurements_of):
        body = measurements_of("survey.kml", builders.mixed_kml())

        assert body["crs"] == "EPSG:4326"
        assert body["measurement_crs"] == "EPSG:32644"
        assert body["feature_count"] == 3
        assert [feature["feature_id"] for feature in body["features"]] == [0, 1, 2]
        assert set(body["features"][0]) == {
            "feature_id",
            "geometry_type",
            "measurement_type",
            "value",
            "unit",
            "status",
            "message",
            "properties",
        }

    def test_polygon_area(self, measurements_of):
        polygon = measurements_of("survey.kml", builders.mixed_kml())["features"][0]

        assert polygon["geometry_type"] == "Polygon"
        assert polygon["measurement_type"] == "area"
        assert polygon["unit"] == "m²"
        assert polygon["status"] == "MEASURED"
        assert polygon["value"] == pytest.approx(builders.SQUARE_AREA_M2, rel=REL_TOLERANCE)

    def test_linestring_length(self, measurements_of):
        line = measurements_of("survey.kml", builders.mixed_kml())["features"][1]

        assert line["geometry_type"] == "LineString"
        assert line["measurement_type"] == "length"
        assert line["unit"] == "m"
        assert line["status"] == "MEASURED"
        assert line["value"] == pytest.approx(builders.LINE_LENGTH_M, rel=REL_TOLERANCE)

    def test_point_needs_no_measurement(self, measurements_of):
        point = measurements_of("survey.kml", builders.mixed_kml())["features"][2]

        assert point["geometry_type"] == "Point"
        assert point["status"] == "NOT_REQUIRED"
        assert point["measurement_type"] is None
        assert point["value"] is None
        assert point["unit"] is None

    def test_polygon_holes_are_subtracted(self, measurements_of):
        kml = builders.kml_document(
            builders.kml_placemark(
                "Donut", builders.kml_polygon(builders.SQUARE_UTM, holes=[builders.HOLE_UTM])
            )
        )

        donut = measurements_of("donut.kml", kml)["features"][0]

        assert donut["value"] == pytest.approx(
            builders.SQUARE_AREA_M2 - builders.HOLE_AREA_M2, rel=REL_TOLERANCE
        )

    def test_multipolygon_total_area(self, measurements_of):
        kml = builders.kml_document(
            builders.kml_placemark(
                "Estate",
                builders.kml_multigeometry(
                    builders.kml_polygon(builders.SQUARE_UTM),
                    builders.kml_polygon(builders.SMALL_SQUARE_UTM),
                ),
            )
        )

        estate = measurements_of("estate.kml", kml)["features"][0]

        assert estate["geometry_type"] == "MultiPolygon"
        assert estate["measurement_type"] == "area"
        assert estate["value"] == pytest.approx(
            builders.SQUARE_AREA_M2 + builders.SMALL_SQUARE_AREA_M2, rel=REL_TOLERANCE
        )

    def test_multilinestring_total_length(self, measurements_of):
        kml = builders.kml_document(
            builders.kml_placemark(
                "Network",
                builders.kml_multigeometry(
                    builders.kml_linestring(builders.LINE_UTM),
                    builders.kml_linestring(builders.SHORT_LINE_UTM),
                ),
            )
        )

        network = measurements_of("network.kml", kml)["features"][0]

        assert network["geometry_type"] == "MultiLineString"
        assert network["measurement_type"] == "length"
        assert network["value"] == pytest.approx(
            builders.LINE_LENGTH_M + builders.SHORT_LINE_LENGTH_M, rel=REL_TOLERANCE
        )

    def test_multipoint_needs_no_measurement(self, measurements_of):
        kml = builders.kml_document(
            builders.kml_placemark(
                "Markers",
                builders.kml_multigeometry(
                    builders.kml_point(builders.POINT_UTM),
                    builders.kml_point(builders.SQUARE_UTM[0]),
                ),
            )
        )

        markers = measurements_of("markers.kml", kml)["features"][0]

        assert markers["geometry_type"] == "MultiPoint"
        assert markers["status"] == "NOT_REQUIRED"

    def test_unsupported_geometry_does_not_break_other_features(self, measurements_of):
        """A mixed MultiGeometry becomes a GeometryCollection: reported, not fatal."""
        kml = builders.kml_document(
            builders.kml_placemark("Parcel A", builders.kml_polygon(builders.SQUARE_UTM)),
            builders.kml_placemark(
                "Mixed",
                builders.kml_multigeometry(
                    builders.kml_point(builders.POINT_UTM),
                    builders.kml_linestring(builders.LINE_UTM),
                ),
            ),
            builders.kml_placemark("Access road", builders.kml_linestring(builders.LINE_UTM)),
        )

        features = _by_name(measurements_of("mixed.kml", kml))

        mixed = features["Mixed"]
        assert mixed["geometry_type"] == "GeometryCollection"
        assert mixed["status"] == "UNSUPPORTED"
        assert mixed["value"] is None
        assert mixed["measurement_type"] is None
        assert "GeometryCollection" in mixed["message"]
        assert features["Parcel A"]["value"] == pytest.approx(builders.SQUARE_AREA_M2, rel=1e-6)
        assert features["Access road"]["value"] == pytest.approx(builders.LINE_LENGTH_M, rel=1e-6)

    def test_invalid_polygon_is_flagged_and_others_still_measured(self, measurements_of):
        kml = builders.kml_document(
            builders.kml_placemark("Bowtie", builders.kml_polygon(builders.BOWTIE_UTM)),
            builders.kml_placemark("Parcel A", builders.kml_polygon(builders.SQUARE_UTM)),
        )

        features = _by_name(measurements_of("invalid.kml", kml))

        bowtie = features["Bowtie"]
        assert bowtie["status"] == "INVALID_GEOMETRY"
        assert bowtie["value"] is None
        assert "Self-intersection" in bowtie["message"]
        assert features["Parcel A"]["status"] == "MEASURED"
        assert features["Parcel A"]["value"] == pytest.approx(builders.SQUARE_AREA_M2, rel=1e-6)

    def test_feature_without_geometry(self, measurements_of):
        kml = builders.kml_document(
            builders.kml_placemark("No geometry"),
            builders.kml_placemark("Parcel A", builders.kml_polygon(builders.SQUARE_UTM)),
        )

        features = _by_name(measurements_of("partial.kml", kml))

        assert features["No geometry"]["status"] == "NO_GEOMETRY"
        assert features["No geometry"]["geometry_type"] is None
        assert features["Parcel A"]["status"] == "MEASURED"


class TestMeasureGeometry:
    """``measure_geometry`` takes coordinates that are already projected."""

    def test_polygon(self):
        result = measure_geometry(Polygon(builders.SQUARE_UTM))

        assert result.status is MeasurementStatus.MEASURED
        assert result.measurement_type is MeasurementType.AREA
        assert result.value == builders.SQUARE_AREA_M2
        assert result.unit == "m²"

    def test_linestring(self):
        result = measure_geometry(LineString(builders.LINE_UTM))

        assert result.measurement_type is MeasurementType.LENGTH
        assert result.value == builders.LINE_LENGTH_M
        assert result.unit == "m"

    def test_linear_ring_is_measured_as_length(self):
        result = measure_geometry(LinearRing(builders.SQUARE_UTM))

        assert result.measurement_type is MeasurementType.LENGTH
        assert result.value == 4_000.0

    def test_multipolygon(self):
        geometry = MultiPolygon([Polygon(builders.SQUARE_UTM), Polygon(builders.SMALL_SQUARE_UTM)])

        assert measure_geometry(geometry).value == 1_250_000.0

    def test_multilinestring(self):
        geometry = MultiLineString([builders.LINE_UTM, builders.SHORT_LINE_UTM])

        assert measure_geometry(geometry).value == 7_000.0

    @pytest.mark.parametrize("geometry", [Point(1, 2), MultiPoint([(1, 2), (3, 4)])])
    def test_points(self, geometry):
        result = measure_geometry(geometry)

        assert result.status is MeasurementStatus.NOT_REQUIRED
        assert result.value is None

    def test_geometry_collection_is_unsupported(self):
        result = measure_geometry(GeometryCollection([Point(1, 2), LineString([(0, 0), (1, 1)])]))

        assert result.status is MeasurementStatus.UNSUPPORTED
        assert result.value is None

    @pytest.mark.parametrize("geometry", [None, Polygon(), LineString(), Point()])
    def test_missing_or_empty_geometry(self, geometry):
        assert measure_geometry(geometry).status is MeasurementStatus.NO_GEOMETRY

    def test_invalid_polygon_is_not_measured_or_repaired(self):
        result = measure_geometry(Polygon(builders.BOWTIE_UTM))

        assert result.status is MeasurementStatus.INVALID_GEOMETRY
        assert result.value is None

    def test_unit_factor_converts_to_metres(self):
        foot = 0.3048
        square_100ft = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        line_100ft = LineString([(0, 0), (100, 0)])

        assert measure_geometry(square_100ft, foot).value == pytest.approx(10_000 * foot**2)
        assert measure_geometry(line_100ft, foot).value == pytest.approx(100 * foot)

    def test_non_finite_result_is_reported_as_failed(self):
        result = measure_geometry(LineString([(0, 0), (math.inf, 0)]))

        assert result.status is MeasurementStatus.FAILED
        assert result.value is None
