"""Safe extraction of uploaded Shapefile ZIP archives.

Nothing here trusts the archive: every member name is validated before any
byte is written, only Shapefile component files are extracted, and both the
member count and the real number of uncompressed bytes are bounded.
"""

import re
import stat
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from app.core.exceptions import InvalidArchiveError, UnsafeArchiveError

SHAPEFILE_COMPONENT_EXTENSIONS = frozenset(
    {
        ".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj",
        ".sbn", ".sbx", ".qix", ".fix", ".atx", ".aih", ".ain", ".xml",
    }
)  # fmt: skip
NESTED_ARCHIVE_EXTENSIONS = frozenset(
    {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar"}
)
IGNORED_DIRECTORIES = frozenset({"__MACOSX"})
ENCRYPTED_FLAG = 0x1
COPY_CHUNK_BYTES = 64 * 1024

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def _safe_relative_path(member_name: str) -> PurePosixPath:
    """Return the member's path, or raise if it could escape the target directory."""
    normalized = member_name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        "\x00" in normalized
        or normalized.startswith("/")
        or _WINDOWS_DRIVE.match(normalized)
        or ".." in path.parts
    ):
        raise UnsafeArchiveError("The ZIP archive contains an unsafe file path.")
    return path


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _validate_members(
    infos: list[zipfile.ZipInfo], *, max_files: int, max_uncompressed_bytes: int
) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    """Validate every member and return the Shapefile components to extract."""
    if not infos:
        raise InvalidArchiveError("The ZIP archive is empty.")
    if len(infos) > max_files:
        raise UnsafeArchiveError(f"The ZIP archive contains too many files (limit: {max_files}).")

    to_extract: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    seen: set[str] = set()
    for info in infos:
        path = _safe_relative_path(info.filename)
        if _is_symlink(info):
            raise UnsafeArchiveError("The ZIP archive contains a symbolic link.")
        if info.flag_bits & ENCRYPTED_FLAG:
            raise InvalidArchiveError("Encrypted ZIP archives are not supported.")
        suffix = path.suffix.lower()
        if suffix in NESTED_ARCHIVE_EXTENSIONS:
            raise UnsafeArchiveError("Nested archives are not allowed inside the ZIP.")
        if IGNORED_DIRECTORIES.intersection(path.parts) or suffix not in (
            SHAPEFILE_COMPONENT_EXTENSIONS
        ):
            continue  # not part of a Shapefile: never written to disk
        key = str(path).lower()
        if key in seen:
            raise UnsafeArchiveError("The ZIP archive contains duplicate file names.")
        seen.add(key)
        to_extract.append((info, path))

    if sum(info.file_size for info, _ in to_extract) > max_uncompressed_bytes:
        raise UnsafeArchiveError("The ZIP archive is too large when uncompressed.")
    return to_extract


def extract_shapefile_archive(
    archive_path: Path,
    destination: Path,
    *,
    max_files: int,
    max_uncompressed_bytes: int,
) -> list[Path]:
    """Extract only Shapefile component files into ``destination``.

    Returns the extracted paths. Raises :class:`InvalidArchiveError` for
    corrupt/empty archives and :class:`UnsafeArchiveError` for anything
    suspicious (path traversal, absolute paths, symlinks, nested archives,
    too many files, decompression bombs).
    """
    destination_root = destination.resolve()
    extracted: list[Path] = []
    remaining = max_uncompressed_bytes
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            members = _validate_members(
                infos, max_files=max_files, max_uncompressed_bytes=max_uncompressed_bytes
            )
            for info, relative_path in members:
                target = (destination_root / relative_path).resolve()
                if not target.is_relative_to(destination_root):
                    raise UnsafeArchiveError("The ZIP archive contains an unsafe file path.")
                target.parent.mkdir(parents=True, exist_ok=True)
                remaining = _copy_member(archive, info, target, remaining)
                extracted.append(target)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError) as exc:
        raise InvalidArchiveError("The ZIP archive is corrupted or unreadable.") from exc
    return extracted


def _copy_member(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path, remaining: int
) -> int:
    """Copy one member, enforcing the byte budget on what is really decompressed.

    The size declared in the ZIP header can lie, so the budget is checked
    against the bytes actually read. Returns the budget left.
    """
    with archive.open(info) as source, target.open("wb") as sink:
        while chunk := source.read(COPY_CHUNK_BYTES):
            remaining -= len(chunk)
            if remaining < 0:
                raise UnsafeArchiveError("The ZIP archive is too large when uncompressed.")
            sink.write(chunk)
    return remaining
