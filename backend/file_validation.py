import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from backend.config import cfg

_PDF_SIGNATURE = b"%PDF-"
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_DOCX_REQUIRED_FILES = frozenset(("[Content_Types].xml", "word/document.xml"))
_DOCX_FORBIDDEN_FILES = frozenset(("word/vbaProject.bin",))
_EXTENSION_TO_KIND = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "doc",
    ".txt": "txt",
}


@dataclass(frozen=True)
class ValidatedResumeFile:
    extension: str
    content_type: str


def _file_size(file_object: BinaryIO) -> int:
    position = file_object.tell()
    file_object.seek(0, io.SEEK_END)
    size = file_object.tell()
    file_object.seek(position)
    return size


def _is_docx(file_object: BinaryIO) -> bool:
    try:
        file_object.seek(0)
        with zipfile.ZipFile(file_object) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if (
                not _DOCX_REQUIRED_FILES.issubset(names)
                or _DOCX_FORBIDDEN_FILES.intersection(names)
                or len(entries) > cfg.resume_docx_max_entries
            ):
                return False

            total_uncompressed = sum(entry.file_size for entry in entries)
            if total_uncompressed > cfg.resume_docx_max_uncompressed_bytes:
                return False
            for entry in entries:
                path_parts = entry.filename.replace("\\", "/").split("/")
                if (
                    entry.flag_bits & 0x1
                    or entry.filename.startswith(("/", "\\"))
                    or ".." in path_parts
                    or (entry.file_size > 0 and entry.compress_size == 0)
                ):
                    return False
                if (
                    entry.file_size > 0
                    and entry.file_size / entry.compress_size
                    > cfg.resume_docx_max_compression_ratio
                ):
                    return False
            return True
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return False
    finally:
        file_object.seek(0)


def _is_plain_text(file_object: BinaryIO) -> bool:
    file_object.seek(0)
    data = file_object.read(cfg.resume_upload_max_bytes + 1)
    file_object.seek(0)
    if not data or len(data) > cfg.resume_upload_max_bytes or b"\x00" in data:
        return False
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    disallowed_controls = sum(
        character < " " and character not in "\n\r\t\f" for character in text
    )
    return disallowed_controls <= max(1, len(text) // 100)


def validate_resume_file(
    file_object: BinaryIO, original_filename: str | None
) -> ValidatedResumeFile:
    """Detect a resume type from its bytes and verify the filename extension."""
    size = _file_size(file_object)
    if size <= 0:
        raise ValueError("Файл пуст")
    if size > cfg.resume_upload_max_bytes:
        raise ValueError(
            f"Файл превышает допустимый размер {cfg.resume_upload_max_bytes} байт"
        )

    file_object.seek(0)
    header = file_object.read(8)
    file_object.seek(0)

    if header.startswith(_PDF_SIGNATURE):
        detected = ValidatedResumeFile(".pdf", "application/pdf")
    elif header.startswith(_ZIP_SIGNATURES) and _is_docx(file_object):
        detected = ValidatedResumeFile(
            ".docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    elif header.startswith(_OLE_SIGNATURE):
        detected = ValidatedResumeFile(".doc", "application/msword")
    elif _is_plain_text(file_object):
        detected = ValidatedResumeFile(".txt", "text/plain")
    else:
        raise ValueError("Содержимое файла не соответствует PDF, DOCX, DOC или TXT")

    supplied_extension = Path(original_filename or "").suffix.lower()
    expected_kind = _EXTENSION_TO_KIND.get(supplied_extension)
    detected_kind = _EXTENSION_TO_KIND[detected.extension]
    if expected_kind != detected_kind:
        raise ValueError(
            "Расширение имени файла не соответствует его фактическому содержимому"
        )

    file_object.seek(0)
    return detected
