"""Artifact storage: validated intake + content-addressed local store.

Security: server-generated storage keys only; client filenames never touch
the filesystem. Content signatures (magic bytes) decide the type, not MIME
headers. Temp file + atomic rename; SHA-256 streamed during write.
"""

from __future__ import annotations

import hashlib
import os
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_id
from app.core.logging import get_logger

logger = get_logger("airlock.storage")

_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_RIFF_MAGIC = b"RIFF"
_FTYP_MAGIC = b"ftyp"


@dataclass(frozen=True)
class StoredArtifact:
    artifact_id: str
    storage_key: str
    path: Path
    sha256: str
    size_bytes: int
    media_type: str
    extension: str


class LocalBlobStore:
    """Filesystem blob store. Keys are `<sha-prefix>/<artifact-id><ext>`."""

    def __init__(self, settings: Settings):
        self.root = Path(settings.blob_dir)
        self.settings = settings

    def ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, storage_key: str) -> Path:
        # Keys are server-generated, but resolve defensively anyway.
        candidate = (self.root / storage_key).resolve()
        root = self.root.resolve()
        if candidate != root and root not in candidate.parents:
            raise AppError(ErrorCode.STORAGE, "Artifact key escapes storage root")
        return candidate

    def store_bytes(self, data: bytes, *, artifact_id: str, extension: str,
                    sha256: str) -> tuple[str, Path]:
        self.ensure_root()
        storage_key = f"{sha256[:2]}/{artifact_id}{extension}"
        target = self._resolve(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f".{artifact_id}.tmp"
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            # Detail stays server-side: OSError text carries filesystem paths.
            logger.error("artifact store failed: %r", exc)
            raise AppError(ErrorCode.STORAGE, "Cannot store artifact") from exc
        return storage_key, target

    def read_bytes(self, storage_key: str) -> bytes:
        path = self._resolve(storage_key)
        try:
            return path.read_bytes()
        except OSError as exc:
            logger.error("artifact read failed: %r", exc)
            raise AppError(ErrorCode.STORAGE, "Cannot read artifact") from exc

    def delete(self, storage_key: str) -> None:
        path = self._resolve(storage_key)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.error("artifact delete failed: %r", exc)
            raise AppError(ErrorCode.STORAGE, "Cannot delete artifact") from exc

    def sweep_tmp(self) -> int:
        """Remove orphaned `.tmp` intake files. Returns count removed."""
        removed = 0
        if not self.root.exists():
            return 0
        for tmp in self.root.rglob(".*.tmp"):
            try:
                if tmp.is_file() and not tmp.is_symlink():
                    tmp.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    def sweep_orphans(self, conn) -> int:
        """Delete blob files with no artifact row (crash recovery).

        Returns count removed. Never deletes temp files (see sweep_tmp)
        and never touches rows -- files only.
        """
        removed = self.sweep_tmp()
        if not self.root.exists():
            return removed
        known = {str(row[0]) for row in
                 conn.execute("SELECT DISTINCT storage_key FROM artifacts")}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            if path.name.startswith(".") and path.suffix == ".tmp":
                continue
            try:
                key = path.relative_to(self.root).as_posix()
            except ValueError:
                continue
            if key not in known:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    continue
        return removed


def sniff_media(data: bytes, filename: str) -> tuple[str, str]:
    """Return (media_type, extension) from content signatures.

    Raises AppError(E_UPLOAD) for unknown/truncated content. The filename
    extension is cross-checked but never trusted on its own.
    """
    if len(data) == 0:
        raise AppError(ErrorCode.UPLOAD, "Empty upload is not accepted")
    ext = Path(filename).suffix.lower()
    if data.startswith(_PDF_MAGIC):
        _check_pdf_bounds(data)
        return "application/pdf", ".pdf"
    if data.startswith(_PNG_MAGIC):
        _check_png_bounds(data)
        return "image/png", ".png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg", ".jpg" if ext != ".jpeg" else ".jpeg"
    if data.startswith(_RIFF_MAGIC) and len(data) >= 12 and data[8:12] == b"WAVE":
        return "audio/wav", ".wav"
    if len(data) >= 12 and data[4:8] == _FTYP_MAGIC:
        return "video/mp4", ".mp4"
    raise AppError(ErrorCode.UPLOAD,
                   "Unsupported file content: unrecognized file signature")


_ENCRYPTED_PDF_RE = re.compile(rb"/Encrypt\b")


def _check_pdf_bounds(data: bytes) -> None:
    if b"%%EOF" not in data[-2056:] and b"%%EOF" not in data:
        raise AppError(ErrorCode.UPLOAD, "Truncated or corrupt PDF (missing EOF marker)")
    if _ENCRYPTED_PDF_RE.search(data):
        raise AppError(ErrorCode.UPLOAD,
                       "Encrypted PDFs are not accepted")


def count_pdf_pages(data: bytes) -> int:
    # Bounded heuristic: count `/Type /Page` (not `/Pages`) occurrences.
    count = 0
    needle = b"/Type"
    idx = 0
    while True:
        idx = data.find(needle, idx)
        if idx == -1:
            break
        window = data[idx:idx + 24]
        if window.startswith(b"/Type/Page") and not window.startswith(b"/Type/Pages"):
            count += 1
            if count > 1000:  # hard parser bound; config limit applies below this
                break
        idx += 5
    return count


def _check_png_bounds(data: bytes) -> None:
    if len(data) < 33:
        raise AppError(ErrorCode.UPLOAD, "Truncated PNG")
    try:
        width, height = struct.unpack(">II", data[16:24])
    except struct.error as exc:
        raise AppError(ErrorCode.UPLOAD, "Corrupt PNG header") from exc
    if width == 0 or height == 0 or width > 100000 or height > 100000:
        raise AppError(ErrorCode.UPLOAD, "Corrupt PNG dimensions")


def png_dimensions(data: bytes) -> tuple[int, int]:
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


# SOF markers carrying frame dimensions (SOF0-SOF15 minus DHT/DAC/JPG).
_JPEG_SOF = frozenset({
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
})
# Standalone markers without a length field.
_JPEG_STANDALONE = frozenset({0x01, 0xD0, 0xD1, 0xD2, 0xD3,
                              0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9})
_MAX_JPEG_MARKERS = 64
_MAX_MP4_BOXES = 128


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Parse JPEG frame dimensions from SOF; None when unparseable.

    Fail-open by design (mirrors `wav_duration_seconds`): an unparseable
    header is accepted and the size cap still bounds the upload. Nothing
    in Phase 2 decodes pixel data.
    """
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        return None
    pos = 2
    for _ in range(_MAX_JPEG_MARKERS):
        if pos + 2 > len(data) or data[pos] != 0xFF:
            return None
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            return None
        marker = data[pos]
        pos += 1
        if marker in _JPEG_STANDALONE:
            continue
        if marker == 0xDA:  # SOS: scan data follows; no SOF will appear
            return None
        if pos + 2 > len(data):
            return None
        (length,) = struct.unpack(">H", data[pos:pos + 2])
        if length < 2 or pos + length > len(data):
            return None
        if marker in _JPEG_SOF:
            if length < 8:
                return None
            height = struct.unpack(">H", data[pos + 3:pos + 5])[0]
            width = struct.unpack(">H", data[pos + 5:pos + 7])[0]
            if width == 0 or height == 0:
                return None
            return int(width), int(height)
        pos += length
    return None


def _mp4_boxes(data: bytes, start: int, end: int) -> list[tuple[bytes, int, int]]:
    """List (type, payload_start, payload_end) for boxes in [start, end)."""
    boxes: list[tuple[bytes, int, int]] = []
    pos = start
    for _ in range(_MAX_MP4_BOXES):
        if pos + 8 > end:
            break
        (size,) = struct.unpack(">I", data[pos:pos + 4])
        box_type = data[pos + 4:pos + 8]
        header = 8
        if size == 1:  # large size
            if pos + 16 > end:
                break
            (size,) = struct.unpack(">Q", data[pos + 8:pos + 16])
            header = 16
        elif size == 0:  # extends to end of container
            size = end - pos
        if size < header or pos + size > end:
            break
        boxes.append((box_type, pos + header, pos + size))
        pos += size
    return boxes


def mp4_duration_seconds(data: bytes) -> float | None:
    """Parse MP4 track duration from moov/mvhd; None when unparseable.

    Fail-open like `jpeg_dimensions`: absence of a readable mvhd does not
    reject the upload; the size cap still bounds it.
    """
    for box_type, payload, box_end in _mp4_boxes(data, 0, len(data)):
        if box_type != b"moov":
            continue
        for inner_type, inner_start, inner_end in _mp4_boxes(data, payload, box_end):
            if inner_type != b"mvhd":
                continue
            header = data[inner_start:inner_end]
            if len(header) < 4:
                return None
            version = header[0]
            try:
                if version == 1:
                    if len(header) < 32:
                        return None
                    timescale = struct.unpack(">I", header[20:24])[0]
                    duration = struct.unpack(">Q", header[24:32])[0]
                else:
                    if len(header) < 20:
                        return None
                    timescale = struct.unpack(">I", header[12:16])[0]
                    duration = struct.unpack(">I", header[16:20])[0]
            except struct.error:
                return None
            if timescale == 0:
                return None
            return duration / timescale
    return None


def wav_duration_seconds(data: bytes) -> float | None:
    """Parse WAV header duration; None when the header is incomplete."""
    if len(data) < 44:
        return None
    if not data.startswith(_RIFF_MAGIC) or data[8:12] != b"WAVE":
        return None
    try:
        byte_rate = struct.unpack("<I", data[28:32])[0]
        data_size = struct.unpack("<I", data[40:44])[0]
    except struct.error:
        return None
    if byte_rate == 0:
        return None
    return data_size / byte_rate


def validate_resource_bounds(data: bytes, media_type: str, settings: Settings) -> None:
    if media_type == "application/pdf":
        pages = count_pdf_pages(data)
        if pages > settings.max_pdf_pages:
            raise AppError(ErrorCode.UPLOAD,
                           f"PDF has {pages} pages; limit is {settings.max_pdf_pages}")
    elif media_type == "image/png":
        width, height = png_dimensions(data)
        if width * height > settings.max_image_pixels:
            raise AppError(ErrorCode.UPLOAD, "Image exceeds pixel limit")
    elif media_type == "image/jpeg":
        dimensions = jpeg_dimensions(data)
        if dimensions is not None:
            width, height = dimensions
            if width * height > settings.max_image_pixels:
                raise AppError(ErrorCode.UPLOAD, "Image exceeds pixel limit")
    elif media_type == "audio/wav":
        duration = wav_duration_seconds(data)
        if duration is not None and duration > settings.max_audio_seconds:
            raise AppError(ErrorCode.UPLOAD, "Audio exceeds duration limit")
    elif media_type == "video/mp4":
        duration = mp4_duration_seconds(data)
        if duration is not None and duration > settings.max_video_seconds:
            raise AppError(ErrorCode.UPLOAD, "Video exceeds duration limit")


def sanitize_filename(filename: str) -> str:
    """Best-effort display name; never used for storage paths."""
    name = filename.replace("\x00", "").strip().split("/")[-1].split("\\")[-1]
    if len(name) > 128:
        name = name[-128:]
    return name or "upload"


def intake_bytes(data: bytes, *, filename: str, settings: Settings,
                 store: LocalBlobStore) -> StoredArtifact:
    """Validate + persist one upload. Returns stored-artifact metadata."""
    if len(data) > settings.max_upload_bytes:
        raise AppError(ErrorCode.UPLOAD,
                       f"Upload is {len(data)} bytes; limit is {settings.max_upload_bytes}")
    media_type, extension = sniff_media(data, filename)
    validate_resource_bounds(data, media_type, settings)
    sha256 = hashlib.sha256(data).hexdigest()
    artifact_id = new_id("art")
    storage_key, path = store.store_bytes(data, artifact_id=artifact_id,
                                          extension=extension, sha256=sha256)
    return StoredArtifact(artifact_id=artifact_id, storage_key=storage_key,
                          path=path, sha256=sha256, size_bytes=len(data),
                          media_type=media_type, extension=extension)
