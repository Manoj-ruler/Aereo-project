"""SQLAlchemy ORM models."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.core.enums import FileStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetime. SQLite drops tzinfo, so it is restored on read."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class FileRecord(Base):
    """An uploaded geospatial file and the outcome of processing it."""

    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(Integer)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    source_crs: Mapped[str | None] = mapped_column(String(255))
    measurement_crs: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default=FileStatus.PROCESSING.value)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    measurements: Mapped[list["FeatureMeasurement"]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
        order_by="FeatureMeasurement.feature_index",
    )


class FeatureMeasurement(Base):
    """One feature of a file: its geometry, attributes and measurement."""

    __tablename__ = "measurements"
    __table_args__ = (UniqueConstraint("file_id", "feature_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    feature_index: Mapped[int] = mapped_column(Integer)
    geometry_type: Mapped[str | None] = mapped_column(String(32))
    measurement_type: Mapped[str | None] = mapped_column(String(16))
    measurement_value: Mapped[float | None] = mapped_column(Float)
    measurement_unit: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(24))
    message: Mapped[str | None] = mapped_column(Text)
    properties_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    geometry_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    file: Mapped[FileRecord] = relationship(back_populates="measurements")
