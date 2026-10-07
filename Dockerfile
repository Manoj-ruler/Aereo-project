# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# No apt-get install of GDAL is needed: the pyogrio, shapely and pyproj wheels
# bundle their own GDAL, GEOS and PROJ libraries (including the KML and
# Shapefile drivers and the PROJ database).
COPY pyproject.toml README.md LICENSE ./
COPY app ./app
RUN pip install .

# Run as an unprivileged user that owns only the runtime data directories.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data /app/storage \
    && chown -R appuser:appuser /app/data /app/storage
USER appuser

ENV DATABASE_URL=sqlite:////app/data/app.db \
    STORAGE_DIR=/app/storage

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
