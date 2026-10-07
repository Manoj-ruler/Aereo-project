"""Reading a zipped Shapefile into a GeoDataFrame."""

import logging
import tempfile
from pathlib import Path

import geopandas as gpd
from pyogrio.errors import DataLayerError, DataSourceError

from app.core.config import Settings
from app.core.exceptions import (
    GeospatialReadError,
    InvalidCRSError,
    MissingCRSError,
    NoFeaturesError,
    ShapefileValidationError,
)
from app.utils.zip_utils import extract_shapefile_archive

logger = logging.getLogger(__name__)

SHAPEFILE_EXTENSION = ".shp"
REQUIRED_SIDECAR_EXTENSIONS = (".shx", ".dbf")
PROJECTION_EXTENSION = ".prj"
TEMP_DIR_PREFIX = "shapefile-"


def read_shapefile_zip(archive_path: Path, settings: Settings) -> gpd.GeoDataFrame:
    """Safely extract the archive to a temporary directory and read its Shapefile.

    The data is fully loaded into memory, and the temporary directory is
    removed before returning, whether or not reading succeeded.
    """
    with tempfile.TemporaryDirectory(prefix=TEMP_DIR_PREFIX) as temp_dir:
        extracted = extract_shapefile_archive(
            archive_path,
            Path(temp_dir),
            max_files=settings.max_zip_files,
            max_uncompressed_bytes=settings.max_zip_uncompressed_bytes,
        )
        shapefile = _locate_shapefile(extracted)
        gdf = _read(shapefile)

    if gdf.empty:
        raise NoFeaturesError("The Shapefile does not contain any features.")
    if gdf.crs is None:
        raise InvalidCRSError("The Shapefile's .prj file could not be interpreted as a valid CRS.")
    return gdf


def _locate_shapefile(extracted: list[Path]) -> Path:
    """Find the single ``.shp`` and check its required companion files exist."""
    shapefiles = [path for path in extracted if path.suffix.lower() == SHAPEFILE_EXTENSION]
    if not shapefiles:
        raise ShapefileValidationError("The ZIP archive does not contain a .shp file.")
    if len(shapefiles) > 1:
        raise ShapefileValidationError(
            f"The ZIP archive contains {len(shapefiles)} Shapefiles; "
            "exactly one .shp file is supported per upload."
        )

    shapefile = shapefiles[0]
    siblings = {
        path.suffix.lower()
        for path in extracted
        if path.parent == shapefile.parent and path.stem.lower() == shapefile.stem.lower()
    }
    missing = [ext for ext in REQUIRED_SIDECAR_EXTENSIONS if ext not in siblings]
    if missing:
        raise ShapefileValidationError(
            f"The Shapefile is incomplete: missing required {', '.join(missing)} file(s)."
        )
    if PROJECTION_EXTENSION not in siblings:
        raise MissingCRSError(
            "The Shapefile has no .prj file, so its source CRS could not be determined. "
            "Measurements cannot be calculated without a CRS."
        )
    return shapefile


def _read(shapefile: Path) -> gpd.GeoDataFrame:
    try:
        return gpd.read_file(shapefile, engine="pyogrio")
    except (DataSourceError, DataLayerError, ValueError, UnicodeDecodeError) as exc:
        logger.warning("Shapefile could not be read: %s", type(exc).__name__)
        raise GeospatialReadError("The Shapefile could not be read; it may be corrupted.") from exc
