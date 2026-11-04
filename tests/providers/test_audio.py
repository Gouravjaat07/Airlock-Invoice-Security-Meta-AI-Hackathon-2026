"""WAV format validation tests (strict header matrix)."""

from __future__ import annotations

import struct

import pytest

from app.core.errors import AppError
from app.providers.audio import parse_wav


def _wav(*, channels=1, sample_rate=16000, bits=16, fmt_tag=1,
         data_seconds=1.0, extra_chunks=()) -> bytes:
    frames = int(sample_rate * data_seconds)
    data = b"\x00" * (frames * channels * (bits // 8))
    fmt = struct.pack("<HHIIHH", fmt_tag, channels, sample_rate,
                      sample_rate * channels * (bits // 8),
                      channels * (bits // 8), bits)
    chunks = struct.pack("<4sI", b"fmt ", 16) + fmt
    for chunk_id, body in extra_chunks:
        chunks += struct.pack("<4sI", chunk_id, len(body)) + body
        if len(body) % 2:
            chunks += b"\x00"
    chunks += struct.pack("<4sI", b"data", len(data)) + data
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def test_valid_wav_rates():
    # Documented file-transcription rates: 16/24 kHz only.
    for rate in (16000, 24000):
        fmt = parse_wav(_wav(sample_rate=rate))
        assert fmt.channels == 1
        assert fmt.sample_rate == rate
        assert fmt.bits_per_sample == 16
        assert abs(fmt.duration_s - 1.0) < 0.01


def test_extra_chunks_skipped():
    data = _wav(extra_chunks=[(b"LIST", b"INFO...."), (b"cue ", b"ab")])
    assert parse_wav(data).channels == 1


@pytest.mark.parametrize("kwargs", [
    {"channels": 2},
    {"bits": 8},
    {"bits": 24},
    {"fmt_tag": 3},
    {"sample_rate": 0},
    {"sample_rate": 500000},
    {"sample_rate": 8000},
    {"sample_rate": 44100},
    {"sample_rate": 48000},
])
def test_invalid_formats_rejected(kwargs):
    with pytest.raises(AppError):
        parse_wav(_wav(**kwargs))


@pytest.mark.parametrize("data", [
    b"",
    b"RIFF" + b"\x00" * 40,
    b"RIFX" + struct.pack("<I", 40) + b"WAVE" + b"\x00" * 40,
    b"RIFF" + struct.pack("<I", 40) + b"MP3 " + b"\x00" * 40,
    b"RIFF" + struct.pack("<I", 4) + b"WAVE",
    b"RIFF" + struct.pack("<I", 12) + b"WAVE" + b"data" + struct.pack("<I", 99999),
])
def test_corrupt_headers_rejected(data):
    with pytest.raises(AppError):
        parse_wav(data)
