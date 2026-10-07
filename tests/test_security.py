"""Hostile uploads: archive attacks, size limits and information leaks."""

import io
import stat
import zipfile
from pathlib import Path

import pytest

from app.core.exceptions import InvalidArchiveError, UnsafeArchiveError
from app.utils.zip_utils import extract_shapefile_archive
from tests.fixtures import builders

BYTES_PER_MB = 1024 * 1024


def _extract(content: bytes, tmp_path: Path, **limits) -> tuple[list[Path], Path]:
    archive = tmp_path / "upload.zip"
    archive.write_bytes(content)
    destination = tmp_path / "extracted"
    destination.mkdir()
    limits = {"max_files": 10, "max_uncompressed_bytes": BYTES_PER_MB} | limits
    return extract_shapefile_archive(archive, destination, **limits), destination


def _all_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


def _symlink_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("layer.shp")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


class TestArchiveAttacksThroughApi:
    @pytest.mark.parametrize(
        "member",
        [
            "../evil.shp",
            "../../../../tmp/evil.shp",
            "data/../../evil.shp",
            "/etc/evil.shp",
            "..\\..\\evil.shp",
            "C:\\Windows\\evil.shp",
        ],
    )
    def test_path_traversal_and_absolute_paths_are_rejected(
        self, upload, polygons_wgs84, tmp_path, member
    ):
        members = builders.shapefile_members(polygons_wgs84) | {member: b"payload"}

        response = upload("attack.zip", builders.raw_zip(members))

        assert response.status_code == 400
        assert response.json()["code"] == "unsafe_archive"
        assert not list(tmp_path.rglob("evil.shp"))

    def test_symlink_member_is_rejected(self, upload):
        response = upload("link.zip", _symlink_zip())

        assert response.status_code == 400
        assert response.json()["code"] == "unsafe_archive"

    def test_nested_archive_is_rejected(self, upload, polygons_wgs84):
        inner = builders.shapefile_zip(polygons_wgs84)
        members = builders.shapefile_members(polygons_wgs84) | {"more/inner.zip": inner}

        response = upload("nested.zip", builders.raw_zip(members))

        assert response.status_code == 400
        assert "Nested archives" in response.json()["detail"]

    def test_too_many_members_are_rejected(self, upload, settings):
        members = {f"file_{i}.txt": b"x" for i in range(settings.max_zip_files + 1)}

        response = upload("many.zip", builders.raw_zip(members))

        assert response.status_code == 400
        assert "too many files" in response.json()["detail"]

    def test_decompression_bomb_is_rejected(self, upload, settings):
        """A few KB on the wire that would inflate past MAX_ZIP_UNCOMPRESSED_MB."""
        bomb = builders.raw_zip({"layer.dbf": b"\x00" * (settings.max_zip_uncompressed_bytes + 1)})
        assert len(bomb) < settings.max_upload_size_bytes

        response = upload("bomb.zip", bomb)

        assert response.status_code == 400
        assert "too large when uncompressed" in response.json()["detail"]

    def test_malicious_archive_is_recorded_as_failed(self, client, upload):
        response = upload("attack.zip", builders.raw_zip({"../evil.shp": b"payload"}))

        info = client.get(f"/api/files/{response.json()['file_id']}/").json()

        assert info["status"] == "FAILED"
        assert info["feature_count"] == 0

    def test_rejected_archive_is_not_kept_in_storage(self, upload, settings):
        upload("attack.zip", builders.raw_zip({"../evil.shp": b"payload"}))

        assert list(settings.storage_dir.iterdir()) == []


class TestUploadLimits:
    def test_oversized_upload_is_rejected(self, upload, settings):
        content = b"<kml>" + b" " * settings.max_upload_size_bytes

        response = upload("big.kml", content)

        assert response.status_code == 413
        assert response.json()["code"] == "file_too_large"
        assert list(settings.storage_dir.iterdir()) == []

    def test_declared_content_length_is_rejected_before_reading(self, client, settings):
        oversized = settings.max_upload_size_bytes + 2 * BYTES_PER_MB

        response = client.post(
            "/api/files/",
            content=b"",
            headers={
                "content-type": "multipart/form-data; boundary=x",
                "content-length": str(oversized),
            },
        )

        assert response.status_code == 413

    def test_upload_at_the_limit_is_accepted_for_processing(self, upload, settings):
        """Exactly MAX bytes passes the size check (and then fails as non-KML data)."""
        content = b"<kml>" + b" " * (settings.max_upload_size_bytes - 5)

        assert upload("edge.kml", content).status_code == 422


class TestNoInformationLeaks:
    def test_error_responses_do_not_expose_server_paths(self, upload, settings, polygons_wgs84):
        responses = [
            upload("broken.kml", b"<kml><Document><Placemark><Polygon>"),
            upload("data.zip", b"not a zip"),
            upload("parcels.zip", builders.shapefile_zip(polygons_wgs84, omit={".shx"})),
            upload("parcels.zip", builders.shapefile_zip(polygons_wgs84, omit={".prj"})),
            upload(
                "corrupt.zip",
                builders.shapefile_zip(polygons_wgs84, overrides={".shp": b"\x00" * 64}),
            ),
        ]

        for response in responses:
            assert response.status_code in (400, 422)
            text = response.text
            assert str(settings.storage_dir) not in text
            assert "/tmp" not in text
            assert "Traceback" not in text

    def test_unexpected_errors_return_a_generic_500(self, settings, monkeypatch):
        from fastapi.testclient import TestClient

        from app.main import create_app
        from app.services import geospatial_service

        def explode(*_args, **_kwargs):
            raise RuntimeError("secret internal detail at /srv/app/private")

        monkeypatch.setattr(geospatial_service, "process_file", explode)
        with TestClient(create_app(settings), raise_server_exceptions=False) as client:
            response = client.post(
                "/api/files/", files={"file": ("survey.kml", builders.mixed_kml())}
            )
            info = client.get(f"/api/files/{response.json()['file_id']}/").json()

        assert response.status_code == 500
        assert response.json()["code"] == "processing_failed"
        assert "secret" not in response.text
        assert info["status"] == "FAILED"
        assert "secret" not in info["error_message"]


class TestExtractShapefileArchive:
    def test_only_shapefile_components_are_written_to_disk(self, tmp_path, polygons_wgs84):
        content = builders.shapefile_zip(
            polygons_wgs84,
            extra_members={
                "run.sh": b"#!/bin/sh\nrm -rf /",
                "tool.exe": b"MZ",
                "notes.txt": b"hello",
                "__MACOSX/._layer.shp": b"junk",
            },
        )

        extracted, destination = _extract(content, tmp_path)

        written = sorted(path.name for path in _all_files(destination))
        assert written == ["layer.cpg", "layer.dbf", "layer.prj", "layer.shp", "layer.shx"]
        assert sorted(path.name for path in extracted) == written

    def test_traversal_writes_nothing_anywhere(self, tmp_path, polygons_wgs84):
        members = builders.shapefile_members(polygons_wgs84) | {"../escaped.shp": b"payload"}

        with pytest.raises(UnsafeArchiveError):
            _extract(builders.raw_zip(members), tmp_path)

        assert not (tmp_path / "escaped.shp").exists()
        assert _all_files(tmp_path / "extracted") == []

    def test_byte_budget_is_enforced_on_real_decompressed_size(self, tmp_path):
        """The declared size in the ZIP header is forged to look tiny."""
        content = bytearray(builders.raw_zip({"layer.dbf": b"\x00" * (2 * BYTES_PER_MB)}))
        real_size = (2 * BYTES_PER_MB).to_bytes(4, "little")
        forged_size = (10).to_bytes(4, "little")
        assert content.count(real_size) == 2  # local header + central directory
        forged = bytes(content).replace(real_size, forged_size)

        with pytest.raises((UnsafeArchiveError, InvalidArchiveError)):
            _extract(forged, tmp_path, max_uncompressed_bytes=BYTES_PER_MB)

        written = _all_files(tmp_path / "extracted")
        assert sum(path.stat().st_size for path in written) <= BYTES_PER_MB

    def test_duplicate_member_names_are_rejected(self, tmp_path):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("layer.shp", b"one")
            archive.writestr("LAYER.SHP", b"two")

        with pytest.raises(UnsafeArchiveError):
            _extract(buffer.getvalue(), tmp_path)

    def test_corrupted_member_data_is_an_invalid_archive(self, tmp_path):
        payload = bytes(range(256)) * 64
        content = bytearray(builders.raw_zip({"layer.dbf": payload}))
        for offset in range(40, 60):  # damage the compressed stream
            content[offset] ^= 0xFF

        with pytest.raises(InvalidArchiveError):
            _extract(bytes(content), tmp_path)
