"""CRS handling: geographic data must never be measured in degrees."""

import geopandas as gpd
import pytest
from pyproj import CRS, Geod
from shapely.geometry import LineString, Point, Polygon

from app.core.exceptions import CRSTransformError, InvalidCRSError, MissingCRSError
from app.services import crs_service
from app.services.crs_service import MeasurementPlan
from tests.fixtures import builders

WGS84_ELLIPSOID = Geod(ellps="WGS84")

# UTM's scale factor is 0.9996 on the central meridian and rises to about 1.001
# at a zone edge, so within a zone a UTM length is within ~0.1 % of the true
# (geodesic) length and an area within ~0.2 %.
UTM_LENGTH_TOLERANCE = 1e-3
UTM_AREA_TOLERANCE = 2e-3


class TestGeographicInput:
    def test_epsg_4326_is_transformed_to_local_utm(self, upload, polygons_wgs84):
        body = upload("parcels.zip", builders.shapefile_zip(polygons_wgs84)).json()

        assert body["crs"] == "EPSG:4326"
        assert body["measurement_crs"] == "EPSG:32644"
        assert CRS(body["measurement_crs"]).is_projected

    def test_area_is_in_square_metres_not_square_degrees(self, measurements_of, polygons_wgs84):
        """Measuring the raw lon/lat polygon would give ~8e-5 'square degrees'."""
        square = polygons_wgs84.geometry.iloc[0]
        area_in_degrees = square.area
        geodesic_area = abs(WGS84_ELLIPSOID.geometry_area_perimeter(square)[0])

        body = measurements_of("parcels.zip", builders.shapefile_zip(polygons_wgs84))
        value = body["features"][0]["value"]

        assert area_in_degrees < 1e-4
        assert value > 1e9 * area_in_degrees
        assert value == pytest.approx(builders.SQUARE_AREA_M2, rel=1e-6)
        assert value == pytest.approx(geodesic_area, rel=UTM_AREA_TOLERANCE)
        assert body["features"][0]["unit"] == "m²"

    def test_length_is_in_metres_not_degrees(self, measurements_of, lines_wgs84):
        line = lines_wgs84.geometry.iloc[0]
        length_in_degrees = line.length
        geodesic_length = WGS84_ELLIPSOID.geometry_length(line)

        body = measurements_of("roads.zip", builders.shapefile_zip(lines_wgs84))
        value = body["features"][0]["value"]

        assert length_in_degrees < 0.1
        assert value == pytest.approx(builders.LINE_LENGTH_M, rel=1e-6)
        assert value == pytest.approx(geodesic_length, rel=UTM_LENGTH_TOLERANCE)
        assert body["features"][0]["unit"] == "m"

    def test_kml_crs_is_reported_by_the_parser_and_transformed(self, upload):
        body = upload("survey.kml", builders.mixed_kml()).json()

        assert body["crs"] == "EPSG:4326"
        assert body["measurement_crs"] == "EPSG:32644"

    def test_utm_zone_follows_the_data_location(self, measurements_of):
        """A 0.01° square near Sydney must use a southern-hemisphere zone (56S)."""
        square = Polygon([(151.20, -33.87), (151.21, -33.87), (151.21, -33.86), (151.20, -33.86)])
        sydney = gpd.GeoDataFrame({"name": ["Sydney"]}, geometry=[square], crs="EPSG:4326")
        geodesic_area = abs(WGS84_ELLIPSOID.geometry_area_perimeter(square)[0])

        body = measurements_of("sydney.zip", builders.shapefile_zip(sydney))

        assert body["measurement_crs"] == "EPSG:32756"
        assert body["features"][0]["value"] == pytest.approx(geodesic_area, rel=UTM_AREA_TOLERANCE)

    def test_other_geographic_datums_are_also_transformed(self, measurements_of, polygons_wgs84):
        nad83 = polygons_wgs84.set_crs("EPSG:4269", allow_override=True)

        body = measurements_of("nad83.zip", builders.shapefile_zip(nad83))

        assert body["crs"] == "EPSG:4269"
        assert CRS(body["measurement_crs"]).is_projected
        assert body["features"][0]["value"] == pytest.approx(
            builders.SQUARE_AREA_M2, rel=UTM_AREA_TOLERANCE
        )


class TestProjectedInput:
    def test_projected_metric_crs_is_measured_as_is(self, measurements_of, polygons_utm):
        body = measurements_of("utm.zip", builders.shapefile_zip(polygons_utm))

        assert body["crs"] == "EPSG:32644"
        assert body["measurement_crs"] == "EPSG:32644"
        assert body["features"][0]["value"] == pytest.approx(builders.SQUARE_AREA_M2, rel=1e-9)

    def test_projected_crs_in_feet_is_converted_to_metres(self, measurements_of):
        """EPSG:2263 (New York Long Island) uses US survey feet."""
        us_survey_foot = 1200 / 3937
        square_1000ft = Polygon(
            [(985_000, 195_000), (986_000, 195_000), (986_000, 196_000), (985_000, 196_000)]
        )
        line_1000ft = LineString([(985_000, 195_000), (986_000, 195_000)])

        squares = gpd.GeoDataFrame({"n": [1]}, geometry=[square_1000ft], crs="EPSG:2263")
        lines = gpd.GeoDataFrame({"n": [1]}, geometry=[line_1000ft], crs="EPSG:2263")
        area_body = measurements_of("ny_area.zip", builders.shapefile_zip(squares))
        length_body = measurements_of("ny_line.zip", builders.shapefile_zip(lines))

        assert area_body["measurement_crs"] == "EPSG:2263"
        assert area_body["features"][0]["unit"] == "m²"
        assert area_body["features"][0]["value"] == pytest.approx(
            1_000_000 * us_survey_foot**2, rel=1e-9
        )
        assert length_body["features"][0]["unit"] == "m"
        assert length_body["features"][0]["value"] == pytest.approx(
            1_000 * us_survey_foot, rel=1e-9
        )

    def test_web_mercator_is_not_used_for_measurement(self, measurements_of, polygons_wgs84):
        """EPSG:3857 is projected, but at 60°N it inflates areas roughly 4x."""
        oslo = Polygon([(10.70, 59.90), (10.72, 59.90), (10.72, 59.91), (10.70, 59.91)])
        geographic = gpd.GeoDataFrame({"name": ["Oslo"]}, geometry=[oslo], crs="EPSG:4326")
        web_mercator = geographic.to_crs("EPSG:3857")
        geodesic_area = abs(WGS84_ELLIPSOID.geometry_area_perimeter(oslo)[0])
        naive_area = web_mercator.geometry.iloc[0].area

        body = measurements_of("oslo.zip", builders.shapefile_zip(web_mercator))
        value = body["features"][0]["value"]

        assert body["crs"] == "EPSG:3857"
        assert body["measurement_crs"] == "EPSG:32632"
        assert naive_area > 3.5 * geodesic_area
        assert value == pytest.approx(geodesic_area, rel=UTM_AREA_TOLERANCE)


class TestCrsFailures:
    def test_missing_prj_fails_gracefully(self, upload, polygons_wgs84):
        response = upload("noprj.zip", builders.shapefile_zip(polygons_wgs84, omit={".prj"}))

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "missing_crs"
        assert "CRS could not be determined" in body["detail"]
        assert "file_id" in body

    def test_unparseable_prj_fails_gracefully(self, upload, polygons_wgs84):
        content = builders.shapefile_zip(
            polygons_wgs84, overrides={".prj": b"THIS IS NOT A COORDINATE SYSTEM"}
        )

        response = upload("badprj.zip", content)

        assert response.status_code == 422
        assert response.json()["code"] == "invalid_crs"

    def test_coordinates_outside_the_crs_domain_fail_gracefully(self, upload):
        """Projected-looking numbers declared as EPSG:4326 cannot be valid lon/lat."""
        bogus = gpd.GeoDataFrame(
            {"n": [1]}, geometry=[Polygon(builders.SQUARE_UTM)], crs="EPSG:4326"
        )

        response = upload("bogus.zip", builders.shapefile_zip(bogus))

        assert response.status_code == 422
        assert response.json()["code"] == "crs_transformation_failed"


class TestPlanMeasurement:
    @staticmethod
    def _frame(geometry, crs) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(geometry=[geometry], crs=crs)

    def test_missing_crs_is_never_guessed(self):
        with pytest.raises(MissingCRSError):
            crs_service.plan_measurement(self._frame(Point(80, 13), None))

    def test_geographic_crs_gets_estimated_utm(self):
        plan = crs_service.plan_measurement(self._frame(Point(80, 13), "EPSG:4326"))

        assert plan.measurement_crs.to_epsg() == 32644
        assert plan.strategy == crs_service.STRATEGY_ESTIMATED_UTM
        assert plan.unit_to_metre == 1.0

    def test_projected_crs_is_kept(self):
        plan = crs_service.plan_measurement(self._frame(Point(400_000, 1_450_000), "EPSG:32644"))

        assert plan.measurement_crs == plan.source_crs
        assert plan.strategy == crs_service.STRATEGY_SOURCE_PROJECTED

    def test_foot_based_crs_reports_conversion_factor(self):
        plan = crs_service.plan_measurement(self._frame(Point(985_000, 195_000), "EPSG:2263"))

        assert plan.unit_to_metre == pytest.approx(1200 / 3937)

    def test_web_mercator_is_replaced_by_utm(self):
        plan = crs_service.plan_measurement(self._frame(Point(8_900_000, 1_460_000), "EPSG:3857"))

        assert plan.measurement_crs.to_epsg() == 32644

    def test_geocentric_crs_is_rejected(self):
        with pytest.raises(InvalidCRSError):
            crs_service.plan_measurement(self._frame(Point(1, 2), "EPSG:4978"))

    def test_only_empty_geometries_need_no_measurement_crs(self):
        plan = crs_service.plan_measurement(self._frame(None, "EPSG:4326"))

        assert plan.measurement_crs is None

    def test_measuring_refuses_a_geographic_measurement_crs(self):
        """Safety net: degrees can never reach the area/length calculation."""
        wgs84 = CRS("EPSG:4326")
        plan = MeasurementPlan(wgs84, wgs84, 1.0, "bogus")
        geometries = gpd.GeoSeries([Point(80, 13)], crs=wgs84)

        with pytest.raises(CRSTransformError):
            crs_service.to_measurement_crs(geometries, plan)

    @pytest.mark.parametrize(
        ("crs", "expected"),
        [("EPSG:4326", "EPSG:4326"), ("EPSG:32644", "EPSG:32644"), ("EPSG:3857", "EPSG:3857")],
    )
    def test_describe_crs(self, crs, expected):
        assert crs_service.describe_crs(CRS(crs)) == expected
