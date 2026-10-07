"""Upload handling: validation, storage, processing orchestration and lookups."""

import logging
import uuid
from pathlib import Path
from typing import BinaryIO

from app.core.config import Settings
from app.core.enums import FileStatus, FileType
from app.core.exceptions import (
    AppError,
    FileNotProcessedError,
    FileRecordNotFoundError,
    FileTooLargeError,
    InvalidFileError,
    ProcessingError,
)
from app.db.models import FeatureMeasurement, FileRecord
from app.db.repositories import FileRepository
from app.services import geospatial_service
from app.services.geospatial_service import ProcessingResult
from app.utils.file_validation import (
    STORAGE_EXTENSION,
    detect_file_type,
    sanitize_filename,
    verify_file_content,
)

logger = logging.getLogger(__name__)

UPLOAD_CHUNK_BYTES = 1024 * 1024


class FileService:
    def __init__(self, repository: FileRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    # -- upload -----------------------------------------------------------------

    def ingest(self, stream: BinaryIO, original_filename: str | None) -> FileRecord:
        """Validate and store an upload, then process it synchronously.

        Storing/registering (:meth:`_register`) and processing (:meth:`process`)
        are separate steps so processing can later move to a background worker
        without changing either of them.
        """
        record, stored_path = self._register(stream, original_filename)
        return self.process(record, stored_path)

    def process(self, record: FileRecord, stored_path: Path) -> FileRecord:
        """Run the geospatial pipeline and persist its outcome on the record."""
        logger.info("File processing started: file_id=%s type=%s", record.id, record.file_type)
        try:
            result = geospatial_service.process_file(
                stored_path, FileType(record.file_type), self._settings
            )
            record = self._repository.mark_completed(
                record,
                source_crs=result.source_crs,
                measurement_crs=result.measurement_crs,
                measurements=_to_rows(result),
            )
        except AppError as exc:
            logger.warning("File processing failed: file_id=%s code=%s", record.id, exc.code)
            self._fail(record, stored_path, exc.detail)
            exc.file_id = record.id
            raise
        except Exception as exc:
            logger.exception("File processing crashed: file_id=%s", record.id)
            self._fail(record, stored_path, ProcessingError.default_detail)
            raise ProcessingError(file_id=record.id) from exc

        logger.info(
            "File processing completed: file_id=%s features=%d", record.id, record.feature_count
        )
        return record

    def _fail(self, record: FileRecord, stored_path: Path, message: str) -> None:
        """Record the failure and discard the upload; unusable files are not retained."""
        self._repository.mark_failed(record, message)
        stored_path.unlink(missing_ok=True)

    def _register(self, stream: BinaryIO, original_filename: str | None) -> tuple[FileRecord, Path]:
        filename = sanitize_filename(original_filename)
        logger.info("File upload started: filename=%r", filename)
        file_type = detect_file_type(filename)

        file_id = str(uuid.uuid4())
        # The stored name is derived from the generated ID, never from client input.
        stored_path = self._settings.storage_dir / f"{file_id}{STORAGE_EXTENSION[file_type]}"
        try:
            size_bytes = self._store(stream, stored_path)
            verify_file_content(stored_path, file_type)
        except AppError:
            stored_path.unlink(missing_ok=True)
            raise

        record = self._repository.create(
            file_id=file_id, filename=filename, file_type=file_type, size_bytes=size_bytes
        )
        logger.info(
            "File accepted: file_id=%s type=%s size_bytes=%d", file_id, file_type.value, size_bytes
        )
        return record, stored_path

    def _store(self, stream: BinaryIO, destination: Path) -> int:
        """Stream the upload to disk, enforcing the size limit as bytes arrive."""
        limit = self._settings.max_upload_size_bytes
        destination.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with destination.open("wb") as sink:
            while chunk := stream.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > limit:
                    raise FileTooLargeError(
                        "The uploaded file exceeds the maximum allowed size of "
                        f"{self._settings.max_upload_size_mb} MB."
                    )
                sink.write(chunk)
        if size == 0:
            raise InvalidFileError("The uploaded file is empty.")
        return size

    # -- lookups ----------------------------------------------------------------

    def get_file(self, file_id: str) -> FileRecord:
        record = self._repository.get(file_id)
        if record is None:
            raise FileRecordNotFoundError()
        return record

    def get_status_counts(self, file_id: str) -> dict[str, int]:
        return self._repository.count_by_status(file_id)

    def get_features(self, file_id: str) -> tuple[FileRecord, list[FeatureMeasurement]]:
        """Return a successfully processed file together with its per-feature rows."""
        record = self.get_file(file_id)
        if record.status != FileStatus.COMPLETED.value:
            reason = record.error_message or "processing has not finished."
            raise FileNotProcessedError(
                f"No results are available for this file (status: {record.status}). {reason}",
                file_id=record.id,
            )
        return record, self._repository.list_measurements(file_id)


def _to_rows(result: ProcessingResult) -> list[FeatureMeasurement]:
    return [
        FeatureMeasurement(
            feature_index=feature.index,
            geometry_type=feature.geometry_type,
            measurement_type=feature.measurement.measurement_type,
            measurement_value=feature.measurement.value,
            measurement_unit=feature.measurement.unit,
            status=feature.measurement.status.value,
            message=feature.measurement.message,
            properties_json=feature.properties,
            geometry_json=feature.geometry,
        )
        for feature in result.features
    ]
