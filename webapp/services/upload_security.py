"""Strict upload type validation and server-selected file extensions."""

from __future__ import annotations

from io import BytesIO
from zipfile import BadZipFile, ZipFile


MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


def _matches_signature(content_type: str, contents: bytes) -> bool:
    if content_type == "image/jpeg":
        return contents.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return contents.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/gif":
        return contents.startswith((b"GIF87a", b"GIF89a"))
    if content_type == "image/webp":
        return len(contents) >= 12 and contents[:4] == b"RIFF" and contents[8:12] == b"WEBP"
    if content_type == "application/pdf":
        return contents.lstrip().startswith(b"%PDF-")
    if content_type == "application/msword":
        return contents.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if content_type.endswith("wordprocessingml.document"):
        try:
            with ZipFile(BytesIO(contents)) as archive:
                names = set(archive.namelist())
                return "[Content_Types].xml" in names and any(name.startswith("word/") for name in names)
        except (BadZipFile, OSError):
            return False
    return False


def safe_upload_extension(
    content_type: str | None,
    contents: bytes,
    allowed_types: set[str] | list[str] | tuple[str, ...],
) -> str:
    """Validate declared type plus magic bytes and return a trusted extension."""
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized not in allowed_types or normalized not in MIME_EXTENSIONS:
        raise ValueError("Unsupported upload type")
    if not _matches_signature(normalized, contents):
        raise ValueError("Upload contents do not match the declared type")
    return MIME_EXTENSIONS[normalized]
