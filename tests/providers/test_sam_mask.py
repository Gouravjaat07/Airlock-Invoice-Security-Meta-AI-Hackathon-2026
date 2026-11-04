"""SAM mask raster decoder tests (pure, offline).

Conformance for the official codec port (`app.providers.sam_mask`):
hand-computed one_bit vectors (range coder traced by hand), the
verbatim documented lossless payloads (structural assertions), a
round-trip property, and a malformed/over-budget error matrix.
"""

from __future__ import annotations

import pytest

from app.providers.sam_mask import (
    MAX_MASK_PIXELS,
    MaskDecodeError,
    decode_mask_to_raster,
    encode_mask_one_bit,
    is_payload_char,
)

# Hand-verified one_bit vectors (1x1): packed bytes [0,0,0,0] decodes
# to bit 0; packed bytes [0x7F,0xFF,0xFF,0xFF] (base85 "O.lVP")
# decodes to bit 1. See the port notes in `sam_mask.py`.
ZERO_1X1 = "!!!!!&!!!!!"
ONE_1X1 = "!!!!!&O.lVP"

# Verbatim documented lossless payloads (reading-segmentation).
DOC_LOSSLESS_A = ("~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/"
                  "#Xd8%dX9x(")
DOC_LOSSLESS_B = ("~!!!!J!0c[q=Pj_zs=*4C4(/./x#:/`S_GnD`=o3?X{emCgO$y@")


def _decode(payload, width, height, encoding="one_bit"):
    return decode_mask_to_raster(encoding=encoding, width=width,
                                 height=height, payload=payload)


def test_one_bit_zero_vector():
    assert _decode(ZERO_1X1, 1, 1) == bytes([0])


def test_one_bit_one_vector():
    assert _decode(ONE_1X1, 1, 1) == bytes([1])


def test_documented_lossless_vectors_decode():
    for payload, dims in ((DOC_LOSSLESS_A, (60, 27)),
                          (DOC_LOSSLESS_B, (48, 27))):
        raster = _decode(payload, dims[0], dims[1], encoding="lossless")
        assert len(raster) == dims[0] * dims[1]
        assert set(raster) <= {0, 1}


def test_one_bit_round_trip_checkerboard():
    width, height = 4, 4
    raster = bytes((x + y) % 2 for y in range(height) for x in range(width))
    payload = encode_mask_one_bit(raster, width, height)
    assert payload.startswith("!")
    assert _decode(payload, width, height) == raster


def test_one_bit_round_trip_solid():
    raster = bytes([1] * 9)
    payload = encode_mask_one_bit(raster, 3, 3)
    assert _decode(payload, 3, 3) == raster


def test_encode_rejects_bad_dims():
    with pytest.raises(MaskDecodeError):
        encode_mask_one_bit(bytes([0, 1]), 2, 2)
    with pytest.raises(MaskDecodeError):
        encode_mask_one_bit(bytes([0, 2, 0, 0]), 2, 2)


@pytest.mark.parametrize("payload,width,height,encoding", [
    ("", 1, 1, "one_bit"),  # empty
    ("!!!!", 1, 1, "one_bit"),  # missing length prefix
    ("~~~~~", 1, 1, "one_bit"),  # wrong marker
    ("!!!!!", 1, 1, "lossless"),  # wrong marker
    (ZERO_1X1, 0, 1, "one_bit"),  # zero dim
    (ZERO_1X1, 1, -1, "one_bit"),  # negative dim
    (ZERO_1X1, 1, 1, "rle"),  # unknown encoding
    ("!!!#&!!!!!", 1, 1, "one_bit"),  # length prefix mismatch
    ("!!!!!&{{{{{", 1, 1, "one_bit"),  # out-of-range group
    ("!!!!!&!!!}!", 1, 1, "one_bit"),  # invalid char in group
    ("!!!!!&!!!~!", 1, 1, "one_bit"),  # marker char inside payload
    ("!!!!!&!! !!", 1, 1, "one_bit"),  # whitespace in payload
])
def test_decode_error_matrix(payload, width, height, encoding):
    with pytest.raises(MaskDecodeError):
        _decode(payload, width, height, encoding=encoding)


def test_decode_over_budget_dims():
    with pytest.raises(MaskDecodeError):
        _decode(ZERO_1X1, MAX_MASK_PIXELS, 2)


def test_decode_non_string_payload():
    with pytest.raises(MaskDecodeError):
        decode_mask_to_raster(encoding="one_bit", width=1, height=1,
                              payload=None)


def test_payload_charset_matches_official_alphabet():
    assert is_payload_char("A")
    assert is_payload_char("!")
    assert is_payload_char("{")
    assert not is_payload_char("}")
    assert not is_payload_char("~")
    assert not is_payload_char("|")
    assert not is_payload_char(";")
    assert not is_payload_char(",")
    assert not is_payload_char(" ")
    assert not is_payload_char("<")
    assert not is_payload_char('"')
