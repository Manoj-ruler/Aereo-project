"""Reading KML documents into a GeoDataFrame."""

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
from pyogrio.errors import DataLayerError, DataSourceError

from app.core.exceptions import GeospatialReadError, NoFeaturesError

logger = logging.getLogger(__name__)


def read_kml(path: Path) -> gpd.GeoDataFrame:
    """Read every layer of a KML document into one GeoDataFrame.

    GDAL exposes the document and each ``<Folder>`` as separate layers; reading
    only the first would silently drop features, so all layers are
    concatenated in document order. The CRS is whatever the parser reports.
    """
    try:
        layer_names = [name for name, _geometry_type in pyogrio.list_layers(path)]
        frames = [gpd.read_file(path, layer=name, engine="pyogrio") for name in layer_names]
    except (DataSourceError, DataLayerError, ValueError) as exc:
        # GDAL messages include the server-side path, so they are logged, not returned.
        logger.warning("KML could not be parsed: %s", type(exc).__name__)
        raise GeospatialReadError("The file could not be parsed as a valid KML document.") from exc

    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise NoFeaturesError("The KML document does not contain any features.")
    if len(frames) == 1:
        return frames[0]

    crs = frames[0].crs
    aligned = [frame if frame.crs == crs else frame.to_crs(crs) for frame in frames]
    return gpd.GeoDataFrame(pd.concat(aligned, ignore_index=True), geometry="geometry", crs=crs)
