"""Validation of uploaded files by name and by actual content."""

import re
import zipfile
from pathlib import Path

from app.core.enums import FileType
from app.core.exceptions import InvalidArchiveError, InvalidFileError, UnsupportedFileFormatError

EXTENSION_TO_FILE_TYPE: dict[str, FileType] = {
    ".kml": FileType.KML,
    ".zip": FileType.SHAPEFILE,
}
STORAGE_EXTENSION: dict[FileType, str] = {
    file_type: extension for extension, file_type in EXTENSION_TO_FILE_TYPE.items()
}

MAX_FILENAME_LENGTH = 255
FALLBACK_FILENAME = "upload"
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06")
KML_SNIFF_BYTES = 8192
KML_ROOT_MARKER = "<kml"
UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_filename(filename: str | None) -> str:
    """Reduce a client-supplied filename to a safe display name.

    The result is only ever stored as metadata; it is never used to build a
    path on the server.
    """
    name = re.split(r"[\\/]", filename or "")[-1]
    name = _CONTROL_CHARACTERS.sub("", name).strip()
    return name[:MAX_FILENAME_LENGTH] or FALLBACK_FILENAME


def detect_file_type(filename: str) -> FileType:
    """Map the filename extension to a supported file type."""
    file_type = EXTENSION_TO_FILE_TYPE.get(Path(filename).suffix.lower())
    if file_type is None:
        raise UnsupportedFileFormatError()
    return file_type


def verify_file_content(path: Path, file_type: FileType) -> None:
    """Check that the stored bytes actually look like the declared format."""
    with path.open("rb") as handle:
        head = handle.read(KML_SNIFF_BYTES)

    if file_type is FileType.SHAPEFILE:
        if not head.startswith(ZIP_SIGNATURES) or not zipfile.is_zipfile(path):
            raise InvalidArchiveError()
        return

    if KML_ROOT_MARKER not in _decode_head(head).lower():
        raise InvalidFileError("The uploaded file does not look like a KML document.")


def _decode_head(head: bytes) -> str:
    encoding = "utf-16" if head.startswith(UTF16_BOMS) else "utf-8"
    return head.decode(encoding, errors="ignore")
