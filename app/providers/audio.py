"""Strict WAV format validation for voice transcription.

The file-transcription contract requires RIFF/WAVE mono 16-bit integer
PCM at 16 kHz or 24 kHz (dev.meta.ai/docs/speech-to-text), within the
app's duration/size caps. Validation is header-level (chunk walk,
bounded); decode/conversion is out of scope — non-conforming audio is
rejected with a safe reason, never auto-converted.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from app.core.errors import AppError, ErrorCode

_MAX_CHUNKS = 64
_PCM_FORMAT_TAG = 1
# Documented file-transcription sample rates (model native: 24 kHz).
_SUPPORTED_RATES = frozenset({16000, 24000})


@dataclass(frozen=True)
class WavFormat:
    channels: int
    sample_rate: int
    bits_per_sample: int
    data_bytes: int
    duration_s: float


def parse_wav(data: bytes) -> WavFormat:
    """Parse and validate WAV headers; AppError(E_UPLOAD) when invalid."""
    if len(data) < 44 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise AppError(ErrorCode.UPLOAD, "Invalid WAV header")
    pos = 12
    fmt: bytes | None = None
    data_size: int | None = None
    for _ in range(_MAX_CHUNKS):
        if pos + 8 > len(data):
            break
        chunk_id = data[pos:pos + 4]
        (chunk_size,) = struct.unpack("<I", data[pos + 4:pos + 8])
        body_start = pos + 8
        body_end = body_start + chunk_size
        if body_end > len(data):
            raise AppError(ErrorCode.UPLOAD, "Truncated WAV chunk")
        if chunk_id == b"fmt ":
            fmt = data[body_start:body_end]
        elif chunk_id == b"data":
            data_size = chunk_size
        pos = body_end + (chunk_size % 2)  # word-aligned
        if fmt is not None and data_size is not None:
            break
    if fmt is None or len(fmt) < 16 or data_size is None:
        raise AppError(ErrorCode.UPLOAD, "WAV missing fmt or data chunk")
    (audio_format, channels, sample_rate, _byte_rate, _block_align,
     bits) = struct.unpack("<HHIIHH", fmt[:16])
    if audio_format != _PCM_FORMAT_TAG:
        raise AppError(ErrorCode.UPLOAD, "WAV must be integer PCM")
    if channels != 1:
        raise AppError(ErrorCode.UPLOAD, "WAV must be mono")
    if bits != 16:
        raise AppError(ErrorCode.UPLOAD, "WAV must be 16-bit")
    if sample_rate not in _SUPPORTED_RATES:
        raise AppError(ErrorCode.UPLOAD,
                       "WAV sample rate must be 16 kHz or 24 kHz")
    if data_size % 2 != 0:
        raise AppError(ErrorCode.UPLOAD, "WAV data chunk is truncated")
    bytes_per_second = sample_rate * channels * (bits // 8)
    duration = data_size / bytes_per_second if bytes_per_second else 0.0
    return WavFormat(channels=channels, sample_rate=sample_rate,
                     bits_per_sample=bits, data_bytes=data_size,
                     duration_s=duration)
