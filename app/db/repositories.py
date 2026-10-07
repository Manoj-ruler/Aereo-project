"""Database access for files and their per-feature measurements."""

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import FileStatus, FileType
from app.db.models import FeatureMeasurement, FileRecord


class FileRepository:
    """All SQL for the ``files`` and ``measurements`` tables lives here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, *, file_id: str, filename: str, file_type: FileType, size_bytes: int
    ) -> FileRecord:
        record = FileRecord(
            id=file_id,
            filename=filename,
            file_type=file_type.value,
            size_bytes=size_bytes,
            status=FileStatus.PROCESSING.value,
        )
        self._session.add(record)
        self._session.commit()
        return record

    def get(self, file_id: str) -> FileRecord | None:
        return self._session.get(FileRecord, file_id)

    def mark_completed(
        self,
        record: FileRecord,
        *,
        source_crs: str,
        measurement_crs: str | None,
        measurements: Iterable[FeatureMeasurement],
    ) -> FileRecord:
        record.measurements = list(measurements)
        record.feature_count = len(record.measurements)
        record.source_crs = source_crs
        record.measurement_crs = measurement_crs
        record.status = FileStatus.COMPLETED.value
        record.error_message = None
        record.processed_at = datetime.now(UTC)
        self._session.commit()
        return record

    def mark_failed(self, record: FileRecord, error_message: str) -> FileRecord:
        self._session.rollback()
        record.status = FileStatus.FAILED.value
        record.error_message = error_message
        record.processed_at = datetime.now(UTC)
        self._session.commit()
        return record

    def list_measurements(self, file_id: str) -> list[FeatureMeasurement]:
        statement = (
            select(FeatureMeasurement)
            .where(FeatureMeasurement.file_id == file_id)
            .order_by(FeatureMeasurement.feature_index)
        )
        return list(self._session.scalars(statement))

    def count_by_status(self, file_id: str) -> dict[str, int]:
        statement = (
            select(FeatureMeasurement.status, func.count())
            .where(FeatureMeasurement.file_id == file_id)
            .group_by(FeatureMeasurement.status)
        )
        return {status: count for status, count in self._session.execute(statement)}
