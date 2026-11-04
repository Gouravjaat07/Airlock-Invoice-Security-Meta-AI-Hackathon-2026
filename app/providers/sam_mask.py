"""SAM 3.1 mask raster decoder (port of the official codec).

Ported from `@meta-sam/parser` 0.1.0 `dist/mask-codec.js` (Meta
Platforms, Inc.; see dev.meta.ai/docs/sam/client-libraries): the
base85 layer, the range coder, and the one_bit/lossless raster
decoders, transcribed operation-by-operation (Python integers are
masked to the reference's 32-bit arithmetic explicitly).

Two deliberate differences from the reference: resource caps are
applied BEFORE any allocation (the reference trusts its input; a
specification deviation must fail closed here), and unexpected
internal failures surface as `MaskDecodeError` (undecodable
evidence), never as partial rasters.

Wire form per record: `data=<H>,<W>,<enc><payload>` with `<enc>`
`~` (lossless) or `!` (one_bit). Decoded rasters are row-major bytes
of 0/1 with exactly H*W entries (H rows, W columns).
"""

from __future__ import annotations

# --- base85 layer (official alphabet) -------------------------------------
# Printable ASCII 0x21..0x7E minus `" \\ , ; < > |`; values 0..84 are
# usable (digit() in the reference rejects indices >= 85, i.e. the
# trailing `}` and `~` never appear inside a payload).
_EXCLUDED = frozenset({'"', "\\", ",", ";", "<", ">", "|"})
_ALPHABET = "".join(chr(code) for code in range(0x21, 0x7F)
                    if chr(code) not in _EXCLUDED)
_VALUE = {char: index for index, char in enumerate(_ALPHABET)}
_RADIX = 85
_PREFIX_LEN = 5

# --- range coder constants (reference values, verbatim) --------------------
_TOP = 1 << 24
_BOTTOM = 1 << 16
_MASK32 = 0xFFFFFFFF
_INCREMENT = 14
_COUNT_LIMIT = 4096
_CONTEXT_COUNT = 1 << 12
_PADDING = 2
_SYMBOLS = 256
_TOTAL_INDEX = 256
_SPATIAL_MODES = 5
_ZERO_INCREMENT = 32
_ZERO_LIMIT = 16384
_ORDER_ONE_INCREMENT = 56
_ORDER_ONE_LIMIT = 8192
_ORDER_TWO_STEP = 14 * 44
_ORDER_TWO_LIMIT = 14 * 3584
_ORDER_ZERO_STEP = 2 * 16
_ORDER_ZERO_LIMIT = 2 * 2048
_ORDER_ZERO_INITIAL = 2
_ORDER_ONE_INITIAL = 1

# --- Airlock resource caps (fail closed past them) --------------------------
# Rasters are downsampled thumbnails of the delivery media (the
# documented examples use ~27x60 rasters for 320x334 frames); 4M
# pixels covers full-resolution 4MP evidence with headroom while
# bounding transient memory (~4MB raster) and pure-Python decode time.
MAX_MASK_PIXELS = 4_194_304
# Total decoded pixels across one lane (all masks, all frames).
MAX_LANE_PIXELS = 16_777_216


class MaskDecodeError(ValueError):
    """A mask payload is malformed, non-canonical, or over budget."""


def is_payload_char(char: str) -> bool:
    """True when `char` is usable inside a mask payload."""
    return _VALUE.get(char, _RADIX) < _RADIX


def _digit(char: str) -> int:
    value = _VALUE.get(char)
    if value is None or value >= _RADIX:
        raise MaskDecodeError("Mask payload contains an invalid character.")
    return value


def _b85_pack(data: bytes) -> str:
    length = len(data)
    prefix = [""] * _PREFIX_LEN
    rest = length
    for index in range(_PREFIX_LEN - 1, -1, -1):
        prefix[index] = _ALPHABET[rest % _RADIX]
        rest //= _RADIX
    if rest != 0:
        raise MaskDecodeError("Mask payload is too large.")
    out = list(prefix)
    full = length - (length % 4)
    for offset in range(0, full, 4):
        value = ((data[offset] << 24) | (data[offset + 1] << 16)
                 | (data[offset + 2] << 8) | data[offset + 3])
        digits = [0] * 5
        for index in range(4, -1, -1):
            digits[index] = value % _RADIX
            value //= _RADIX
        out.extend(_ALPHABET[d] for d in digits)
    remainder = length - full
    if remainder:
        value = 0
        for index in range(4):
            value = ((value << 8)
                     | (data[full + index] if index < remainder else 0)
                     ) & _MASK32
        digits = [0] * 5
        for index in range(4, -1, -1):
            digits[index] = value % _RADIX
            value //= _RADIX
        out.extend(_ALPHABET[digits[index]] for index in range(remainder + 1))
    return "".join(out)


def _b85_unpack(payload: str, *, max_bytes: int) -> bytes:
    if len(payload) < _PREFIX_LEN:
        raise MaskDecodeError("Mask payload is missing its length prefix.")
    length = 0
    for char in payload[:_PREFIX_LEN]:
        length = length * _RADIX + _digit(char)
    if length > max_bytes:
        raise MaskDecodeError("Mask packed length exceeds its raster bound.")
    remainder = length % 4
    expected = (_PREFIX_LEN + (length // 4) * 5
                + (0 if remainder == 0 else remainder + 1))
    if len(payload) != expected:
        raise MaskDecodeError("Mask payload length does not match its prefix.")
    out = bytearray(length)
    source = _PREFIX_LEN
    dest = 0
    full = length - remainder
    while dest < full:
        value = 0
        for index in range(5):
            value = value * _RADIX + _digit(payload[source + index])
        if value > _MASK32:
            raise MaskDecodeError(
                "Mask payload contains an out-of-range group.")
        source += 5
        out[dest] = (value >> 24) & 0xFF
        out[dest + 1] = (value >> 16) & 0xFF
        out[dest + 2] = (value >> 8) & 0xFF
        out[dest + 3] = value & 0xFF
        dest += 4
    if remainder:
        value = 0
        for index in range(5):
            value = value * _RADIX + (
                _digit(payload[source + index])
                if index < remainder + 1 else _RADIX - 1)
        if value > _MASK32:
            raise MaskDecodeError("Mask payload contains an out-of-range tail.")
        for index in range(remainder):
            out[dest + index] = (value >> (24 - index * 8)) & 0xFF
    if _b85_pack(bytes(out)) != payload:
        raise MaskDecodeError("Mask payload is not in canonical form.")
    return bytes(out)


class _RangeEncoder:
    def __init__(self) -> None:
        self._low = 0
        self._range = _MASK32
        self._output: list[int] = []

    def encode(self, cumulative: int, frequency: int, total: int) -> None:
        scaled = self._range // total
        self._low = (self._low + scaled * cumulative) & _MASK32
        self._range = scaled * frequency
        self._renorm()

    def _renorm(self) -> None:
        while True:
            if (((self._low ^ (self._low + self._range)) & _MASK32)
                    < _TOP):
                pass
            elif self._range < _BOTTOM:
                self._range = ((-self._low) & _MASK32) & (_BOTTOM - 1)
            else:
                return
            self._output.append((self._low >> 24) & 0xFF)
            self._low = (self._low << 8) & _MASK32
            self._range = (self._range << 8) & _MASK32

    def finish(self) -> bytes:
        for _ in range(4):
            self._output.append((self._low >> 24) & 0xFF)
            self._low = (self._low << 8) & _MASK32
        return bytes(self._output)


class _RangeDecoder:
    def __init__(self, data: bytes) -> None:
        if len(data) < 4:
            raise MaskDecodeError("Mask payload is missing its finalization.")
        self._data = data
        self._pos = 0
        self._low = 0
        self._range = _MASK32
        self._code = 0
        self._scaled = 0
        for _ in range(4):
            self._code = ((self._code << 8) | self._read()) & _MASK32

    def _read(self) -> int:
        if self._pos >= len(self._data):
            raise MaskDecodeError(
                "Mask payload ended before decoding completed.")
        byte = self._data[self._pos]
        self._pos += 1
        return byte

    def frequency(self, total: int) -> int:
        self._scaled = self._range // total
        if self._scaled == 0:
            raise MaskDecodeError("Mask payload has invalid coding state.")
        value = ((self._code - self._low) & _MASK32) // self._scaled
        return value if value < total else total - 1

    def decode(self, cumulative: int, frequency: int) -> None:
        self._low = (self._low + self._scaled * cumulative) & _MASK32
        self._range = self._scaled * frequency
        while True:
            if (((self._low ^ (self._low + self._range)) & _MASK32)
                    < _TOP):
                pass
            elif self._range < _BOTTOM:
                self._range = ((-self._low) & _MASK32) & (_BOTTOM - 1)
            else:
                return
            self._code = ((self._code << 8) | self._read()) & _MASK32
            self._low = (self._low << 8) & _MASK32
            self._range = (self._range << 8) & _MASK32


def _order_two(table: dict[int, list[int]], key: int) -> list[int]:
    counts = table.get(key)
    if counts is None:
        counts = [0] * (_SYMBOLS + 1)
        table[key] = counts
    return counts


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_dist = abs(estimate - left)
    up_dist = abs(estimate - up)
    upper_left_dist = abs(estimate - upper_left)
    if left_dist <= up_dist and left_dist <= upper_left_dist:
        return left
    return up if up_dist <= upper_left_dist else upper_left


def _predict_byte(output: bytearray, offset: int, x: int, y: int,
                  mode: int, width: int) -> int:
    if mode < 0 or mode >= _SPATIAL_MODES:
        raise MaskDecodeError("Lossless mask payload uses an invalid predictor.")
    left = output[offset - 1] if x > 0 else 0
    up = output[offset - width] if y > 0 else 0
    if mode == 1:
        return up
    if mode == 2:
        return left
    if mode == 3:
        return (left + up) >> 1
    upper_left = output[offset - width - 1] if x > 0 and y > 0 else 0
    if mode == 0:
        return _paeth(left, up, upper_left)
    if upper_left >= max(left, up):
        return min(left, up)
    if upper_left <= min(left, up):
        return max(left, up)
    return left + up - upper_left


def _unzig(value: int, prediction: int) -> int:
    delta = -((value + 1) >> 1) if value & 1 else value >> 1
    return (prediction + delta) & 0xFF


def _zero_context(residuals: bytearray, offset: int, x: int, y: int,
                  width: int) -> int:
    left = 1 if x == 0 else (1 if residuals[offset - 1] == 0 else 0)
    up = 1 if y == 0 else (1 if residuals[offset - width] == 0 else 0)
    upper_left = 1 if (x == 0 or y == 0) else (
        1 if residuals[offset - width - 1] == 0 else 0)
    upper_right = 1 if (y == 0 or x >= width - 1) else (
        1 if residuals[offset - width + 1] == 0 else 0)
    return left | (up << 1) | (upper_left << 2) | (upper_right << 3)


def _decode_lossless(payload: str, width: int, height: int) -> bytes:
    packed = _b85_unpack(payload[1:], max_bytes=width * height * 2 + 1024)
    if len(packed) < 5:
        raise MaskDecodeError("Lossless mask payload is truncated.")
    selector = packed[0]
    decoder = _RangeDecoder(packed[1:])
    length = width * height
    output = bytearray(length)
    residuals = bytearray(length)
    zero_counts = [1] * 32
    order_one = [_ORDER_ONE_INITIAL] * (_SYMBOLS * _SYMBOLS)
    order_one_totals = [_SYMBOLS * _ORDER_ONE_INITIAL] * _SYMBOLS
    order_zero = [_ORDER_ZERO_INITIAL] * _SYMBOLS
    order_zero_total = _SYMBOLS * _ORDER_ZERO_INITIAL
    order_two: dict[int, list[int]] = {}
    previous = 0
    for offset in range(length):
        x = offset % width
        y = offset // width
        zero_off = _zero_context(residuals, offset, x, y, width) << 1
        zero = zero_counts[zero_off]
        nonzero = zero_counts[zero_off + 1]
        freq = decoder.frequency(zero + nonzero)
        bit = 0 if freq < zero else 1
        decoder.decode(0 if bit == 0 else zero,
                       zero if bit == 0 else nonzero)
        zero_counts[zero_off + bit] += _ZERO_INCREMENT
        if zero_counts[zero_off] + zero_counts[zero_off + 1] >= _ZERO_LIMIT:
            zero_counts[zero_off] = (zero_counts[zero_off] >> 1) or 1
            zero_counts[zero_off + 1] = (zero_counts[zero_off + 1] >> 1) or 1
        symbol = 0
        if bit == 1:
            above = residuals[offset - width] if offset >= width else 0
            second = _order_two(order_two, (previous << 8) | above)
            first_off = previous << 8
            excluded = (second[0] + order_one[first_off]
                        + order_zero[0])
            total = (second[_TOTAL_INDEX] + order_one_totals[previous]
                     + order_zero_total - excluded)
            target = decoder.frequency(total)
            cumulative = 0
            symbol = 1
            frequency = (second[1] + order_one[first_off + 1]
                         + order_zero[1])
            while cumulative + frequency <= target:
                cumulative += frequency
                symbol += 1
                if symbol >= _SYMBOLS:
                    raise MaskDecodeError(
                        "Lossless mask payload is malformed.")
                frequency = (second[symbol] + order_one[first_off + symbol]
                             + order_zero[symbol])
            decoder.decode(cumulative, frequency)
            second[symbol] += _ORDER_TWO_STEP
            second[_TOTAL_INDEX] += _ORDER_TWO_STEP
            if second[_TOTAL_INDEX] >= _ORDER_TWO_LIMIT:
                scaled_total = 0
                for value in range(_SYMBOLS):
                    second[value] >>= 1
                    scaled_total += second[value]
                second[_TOTAL_INDEX] = scaled_total
            order_one[first_off + symbol] += _ORDER_ONE_INCREMENT
            order_one_totals[previous] += _ORDER_ONE_INCREMENT
            if order_one_totals[previous] >= _ORDER_ONE_LIMIT:
                scaled_total = 0
                for value in range(_SYMBOLS):
                    scaled = (order_one[first_off + value] >> 1) or 1
                    order_one[first_off + value] = scaled
                    scaled_total += scaled
                order_one_totals[previous] = scaled_total
            order_zero[symbol] += _ORDER_ZERO_STEP
            order_zero_total += _ORDER_ZERO_STEP
            if order_zero_total >= _ORDER_ZERO_LIMIT:
                scaled_total = 0
                for value in range(_SYMBOLS):
                    order_zero[value] >>= 1
                    scaled_total += order_zero[value]
                order_zero_total = scaled_total
        residuals[offset] = symbol
        output[offset] = _unzig(
            symbol, _predict_byte(output, offset, x, y, selector, width))
        previous = symbol
    return bytes(output)


def _context_at(raster: bytearray, position: int, prior: int,
                earlier: int) -> int:
    return (raster[position - 1]
            | (raster[position - 2] << 1)
            | (raster[prior - 2] << 2)
            | (raster[prior - 1] << 3)
            | (raster[prior] << 4)
            | (raster[prior + 1] << 5)
            | (raster[prior + 2] << 6)
            | (raster[earlier - 2] << 7)
            | (raster[earlier - 1] << 8)
            | (raster[earlier] << 9)
            | (raster[earlier + 1] << 10)
            | (raster[earlier + 2] << 11))


def _update_counts(counts: list[int], offset: int, bit: int) -> None:
    counts[offset + bit] += _INCREMENT
    if counts[offset] + counts[offset + 1] >= _COUNT_LIMIT:
        counts[offset] = (counts[offset] >> 1) or 1
        counts[offset + 1] = (counts[offset + 1] >> 1) or 1


def _encode_one_bit(raster: bytes, width: int, height: int) -> str:
    encoder = _RangeEncoder()
    counts = [1] * (_CONTEXT_COUNT * 2)
    padded_width = width + 2 * _PADDING
    padded = bytearray(padded_width * (height + _PADDING))
    for y in range(height):
        row = (y + _PADDING) * padded_width + _PADDING
        for x in range(width):
            position = row + x
            context = _context_at(padded, position, position - padded_width,
                                  position - 2 * padded_width)
            offset = context << 1
            zero = counts[offset]
            one = counts[offset + 1]
            bit = raster[y * width + x]
            if bit != 0 and bit != 1:
                raise MaskDecodeError("Mask raster must be binary.")
            if bit == 0:
                encoder.encode(0, zero, zero + one)
            else:
                encoder.encode(zero, one, zero + one)
            padded[position] = bit
            _update_counts(counts, offset, bit)
    return "!" + _b85_pack(encoder.finish())


def _decode_one_bit(payload: str, width: int, height: int) -> bytes:
    decoder = _RangeDecoder(
        _b85_unpack(payload[1:], max_bytes=width * height * 2 + 1024))
    counts = [1] * (_CONTEXT_COUNT * 2)
    padded_width = width + 2 * _PADDING
    padded = bytearray(padded_width * (height + _PADDING))
    output = bytearray(width * height)
    for y in range(height):
        row = (y + _PADDING) * padded_width + _PADDING
        for x in range(width):
            position = row + x
            context = _context_at(padded, position, position - padded_width,
                                  position - 2 * padded_width)
            offset = context << 1
            zero = counts[offset]
            one = counts[offset + 1]
            value = decoder.frequency(zero + one)
            bit = 0 if value < zero else 1
            if bit == 0:
                decoder.decode(0, zero)
            else:
                decoder.decode(zero, one)
            padded[position] = bit
            output[y * width + x] = bit
            _update_counts(counts, offset, bit)
    return bytes(output)


def encode_mask_one_bit(raster: bytes, width: int, height: int) -> str:
    """Encode a binary raster (port of `encodeSegmentationMask`).

    Used for the one_bit canonicality check and for building
    deterministic conformance vectors in tests.
    """
    if (not isinstance(width, int) or isinstance(width, bool)
            or not isinstance(height, int) or isinstance(height, bool)
            or width <= 0 or height <= 0
            or width * height != len(raster)):
        raise MaskDecodeError(
            "Mask raster dimensions do not match its payload.")
    return _encode_one_bit(bytes(raster), width, height)


def decode_mask_to_raster(*, encoding: str, width: int, height: int,
                          payload: str) -> bytes:
    """Decode one complete mask to row-major 0/1 bytes (H*W entries).

    `payload` carries its leading marker (`~`/`!`), like the reference
    `mask.payload`. Raises `MaskDecodeError` when the payload is
    malformed, non-canonical, or over budget — never a partial raster.
    """
    try:
        if encoding != "one_bit" and encoding != "lossless":
            raise MaskDecodeError(
                f"Unsupported mask encoding: {encoding}.")
        for name, dim in (("width", width), ("height", height)):
            if (not isinstance(dim, int) or isinstance(dim, bool)
                    or dim <= 0):
                raise MaskDecodeError(
                    f"Mask {name} must be a positive integer.")
        if width * height > MAX_MASK_PIXELS:
            raise MaskDecodeError("Mask raster exceeds the decode budget.")
        if not isinstance(payload, str):
            raise MaskDecodeError("Mask payload must be a string.")
        if encoding == "one_bit":
            if not payload.startswith("!"):
                raise MaskDecodeError(
                    "one_bit mask payloads must start with !.")
            raster = _decode_one_bit(payload, width, height)
            if _encode_one_bit(raster, width, height) != payload:
                raise MaskDecodeError(
                    "Mask payload is not canonical or has invalid "
                    "finalization.")
            return raster
        if not payload.startswith("~"):
            raise MaskDecodeError(
                "lossless mask payloads must start with ~.")
        coverage = _decode_lossless(payload, width, height)
        return bytes(1 if value >= 129 else 0 for value in coverage)
    except MaskDecodeError:
        raise
    except Exception as exc:
        raise MaskDecodeError(
            "Mask payload could not be decoded.") from exc
