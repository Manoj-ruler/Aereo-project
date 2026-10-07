"""Shared fixtures: an isolated app per test plus upload helpers."""

from collections.abc import Callable, Iterator
from pathlib import Path

import geopandas as gpd
import httpx
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, Polygon

from app.core.config import Settings
from app.main import create_app
from tests.fixtures import builders

Upload = Callable[..., httpx.Response]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointing at a throwaway database and storage directory, with small limits."""
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_dir=tmp_path / "storage",
        max_upload_size_mb=1,
        max_zip_files=10,
        max_zip_uncompressed_mb=2,
        log_level="WARNING",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def upload(client: TestClient) -> Upload:
    """Upload ``content`` under ``filename`` and return the response."""

    def _upload(
        filename: str, content: bytes, content_type: str = "application/octet-stream"
    ) -> httpx.Response:
        return client.post("/api/files/", files={"file": (filename, content, content_type)})

    return _upload


@pytest.fixture
def measurements_of(client: TestClient, upload: Upload) -> Callable[[str, bytes], dict]:
    """Upload a file (asserting success) and return its measurements response body."""

    def _measurements(filename: str, content: bytes) -> dict:
        response = upload(filename, content)
        assert response.status_code == 201, response.text
        result = client.get(f"/api/files/{response.json()['id']}/measurements/")
        assert result.status_code == 200, result.text
        return result.json()

    return _measurements


@pytest.fixture
def polygons_wgs84() -> gpd.GeoDataFrame:
    """Two polygons in EPSG:4326 with attributes of several types."""
    return gpd.GeoDataFrame(
        {
            "name": ["Parcel A", "Parcel B"],
            "parcel_no": [101, 102],
            "rate": [12.5, 7.25],
        },
        geometry=[
            Polygon(builders.to_lonlat(builders.SQUARE_UTM)),
            Polygon(builders.to_lonlat(builders.SMALL_SQUARE_UTM)),
        ],
        crs=builders.WGS84,
    )


@pytest.fixture
def polygons_utm() -> gpd.GeoDataFrame:
    """The 1 km² reference square in projected EPSG:32644."""
    return gpd.GeoDataFrame(
        {"name": ["Parcel A"]}, geometry=[Polygon(builders.SQUARE_UTM)], crs=builders.UTM_44N
    )


@pytest.fixture
def lines_wgs84() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"name": ["Access road"]},
        geometry=[LineString(builders.to_lonlat(builders.LINE_UTM))],
        crs=builders.WGS84,
    )


@pytest.fixture
def points_wgs84() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"name": ["Survey marker"]},
        geometry=[Point(builders.to_lonlat([builders.POINT_UTM])[0])],
        crs=builders.WGS84,
    )
