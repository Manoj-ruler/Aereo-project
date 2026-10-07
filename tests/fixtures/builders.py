"""Programmatic builders for small, deterministic geospatial test files.

Reference shapes are defined in UTM zone 44N (EPSG:32644) metres, where their
area/length is known exactly, and converted to WGS84 longitude/latitude for
files that use geographic coordinates.
"""

import io
import tempfile
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import geopandas as gpd
from pyproj import Transformer

UTM_44N = "EPSG:32644"
WGS84 = "EPSG:4326"

# A 1000 m x 1000 m square: exactly 1 000 000 m².
SQUARE_UTM = [
    (400_000.0, 1_450_000.0),
    (401_000.0, 1_450_000.0),
    (401_000.0, 1_451_000.0),
    (400_000.0, 1_451_000.0),
    (400_000.0, 1_450_000.0),
]
SQUARE_AREA_M2 = 1_000_000.0

# A 200 m x 200 m hole inside the square: 40 000 m².
HOLE_UTM = [
    (400_400.0, 1_450_400.0),
    (400_400.0, 1_450_600.0),
    (400_600.0, 1_450_600.0),
    (400_600.0, 1_450_400.0),
    (400_400.0, 1_450_400.0),
]
HOLE_AREA_M2 = 40_000.0

# A second, disjoint 500 m x 500 m square: 250 000 m².
SMALL_SQUARE_UTM = [
    (402_000.0, 1_450_000.0),
    (402_500.0, 1_450_000.0),
    (402_500.0, 1_450_500.0),
    (402_000.0, 1_450_500.0),
    (402_000.0, 1_450_000.0),
]
SMALL_SQUARE_AREA_M2 = 250_000.0

# A 3-4-5 triangle side: exactly 5000 m.
LINE_UTM = [(400_000.0, 1_450_000.0), (403_000.0, 1_454_000.0)]
LINE_LENGTH_M = 5_000.0

# A second line of exactly 2000 m.
SHORT_LINE_UTM = [(400_000.0, 1_452_000.0), (402_000.0, 1_452_000.0)]
SHORT_LINE_LENGTH_M = 2_000.0

POINT_UTM = (400_500.0, 1_450_500.0)

# Self-intersecting "bow-tie" ring: an invalid polygon.
BOWTIE_UTM = [
    (400_000.0, 1_450_000.0),
    (401_000.0, 1_451_000.0),
    (401_000.0, 1_450_000.0),
    (400_000.0, 1_451_000.0),
    (400_000.0, 1_450_000.0),
]

_to_wgs84 = Transformer.from_crs(UTM_44N, WGS84, always_xy=True)

Coordinates = Sequence[tuple[float, float]]


def to_lonlat(coordinates: Coordinates) -> list[tuple[float, float]]:
    """Convert UTM 44N metres to WGS84 (longitude, latitude)."""
    return [_to_wgs84.transform(x, y) for x, y in coordinates]


# -- KML ----------------------------------------------------------------------


def _kml_coordinates(utm_coordinates: Coordinates) -> str:
    return " ".join(f"{lon:.10f},{lat:.10f},0" for lon, lat in to_lonlat(utm_coordinates))


def kml_polygon(outer: Coordinates, holes: Iterable[Coordinates] = ()) -> str:
    inner = "".join(
        "<innerBoundaryIs><LinearRing><coordinates>"
        f"{_kml_coordinates(hole)}</coordinates></LinearRing></innerBoundaryIs>"
        for hole in holes
    )
    return (
        "<Polygon><outerBoundaryIs><LinearRing><coordinates>"
        f"{_kml_coordinates(outer)}</coordinates></LinearRing></outerBoundaryIs>{inner}</Polygon>"
    )


def kml_linestring(coordinates: Coordinates) -> str:
    return f"<LineString><coordinates>{_kml_coordinates(coordinates)}</coordinates></LineString>"


def kml_point(coordinate: tuple[float, float]) -> str:
    return f"<Point><coordinates>{_kml_coordinates([coordinate])}</coordinates></Point>"


def kml_multigeometry(*geometries: str) -> str:
    return f"<MultiGeometry>{''.join(geometries)}</MultiGeometry>"


def kml_placemark(name: str, geometry: str = "", data: Mapping[str, str] | None = None) -> str:
    extended = ""
    if data:
        items = "".join(
            f'<Data name="{key}"><value>{value}</value></Data>' for key, value in data.items()
        )
        extended = f"<ExtendedData>{items}</ExtendedData>"
    return f"<Placemark><name>{name}</name>{extended}{geometry}</Placemark>"


def kml_folder(name: str, *placemarks: str) -> str:
    return f"<Folder><name>{name}</name>{''.join(placemarks)}</Folder>"


def kml_document(*children: str) -> bytes:
    body = "".join(children)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2">'
        f"<Document><name>test</name>{body}</Document></kml>"
    ).encode()


def mixed_kml() -> bytes:
    """Polygon (1 km²), LineString (5 km) and Point, in that order."""
    return kml_document(
        kml_placemark("Parcel A", kml_polygon(SQUARE_UTM), {"owner": "Asha", "zone": "R1"}),
        kml_placemark("Access road", kml_linestring(LINE_UTM)),
        kml_placemark("Survey marker", kml_point(POINT_UTM)),
    )


# -- Shapefile ZIPs -------------------------------------------------------------


def shapefile_zip(
    gdf: gpd.GeoDataFrame,
    *,
    name: str = "layer",
    omit: Iterable[str] = (),
    folder: str = "",
    overrides: Mapping[str, bytes] | None = None,
    extra_members: Mapping[str, bytes] | None = None,
) -> bytes:
    """Write ``gdf`` as a Shapefile and return it zipped.

    ``omit`` drops components by extension (e.g. ``{".prj"}``); ``overrides``
    replaces a component's bytes; ``extra_members`` adds arbitrary entries.
    """
    omit = {extension.lower() for extension in omit}
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory() as temp_dir:
        gdf.to_file(Path(temp_dir) / f"{name}.shp", driver="ESRI Shapefile", engine="pyogrio")
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for component in sorted(Path(temp_dir).iterdir()):
                if component.suffix.lower() in omit:
                    continue
                content = (overrides or {}).get(component.suffix.lower(), component.read_bytes())
                archive.writestr(f"{folder}{component.name}", content)
            for member_name, content in (extra_members or {}).items():
                archive.writestr(member_name, content)
    return buffer.getvalue()


def raw_zip(members: Mapping[str, bytes]) -> bytes:
    """Build a ZIP from explicit member names, without any path sanitising."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for member_name, content in members.items():
            archive.writestr(member_name, content)
    return buffer.getvalue()


def shapefile_members(gdf: gpd.GeoDataFrame, name: str = "layer") -> dict[str, bytes]:
    """Return the component files of a Shapefile as ``{filename: bytes}``."""
    with zipfile.ZipFile(io.BytesIO(shapefile_zip(gdf, name=name))) as archive:
        return {member: archive.read(member) for member in archive.namelist()}
