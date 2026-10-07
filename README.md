# Geospatial File Measurement API

## Overview

A FastAPI backend that accepts a geospatial file (**KML** or a **zipped Shapefile**),
extracts its features, and returns per-feature measurements:

- **Polygon** → area in **m²**
- **LineString** → length in **m**
- **Point** → no measurement

Files in geographic coordinates (latitude/longitude, e.g. `EPSG:4326`) are never
measured in degrees. Geometries are first transformed to a suitable projected CRS
(the local UTM zone), and every result is reported in metres.

## Problem Statement

Build a backend service that accepts a geospatial file, processes the features in
it and returns measurement information. For every feature the service must
identify its ID/index, geometry type, geometry, CRS and properties; calculate area
for polygons and length for lines; handle unsupported geometry types gracefully;
and handle geographic CRSs correctly by projecting before measuring.

## Features

**Implemented**

- Upload of `.kml` files and `.zip` archives containing one Shapefile
- Feature extraction: index, geometry type, GeoJSON-style geometry, CRS, attributes
- Area (m²) for Polygon / MultiPolygon, length (m) for LineString / MultiLineString
- Explicit per-feature statuses for points, unsupported, invalid and empty geometries
- CRS-aware measurement: automatic UTM zone selection for geographic data,
  unit conversion for projected CRSs that are not in metres
- Persistence of file metadata, features and measurements in SQLite
- Processing status (`PROCESSING` / `COMPLETED` / `FAILED`) with stored error message
- Hardened uploads: size limits, content sniffing, safe ZIP extraction
- Consistent JSON error responses, structured server-side logging
- OpenAPI / Swagger documentation at `/docs`
- Pytest suite with programmatically generated geospatial fixtures
- Docker image and Compose file

Not implemented (see [Future Scope](#future-scope)): authentication, background
processing, pagination, PostGIS, additional formats.

## Tech Stack

| Concern            | Choice                                              |
| ------------------ | --------------------------------------------------- |
| Language           | Python 3.11+ (developed on 3.12)                    |
| Web framework      | FastAPI + Uvicorn                                   |
| Geospatial I/O     | GeoPandas with the Pyogrio engine (GDAL)            |
| Geometry           | Shapely 2 (GEOS)                                    |
| CRS / reprojection | PyProj (PROJ)                                       |
| Persistence        | SQLAlchemy 2 + SQLite                               |
| Configuration      | pydantic-settings (environment variables / `.env`)  |
| Tests / lint       | Pytest, Ruff                                        |
| Packaging          | `pyproject.toml`, Docker                            |

## Architecture

A layered design: thin routes → services → repositories, with a pure geospatial
pipeline in the middle that knows nothing about HTTP or the database.

```
HTTP request
    │
    ▼
api/routes ──────────── thin handlers: parse request, call service, shape response
    │
    ▼
services/file_service ─ orchestration: validate → store → record → process → persist
    │                                                   │
    │                                                   ▼
    │                                        db/repositories ── SQLite
    ▼
services/geospatial_service ── pure pipeline (file path in, result object out)
    ├── kml_service / shapefile_service   read file → GeoDataFrame
    ├── crs_service                       choose measurement CRS, reproject
    └── measurement_service               area / length per geometry
```

### File-processing flow

```
POST /api/files/
  1. sanitise filename, map extension → file type            (400 if unsupported)
  2. stream body to storage as <uuid>.<ext>, enforcing size  (413 if too large)
  3. sniff content: ZIP signature / KML root element         (400 if mismatch)
  4. insert `files` row with status PROCESSING
  5. read features
       KML       → all layers (document + folders) via GDAL
       Shapefile → validate archive members, extract Shapefile components to a
                   temporary directory, require .shp/.shx/.dbf/.prj, read, clean up
  6. choose measurement CRS, reproject, measure each feature
  7. store one `measurements` row per feature; status → COMPLETED
     on any failure: status → FAILED + error message, stored upload is deleted
```

### Measurement calculation flow

```
GeoDataFrame ──► crs_service.plan_measurement ──► MeasurementPlan
                                                     │  (measurement CRS + unit→metre factor)
                                                     ▼
              GeoSeries.to_crs(measurement CRS)   (one vectorised reprojection)
                                                     ▼
              for each geometry (isolated from the others):
                 null / empty                  → NO_GEOMETRY
                 Point, MultiPoint             → NOT_REQUIRED
                 LineString, MultiLineString   → length × factor      → MEASURED (m)
                 Polygon, MultiPolygon
                     invalid                   → INVALID_GEOMETRY
                     valid                     → area × factor²       → MEASURED (m²)
                 anything else                 → UNSUPPORTED
```

## Project Structure

```
app/
├── main.py                  application factory, middleware, router wiring
├── api/
│   ├── dependencies.py      settings / session / service injection
│   └── routes/
│       ├── files.py         upload, file info, features
│       └── measurements.py  measurements
├── core/
│   ├── config.py            environment-driven settings
│   ├── enums.py             FileType, FileStatus, MeasurementStatus, ...
│   ├── exceptions.py        domain errors + JSON exception handlers
│   └── logging.py
├── db/
│   ├── database.py          engine / session factory
│   ├── models.py            `files` and `measurements` tables
│   └── repositories.py      all SQL
├── schemas/                 Pydantic response models
├── services/
│   ├── file_service.py      upload orchestration and lookups
│   ├── geospatial_service.py  file → features + measurements pipeline
│   ├── kml_service.py
│   ├── shapefile_service.py
│   ├── crs_service.py       measurement-CRS selection (single source of truth)
│   └── measurement_service.py
└── utils/
    ├── file_validation.py   extension + content checks, filename sanitising
    ├── zip_utils.py         safe archive extraction
    └── serialization.py     NumPy / pandas / Shapely → JSON
tests/                       pytest suite (fixtures built in tests/fixtures/builders.py)
samples/                     small KML and Shapefile ZIP for manual testing
```

## Supported File Formats

| Upload | Requirements |
| ------ | ------------ |
| `.kml` | A KML document. Placemarks from the document root and from every `<Folder>` are read, in document order. |
| `.zip` | Exactly one Shapefile: `.shp`, `.shx`, `.dbf` and `.prj` with the same base name (optionally inside a folder). Other sidecar files (`.cpg`, `.sbn`, ...) are used if present; unrelated files are ignored and never extracted. |

Rejected with a clear error: any other extension (including `.kmz`), a ZIP with no
`.shp`, with several `.shp` files (the service does not guess which one you meant),
or with a missing `.shx` / `.dbf` / `.prj`.

## Supported Geometry Types

| Geometry type             | Measurement | Unit | `status`           |
| ------------------------- | ----------- | ---- | ------------------ |
| Polygon                   | area        | m²   | `MEASURED`         |
| MultiPolygon *(extra)*    | total area  | m²   | `MEASURED`         |
| LineString                | length      | m    | `MEASURED`         |
| MultiLineString *(extra)* | total length| m    | `MEASURED`         |
| Point, MultiPoint         | —           | —    | `NOT_REQUIRED`     |
| GeometryCollection, other | —           | —    | `UNSUPPORTED`      |
| Invalid polygon           | —           | —    | `INVALID_GEOMETRY` |
| Null / empty geometry     | —           | —    | `NO_GEOMETRY`      |

Polygon holes are subtracted from the area. A feature that cannot be measured gets
a status and a `message`; it never causes the request, or other features, to fail.

**Invalid geometries.** A self-intersecting polygon has no well-defined area
(GEOS would return a number in which overlapping parts cancel out). Such features
are reported as `INVALID_GEOMETRY` with the reason, and are **not** repaired:
`make_valid`/`buffer(0)` can change the shape — and therefore the area — in ways
the uploader did not intend, so silently "fixing" survey data was judged worse
than reporting it.

## CRS Handling

Longitude/latitude are angles. `geometry.area` on EPSG:4326 coordinates returns
"square degrees", which is meaningless — and a degree of longitude does not even
have a constant size. The service therefore only ever measures in a projected CRS.
All CRS decisions live in one module, `app/services/crs_service.py`:

| Source CRS                                   | Measurement CRS                         |
| -------------------------------------------- | --------------------------------------- |
| Geographic (EPSG:4326, EPSG:4269, ...)       | Local UTM zone estimated from the data extent (`GeoDataFrame.estimate_utm_crs()`), e.g. `EPSG:32644` |
| Projected, e.g. UTM or a national grid       | The source CRS itself (no reprojection) |
| Projected but not in metres (e.g. US feet)   | The source CRS; results converted to metres using the CRS's unit factor |
| Web Mercator (EPSG:3857)                     | Treated like geographic → local UTM zone, because Web Mercator inflates areas by 1/cos²(latitude) (≈4× at 60°N) |
| Missing (no `.prj`)                          | `422 missing_crs` — the CRS is never guessed |
| Unparseable `.prj`                           | `422 invalid_crs` |
| Neither geographic nor projected (geocentric)| `422 invalid_crs` |
| Coordinates impossible for the declared CRS  | `422 crs_transformation_failed` |

Both CRSs are stored and returned: `crs` (source) and `measurement_crs`.

The KML standard mandates WGS84, but the service uses the CRS reported by the
parser rather than hard-coding it. As a last line of defence, the reprojection
step refuses to hand geometries to the measurement code unless the target CRS is
projected, so a future bug in CRS selection cannot result in degree-based numbers.

## Measurement Strategy

- **Why UTM.** UTM is conformal, metric and defined for the whole globe, and its
  scale error stays within roughly ±0.1 % inside a zone (−0.04 % on the central
  meridian) — so it can be selected automatically for any location with good
  accuracy for parcel/route-sized features.
- **One zone per file.** The zone is estimated once from the extent of the whole
  dataset, which keeps `measurement_crs` a single, explainable value per file.
- **Accuracy.** The test-suite checks results against both exactly-known shapes
  (a 1 km × 1 km square, a 5 km line) and independent geodesic calculations on
  the WGS84 ellipsoid (`pyproj.Geod`): lengths agree within 0.1 %, areas within 0.2 %.
- **Units.** Values are always metres / square metres, with the unit in the
  response. Raw, un-rounded floats are returned; rounding is left to the client.
- **Planar, 2-D.** Z coordinates are ignored for measurement.

## API Documentation

Interactive documentation is generated by FastAPI:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI schema: `http://localhost:8000/openapi.json`

| Method | Path                               | Purpose                                   |
| ------ | ---------------------------------- | ----------------------------------------- |
| POST   | `/api/files/`                      | Upload and process a file                 |
| GET    | `/api/files/{id}/`                 | File information and processing status    |
| GET    | `/api/files/{id}/measurements/`    | Per-feature measurements                  |
| GET    | `/api/files/{id}/features/`        | Per-feature geometry and properties *(extra)* |
| GET    | `/health`                          | Liveness check *(extra)*                  |

## POST /api/files/

Uploads and processes a file. `multipart/form-data` with one field, `file`.

Processing is synchronous, so the `201 Created` response already contains the
final status. The response body is the same object as `GET /api/files/{id}/`.

## GET /api/files/{id}/

Returns information about an uploaded file: name, type, feature count, source
CRS, measurement CRS, status, and a count of features per measurement status.
Files whose processing failed are returned too, with `status: "FAILED"` and an
`error_message`.

## GET /api/files/{id}/measurements/

Returns one entry per feature, in file order: geometry type, measurement type,
value, unit, status and the feature's properties. `feature_id` is the zero-based
index of the feature in the file. Returns `409` if the file was not processed
successfully.

`GET /api/files/{id}/features/` complements it with the full GeoJSON-style
geometry of each feature (in the source CRS), keeping the measurements response
small.

## Example Requests

Sample files are included in [`samples/`](samples/).

```bash
curl -F "file=@samples/sample.kml" http://localhost:8000/api/files/
```

```bash
curl -F "file=@samples/sample_shapefile.zip" http://localhost:8000/api/files/
```

```bash
curl http://localhost:8000/api/files/<id>/
```

```bash
curl http://localhost:8000/api/files/<id>/measurements/
```

```bash
curl http://localhost:8000/api/files/<id>/features/
```

## Example Responses

`POST /api/files/` → `201 Created` (and `GET /api/files/{id}/` → `200 OK`)

```json
{
  "id": "1f8c4dd1-8105-46b3-b381-f8140d9fe68a",
  "filename": "sample.kml",
  "file_type": "kml",
  "size_bytes": 819,
  "feature_count": 3,
  "crs": "EPSG:4326",
  "measurement_crs": "EPSG:32644",
  "status": "COMPLETED",
  "error_message": null,
  "measurement_summary": { "MEASURED": 2, "NOT_REQUIRED": 1 },
  "created_at": "2026-10-07T12:13:56.597982Z",
  "processed_at": "2026-10-07T12:13:56.763083Z"
}
```

`GET /api/files/{id}/measurements/` → `200 OK` (properties shortened)

```json
{
  "file_id": "1f8c4dd1-8105-46b3-b381-f8140d9fe68a",
  "crs": "EPSG:4326",
  "measurement_crs": "EPSG:32644",
  "feature_count": 3,
  "features": [
    {
      "feature_id": 0,
      "geometry_type": "Polygon",
      "measurement_type": "area",
      "value": 1000000.0045440393,
      "unit": "m²",
      "status": "MEASURED",
      "message": null,
      "properties": { "Name": "Parcel A", "owner": "Asha", "zone": "R1" }
    },
    {
      "feature_id": 1,
      "geometry_type": "LineString",
      "measurement_type": "length",
      "value": 5000.000004080333,
      "unit": "m",
      "status": "MEASURED",
      "message": null,
      "properties": { "Name": "Access road" }
    },
    {
      "feature_id": 2,
      "geometry_type": "Point",
      "measurement_type": null,
      "value": null,
      "unit": null,
      "status": "NOT_REQUIRED",
      "message": null,
      "properties": { "Name": "Survey marker" }
    }
  ]
}
```

`GET /api/files/{id}/features/` → `200 OK` (shortened)

```json
{
  "file_id": "1f8c4dd1-8105-46b3-b381-f8140d9fe68a",
  "crs": "EPSG:4326",
  "feature_count": 3,
  "features": [
    {
      "feature_id": 0,
      "geometry_type": "Polygon",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[80.0774532132, 13.1146755599, 0.0], [80.0866778506, 13.1147084301, 0.0], "..."]]
      },
      "properties": { "Name": "Parcel A", "owner": "Asha", "zone": "R1" }
    }
  ]
}
```

An unsupported geometry inside an otherwise valid file:

```json
{
  "feature_id": 1,
  "geometry_type": "GeometryCollection",
  "measurement_type": null,
  "value": null,
  "unit": null,
  "status": "UNSUPPORTED",
  "message": "Measurement is not supported for geometry type 'GeometryCollection'.",
  "properties": { "Name": "Mixed" }
}
```

## Error Responses

Every error has the same shape. `code` is stable and machine-readable; `file_id`
is present when the upload got far enough to be recorded (as `FAILED`).

```json
{
  "detail": "The Shapefile has no .prj file, so its source CRS could not be determined. Measurements cannot be calculated without a CRS.",
  "code": "missing_crs",
  "file_id": "93ee61b3-49fe-4436-9674-910b69298bfe"
}
```

| Status | `code`                       | When |
| ------ | ---------------------------- | ---- |
| 400    | `unsupported_file_format`    | Extension is not `.kml` or `.zip` |
| 400    | `invalid_file`               | Empty upload, or `.kml` content is not KML |
| 400    | `invalid_archive`            | Not a ZIP, empty, corrupted or encrypted ZIP |
| 400    | `unsafe_archive`             | Path traversal, absolute path, symlink, nested archive, too many files, decompression bomb |
| 404    | `file_not_found`             | Unknown file ID |
| 409    | `file_not_processed`         | Measurements/features requested for a `FAILED` file |
| 413    | `file_too_large`             | Upload larger than `MAX_UPLOAD_SIZE_MB` |
| 422    | `validation_error`           | Malformed request (e.g. no `file` field) |
| 422    | `invalid_shapefile`          | No `.shp`, several `.shp`, or missing `.shx` / `.dbf` |
| 422    | `unreadable_geospatial_file` | KML / Shapefile could not be parsed |
| 422    | `no_features`                | File contains no features |
| 422    | `missing_crs`                | Shapefile without `.prj` |
| 422    | `invalid_crs`                | Unparseable `.prj` or unsupported CRS type |
| 422    | `crs_transformation_failed`  | Coordinates cannot be projected (invalid for the declared CRS) |
| 500    | `processing_failed` / `internal_error` | Unexpected failure; details are logged, not returned |

Error messages never include stack traces or server filesystem paths.

## Local Setup

Requires Python 3.11 or newer. No system GDAL installation is needed: the
`pyogrio`, `shapely` and `pyproj` wheels ship their own GDAL / GEOS / PROJ.

```bash
git clone https://github.com/Manoj-ruler/Aereo-project.git
cd Aereo-project

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"

cp .env.example .env             # optional: all values have defaults

uvicorn app.main:app --reload
```

The API is then available at `http://localhost:8000` (docs at `/docs`).

Dependencies are declared in `pyproject.toml`; `pip install .` installs only the
runtime dependencies, `pip install -e ".[dev]"` adds pytest, httpx and ruff.

### Configuration

| Variable                  | Default                   | Meaning |
| ------------------------- | ------------------------- | ------- |
| `APP_ENV`                 | `development`             | Environment label (logged at start-up) |
| `DATABASE_URL`            | `sqlite:///./data/app.db` | SQLAlchemy database URL |
| `STORAGE_DIR`             | `./storage`               | Where uploaded files are kept |
| `MAX_UPLOAD_SIZE_MB`      | `25`                      | Maximum upload size |
| `MAX_ZIP_FILES`           | `100`                     | Maximum number of entries in a ZIP |
| `MAX_ZIP_UNCOMPRESSED_MB` | `200`                     | Maximum total uncompressed size of a ZIP |
| `LOG_LEVEL`               | `INFO`                    | Application log level |

## Docker Setup

```bash
docker compose up --build
```

The API listens on `http://localhost:8000`. The SQLite database and uploaded
files are kept in named volumes (`api-data`, `api-storage`). The image is based on
`python:3.12-slim`, installs the runtime dependencies from wheels (which bundle
GDAL, GEOS and PROJ, so no `apt-get install gdal` is required), and runs as a
non-root user.

Without Compose:

```bash
docker build -t geospatial-measurement-api .
docker run --rm -p 8000:8000 geospatial-measurement-api
```

## Running Tests

```bash
pytest
```

The suite (about 150 tests) builds its own KML files and Shapefile ZIPs from
shapes whose area and length are known exactly, and covers:

- **Upload** — valid KML / Shapefile, unsupported extensions, spoofed content
  types, empty / truncated / shapefile-less ZIPs, missing components
- **CRS** — EPSG:4326 is transformed and results are not in degrees, UTM zone
  follows the data (northern / southern hemisphere), projected CRSs are kept,
  foot-based CRSs are converted, Web Mercator is avoided, missing / invalid CRS
- **Measurements** — Polygon, LineString, Point, MultiPolygon, MultiLineString,
  holes, GeometryCollection, invalid polygons, features without geometry
- **API** — all endpoints, 404 / 409 behaviour, error shapes, OpenAPI schema
- **Security** — ZIP path traversal, absolute paths, symlinks, nested archives,
  decompression bombs (including forged size headers), oversized uploads,
  no path or exception leakage

Lint and formatting: `ruff check .` and `ruff format --check .`

## Design Decisions

**FastAPI rather than Django + DRF.** The service is a small JSON API with no
admin, templates or auth. FastAPI gives typed request/response models, automatic
OpenAPI docs and dependency injection with very little code. Django would add an
ORM-coupled project layout and, for spatial work, pushes toward GeoDjango/PostGIS,
which is more infrastructure than this problem needs.

**GeoPandas (Pyogrio engine).** One call reads both formats through GDAL into a
uniform table of geometries + attributes + CRS, and reprojection is vectorised.
Alternatives considered: Fiona (slower, lower-level, same GDAL underneath),
`pyshp` + hand-written KML parsing (no GDAL dependency, but two code paths and
re-implementing CRS/encoding handling), and calling `pyogrio` directly (viable,
but GeoPandas' `to_crs` / `estimate_utm_crs` are exactly what is needed).

**Shapely.** The standard GEOS binding: planar `area` / `length`, validity checks
with a reason, and GeoJSON output. It is already GeoPandas' geometry type.

**PyProj.** Authoritative CRS introspection (geographic vs projected, axis units,
projection method) and transformations via PROJ. Used directly for the decisions
GeoPandas does not make: unit conversion and Web Mercator detection.

**Local UTM zone rather than a fixed projected CRS.** A single global CRS cannot
be accurate everywhere; EPSG:3857 in particular is a visualisation projection
with severe area distortion. Alternatives considered:

- *Geodesic measurement on the ellipsoid* (`pyproj.Geod`) — the most accurate
  and zone-free, but the brief explicitly asks for transformation to a projected
  CRS. It is used in the tests as an independent reference instead.
- *Equal-area projection* (e.g. a Lambert azimuthal equal-area centred on the
  data) — exact areas but distorted lengths; UTM is a good compromise for both.
- *Per-feature UTM zones* — more accurate for datasets spanning many zones, at
  the cost of a different `measurement_crs` per feature. Left as future work.

**SQLite.** Zero-setup for a reviewer, and enough for metadata plus per-feature
rows. Access goes through SQLAlchemy and one repository class, so moving to
PostgreSQL is a `DATABASE_URL` change plus migrations. PostGIS was not added
because no spatial query is performed in the database.

**Synchronous processing.** Files within the upload limit are processed in well
under a second, so the client gets its result in one round trip, with no broker
or worker to run. Endpoints are plain `def` functions, so FastAPI runs the
blocking GeoPandas work in its thread pool rather than on the event loop. The
status model (`PROCESSING` → `COMPLETED` / `FAILED`) and the split between
registering an upload and processing it already match an asynchronous design:
`FileService.process()` could be handed to a worker and `POST` could return `202`.

**Temporary extraction directories.** A Shapefile must exist as real files for
GDAL. Extracting into a fresh `TemporaryDirectory` isolates each upload, makes
name collisions impossible and guarantees clean-up even when reading fails. Only
whitelisted Shapefile component files are ever written.

**GeoJSON-style geometry.** It is the de-facto JSON encoding for geometries,
directly usable by web maps and GIS tools, and trivially stored in a JSON column.
WKT/WKB would be more compact but need another parser on the client.

**Common multi-geometries.** Real Shapefiles routinely store parcels as
MultiPolygon and roads as MultiLineString (the Shapefile format does not even
distinguish single from multi parts), so treating them as "unsupported" would make
the service useless on ordinary data. The measurement is the same GEOS call.

**Other choices**

- *Upload response = file info.* Clients get the ID, CRSs and status immediately
  and fetch measurements separately, as the brief's endpoint list suggests.
- *Processing errors return an error status and keep a `FAILED` record.* The
  client gets a proper 4xx, while `GET /api/files/{id}/` still explains what
  happened. The unusable upload itself is deleted.
- *Unrelated files in a ZIP are ignored, not rejected.* Archives often carry a
  README or `__MACOSX` entries. They are never extracted, so they cost nothing;
  nested archives, symlinks and unsafe paths are rejected outright.
- *Separate `/features/` endpoint.* Geometries can be large; keeping them out of
  the measurements response keeps that response small.
- *Tables are created at start-up* (`create_all`). Adequate for one schema
  version; Alembic migrations belong with a move to PostgreSQL.

## Security Considerations

- **Size limits** — uploads are streamed to disk with the limit enforced as bytes
  arrive; requests declaring an oversized `Content-Length` are refused up front.
- **Content validation** — the `Content-Type` header is ignored. The extension
  selects the format, and the bytes must match it (ZIP signature / KML root).
- **Safe ZIP handling** — every member is validated before anything is written:
  no absolute paths, drive letters, `..` segments, symlinks, encrypted entries,
  nested archives or duplicate names; bounded member count; bounded uncompressed
  size, enforced on the bytes actually decompressed (declared sizes can be
  forged). Members are copied manually to a resolved path that must stay inside
  the temporary directory — `ZipFile.extractall` is not used.
- **No client-controlled paths** — files are stored as `<uuid>.<ext>`; the
  original filename is sanitised and kept only as metadata.
- **Nothing is executed** — uploaded content is only parsed by GDAL.
- **No information leakage** — domain errors carry curated messages; GDAL
  messages (which contain paths) and stack traces go to the server log only.
- **Non-guessable IDs** — random UUIDv4 identifiers.
- **Container** — runs as an unprivileged user.

Logs record upload/processing events, IDs, sizes and CRSs — never file contents
or geometries.

## Limitations

- One UTM zone is chosen per file. For a dataset spanning several zones (or very
  large single features) distortion grows away from the chosen zone; continental-scale
  data would need per-feature zones or geodesic measurement. Geographic data
  outside UTM's coverage (north of 84°N or south of 80°S) is rejected with
  `crs_transformation_failed`; it would need a polar (UPS) projection.
- Exactly one Shapefile per ZIP; `.kmz` and other formats are not supported.
- Processing is synchronous and loads the whole file into memory, so it is
  bounded by `MAX_UPLOAD_SIZE_MB` rather than designed for very large datasets.
  Starlette also spools the multipart body to a temporary file before the
  handler runs; a reverse proxy should enforce a body limit in production.
- Results are not paginated.
- KML layer/folder names are not exposed as an attribute; features of all
  folders are returned as one flat list. GDAL's KML driver adds its standard
  fields (`timestamp`, `tessellate`, ...) to every feature's properties.
- Invalid polygons are reported, not repaired.
- No authentication, authorisation or rate limiting.
- SQLite suits a single instance; there are no schema migrations.
- The Docker image relies on binary wheels being available for the platform
  (they are for Linux x86-64 and arm64).

## Learning

- **A projected CRS is not automatically a good measurement CRS.** Web Mercator
  is "projected, in metres" and still wrong by a factor of four at 60°N. Checking
  `is_projected` is not enough; the projection method matters.
- **Units are part of the CRS.** State Plane CRSs in US survey feet would silently
  produce square feet labelled as m² without reading the axis unit factor.
- **UTM is accurate but not exact.** Comparing against geodesic results made the
  0.9996 scale factor visible (≈0.08 % in area at the central meridian) and gave
  principled test tolerances instead of arbitrary ones.
- **KML is hierarchical.** GDAL exposes each folder as a layer, so a naive
  `read_file` returns only the first folder's placemarks — a silent data loss
  that only showed up when testing with a multi-folder document.
- **A missing or broken `.prj` yields `crs=None`, not an error**, so the absence
  of a CRS has to be checked explicitly and turned into a clear message.
- **ZIP metadata cannot be trusted.** Declared sizes can be forged and member
  names can point anywhere, so validation has to cover names, types and the
  number of bytes actually produced.
- **Geospatial values are not JSON.** NaT, NaN, NumPy scalars and dates all
  appear in attribute tables and need explicit normalisation.
- **Library error messages leak.** GDAL errors include absolute paths, so they
  must be logged and replaced rather than forwarded to clients.

## Future Scope

None of the following is implemented.

- **PostgreSQL / PostGIS** — native geometry columns, spatial indexes and
  spatial queries (bounding-box filters, intersections); Alembic migrations
- **Object storage (S3-compatible)** behind a storage interface, instead of local disk
- **Background processing** — return `202 Accepted` and process in a worker
  (Celery or RQ with Redis), with clients polling the status
- **Large files** — streaming / chunked feature reads instead of loading the
  whole dataset; resumable uploads
- **Multiple layers** — several Shapefiles per archive, KML folders exposed as
  named layers
- **Additional formats** — KMZ, GeoJSON, GeoPackage, GPX, FlatGeobuf
- **Measurement options** — client-selected CRS, geodesic measurement, per-feature
  UTM zones, alternative units (hectares, kilometres), perimeter, opt-in geometry repair
- **Pagination and filtering** of features and measurements; GeoJSON
  FeatureCollection export
- **Authentication, authorisation and rate limiting**
- **Operations** — file deletion / retention policy, metrics, request tracing
