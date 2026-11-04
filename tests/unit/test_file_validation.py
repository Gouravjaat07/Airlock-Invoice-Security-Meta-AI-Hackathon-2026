"""Unit tests: upload validation, content sniffing, storage safety."""

from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.storage.artifacts import (
    count_pdf_pages,
    intake_bytes,
    jpeg_dimensions,
    mp4_duration_seconds,
    sanitize_filename,
    sniff_media,
    validate_resource_bounds,
    wav_duration_seconds,
)


def _pdf(pages: int = 1) -> bytes:
    kids = "".join(f"{3 + i} 0 R" for i in range(pages))
    objs = "".join(
        f"{3 + i} 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 10 10]>>endobj\n"
        for i in range(pages))
    return (f"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            f"2 0 obj<</Type/Pages/Kids[{kids}]/Count {pages}>>endobj\n"
            f"{objs}trailer<</Root 1 0 R>>\n%%EOF\n").encode()


def test_sniff_pdf_png_jpeg_wav_mp4():
    assert sniff_media(_pdf(), "x.pdf")[0] == "application/pdf"
    import struct
    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + \
        struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0) + b"\x00" * 4
    assert sniff_media(png, "x.bin")[0] == "image/png"
    assert sniff_media(b"\xff\xd8\xff\xe0" + b"\x00" * 20, "x.pdf")[0] == \
        "image/jpeg"  # content wins over the lying extension
    wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 40
    assert sniff_media(wav, "x.mp3")[0] == "audio/wav"
    mp4 = b"\x00\x00\x00\x1cftypisom" + b"\x00" * 20
    assert sniff_media(mp4, "x.avi")[0] == "video/mp4"


def test_sniff_rejects_unknown_and_empty():
    with pytest.raises(AppError):
        sniff_media(b"", "x.pdf")
    with pytest.raises(AppError):
        sniff_media(b"MZ" + b"\x00" * 100, "evil.pdf")
    with pytest.raises(AppError):
        sniff_media(b"%PDF-1.4 truncated", "x.pdf")


def test_pdf_page_count_and_limit(settings):
    assert count_pdf_pages(_pdf(3)) == 3
    settings.max_pdf_pages = 2
    with pytest.raises(AppError):
        validate_resource_bounds(_pdf(3), "application/pdf", settings)


def test_wav_duration(settings):
    import struct
    header = (b"RIFF" + struct.pack("<I", 36 + 16000) + b"WAVE" + b"fmt " +
              struct.pack("<I", 16) +
              struct.pack("<HHIIHH", 1, 1, 8000, 8000, 1, 8) + b"data" +
              struct.pack("<I", 16000))
    assert wav_duration_seconds(header) == pytest.approx(2.0)
    settings.max_audio_seconds = 1
    with pytest.raises(AppError):
        validate_resource_bounds(header, "audio/wav", settings)


def test_oversize_rejected(settings, store):
    settings.max_upload_bytes = 10
    with pytest.raises(AppError):
        intake_bytes(_pdf(), filename="x.pdf", settings=settings,
                     store=store)


def test_storage_key_never_uses_filename(settings, store):
    stored = intake_bytes(_pdf(), filename="../../../etc/passwd\x00.pdf",
                          settings=settings, store=store)
    assert ".." not in stored.storage_key and "passwd" not in stored.storage_key
    assert stored.path.read_bytes() == _pdf()


def test_sanitize_filename():
    assert sanitize_filename("..\\..\\x.pdf") == "x.pdf"
    assert sanitize_filename("a\x00b") == "ab"


def test_path_escape_blocked(settings, store):
    store.ensure_root()
    with pytest.raises(AppError):
        store.read_bytes("../../pyproject.toml")


def _png(width, height):
    import struct
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" +
            struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0) +
            b"\x00" * 4)


def _jpeg(width, height):
    import struct
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof = (b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" +
           struct.pack(">HH", height, width) + b"\x01\x01\x11\x00")
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def _mp4(timescale, duration):
    import struct
    payload = (b"\x00\x00\x00\x00" +
               struct.pack(">IIII", 0, 0, timescale, duration) +
               b"\x00" * 80)
    mvhd = struct.pack(">I", 8 + len(payload)) + b"mvhd" + payload
    moov = struct.pack(">I", 8 + len(mvhd)) + b"moov" + mvhd
    ftyp = struct.pack(">I", 24) + b"ftyp" + b"isom" + b"\x00" * 12
    return ftyp + moov


def test_png_width_validated():
    """Regression (F8): zero/huge width is corrupt, like height."""
    with pytest.raises(AppError):
        sniff_media(_png(0, 8), "x.png")
    with pytest.raises(AppError):
        sniff_media(_png(200000, 8), "x.png")
    assert sniff_media(_png(8, 8), "x.png")[0] == "image/png"


def test_jpeg_dimensions_and_limit(settings):
    """Regression (F9): JPEG honors the shared pixel cap."""
    assert jpeg_dimensions(_jpeg(16, 32)) == (16, 32)
    assert jpeg_dimensions(b"\xff\xd8\xff") is None  # fail-open
    settings.max_image_pixels = 100
    with pytest.raises(AppError):
        validate_resource_bounds(_jpeg(16, 32), "image/jpeg", settings)
    validate_resource_bounds(_jpeg(4, 4), "image/jpeg", settings)
    validate_resource_bounds(b"\xff\xd8\xff\xe0" + b"\x00" * 20,
                             "image/jpeg", settings)  # unparseable: allowed


def test_mp4_duration_and_limit(settings):
    """Regression (F9): MP4 honors the configured duration cap."""
    assert mp4_duration_seconds(_mp4(1000, 5000)) == pytest.approx(5.0)
    assert mp4_duration_seconds(b"\x00\x00\x00\x1cftypisom" + b"\x00" * 20) is None
    settings.max_video_seconds = 2
    with pytest.raises(AppError):
        validate_resource_bounds(_mp4(1000, 5000), "video/mp4", settings)
    validate_resource_bounds(_mp4(1000, 1000), "video/mp4", settings)


def test_encrypted_pdf_rejected():
    """Regression (F10): password-protected PDFs fail fast at intake."""
    encrypted = _pdf().replace(b"%%EOF", b"<< /Encrypt 5 0 R >>\n%%EOF")
    with pytest.raises(AppError) as exc_info:
        sniff_media(encrypted, "x.pdf")
    assert "Encrypted" in exc_info.value.message


def test_fixture_media_pass_bounds(settings):
    from tests.conftest import fixture_bytes
    validate_resource_bounds(fixture_bytes("delivery/sam-ok.png"),
                             "image/png", settings)
    validate_resource_bounds(fixture_bytes("delivery/clip.mp4"),
                             "video/mp4", settings)


def test_sweep_tmp(settings, store):
    store.ensure_root()
    stray = store.root / ".orphan.tmp"
    stray.write_bytes(b"junk")
    assert store.sweep_tmp() == 1
    assert not stray.exists()
