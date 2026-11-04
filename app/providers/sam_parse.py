"""SAM 3.1 segmentation-lane grammar parser (pure, deterministic).

Implements the documented output grammar (dev.meta.ai/docs/sam/
reading-segmentation, verified 2026-11-01):

* the lane holds one line per emitted frame;
* a line is a `<Nf>` frame marker plus comma-separated records;
* a record is an integer object id, exactly one box token, then
  exactly one mask token (`id<|box;...|><|mask;...|>`);
* box corners are inclusive source pixels with the frame size in
  `w`/`h`; the mask origin is the literal `x=0;y=0`;
* an optional `;c=` confidence (0..1) rides inside box/mask tokens
  when requested — there is no standalone confidence field;
* frame indices are zero-based and may skip or run out of order;
  object ids are sparse integers, stable within one response;
* mask payloads use the official base85 alphabet (see
  `app.providers.sam_mask`); raster decoding lives there.

Raises `SamGrammarError` on any deviation — never partial results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.providers.sam_mask import MAX_MASK_PIXELS, is_payload_char

_FRAME_RE = re.compile(r"<(\d+)f>")
_ID_RE = re.compile(r"\d+")
_INT_RE = re.compile(r"\d+")
_CONF_RE = re.compile(r"\d+(\.\d+)?")

# Sanity bounds (fail closed past them; set above the documented
# limits of 15,000 frames per clip and 16 tracked objects per video
# frame, since still images may legitimately carry many instances).
MAX_FRAMES = 20_000
MAX_OBJECTS_PER_FRAME = 1_000
MAX_DIMENSION = 100_000
_MAX_CONF_CHARS = 32


class SamGrammarError(ValueError):
    """The lane deviates from the documented grammar."""


@dataclass(frozen=True)
class ParsedBox:
    object_id: str
    x1: int
    y1: int
    x2: int
    y2: int
    width: int
    height: int
    confidence: float | None = None


@dataclass(frozen=True)
class ParsedMask:
    object_id: str
    raster_h: int
    raster_w: int
    encoding: str  # "lossless" | "one_bit"
    payload: str  # base85 text after the encoding marker
    confidence: float | None = None


@dataclass(frozen=True)
class ParsedFrame:
    index: int
    boxes: tuple[ParsedBox, ...] = ()
    masks: tuple[ParsedMask, ...] = ()
    confidences: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class ParsedLane:
    frames: tuple[ParsedFrame, ...] = ()
    object_ids: frozenset[str] = field(default_factory=frozenset)


def _safe_int(text: str, *, what: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise SamGrammarError(f"{what} is not a usable integer") from None


def _parse_conf(value: str, *, what: str) -> float:
    if len(value) > _MAX_CONF_CHARS or not _CONF_RE.fullmatch(value):
        raise SamGrammarError(f"bad {what} confidence: {value[:16]!r}")
    confidence = float(value)
    if not 0.0 <= confidence <= 1.0:
        raise SamGrammarError(f"{what} confidence out of range")
    return confidence


_BOX_INT_FIELDS = frozenset({"x1", "y1", "x2", "y2", "w", "h"})


def _parse_box(object_id: str, body: str) -> ParsedBox:
    fields: dict[str, int] = {}
    confidence: float | None = None
    for chunk in body.split(";"):
        if not chunk:
            continue
        key, sep, value = chunk.partition("=")
        if not sep:
            raise SamGrammarError(f"bad box field: {chunk[:16]!r}")
        if key == "c":
            if confidence is not None:
                raise SamGrammarError("duplicate box confidence")
            confidence = _parse_conf(value, what="box")
            continue
        if key not in _BOX_INT_FIELDS:
            raise SamGrammarError(f"unknown box field: {key[:16]!r}")
        if key in fields:
            raise SamGrammarError(f"duplicate box field: {key!r}")
        if not _INT_RE.fullmatch(value):
            raise SamGrammarError(f"non-integer box field: {key!r}")
        fields[key] = _safe_int(value, what=f"box field {key}")
    for key in ("x1", "y1", "x2", "y2", "w", "h"):
        if key not in fields:
            raise SamGrammarError(f"box missing {key}")
    w, h = fields["w"], fields["h"]
    if w <= 0 or h <= 0 or w > MAX_DIMENSION or h > MAX_DIMENSION:
        raise SamGrammarError(f"box media size out of range: {w}x{h}")
    x1, y1, x2, y2 = fields["x1"], fields["y1"], fields["x2"], fields["y2"]
    # Corners are inclusive source pixels (documented).
    if not (0 <= x1 <= x2 < w and 0 <= y1 <= y2 < h):
        raise SamGrammarError("box coordinates out of bounds or inverted")
    return ParsedBox(object_id=object_id, x1=x1, y1=y1, x2=x2, y2=y2,
                     width=w, height=h, confidence=confidence)


def _parse_mask(object_id: str, body: str) -> ParsedMask:
    # Split ONLY on the first ";data=" — the payload itself never
    # contains ";" (excluded from the official alphabet).
    head, sep, data = body.partition(";data=")
    if not sep or not data:
        raise SamGrammarError("mask missing data")
    parts = head.split(";")
    if len(parts) not in (2, 3) or parts[0] != "x=0" or parts[1] != "y=0":
        raise SamGrammarError("mask origin must be the literal x=0;y=0")
    confidence: float | None = None
    if len(parts) == 3:
        key, eq, value = parts[2].partition("=")
        if key != "c" or not eq:
            raise SamGrammarError(f"bad mask field: {parts[2][:16]!r}")
        confidence = _parse_conf(value, what="mask")
    # data = H,W,<enc><payload>; the payload never contains ",".
    h_str, sep1, rest = data.partition(",")
    w_str, sep2, enc_payload = rest.partition(",")
    if not sep1 or not sep2 or not enc_payload:
        raise SamGrammarError("mask data missing raster header")
    if not _INT_RE.fullmatch(h_str) or not _INT_RE.fullmatch(w_str):
        raise SamGrammarError("mask raster size must be integers")
    raster_h = _safe_int(h_str, what="mask raster height")
    raster_w = _safe_int(w_str, what="mask raster width")
    if raster_h <= 0 or raster_w <= 0:
        raise SamGrammarError("mask raster size out of range")
    if raster_h * raster_w > MAX_MASK_PIXELS:
        raise SamGrammarError("mask raster too large")
    marker, payload = enc_payload[0], enc_payload[1:]
    if marker == "~":
        encoding = "lossless"
    elif marker == "!":
        encoding = "one_bit"
    else:
        raise SamGrammarError("mask payload missing encoding marker")
    if not payload:
        raise SamGrammarError("mask payload is empty")
    if len(payload) > raster_h * raster_w * 3 + 2048:
        raise SamGrammarError("mask payload exceeds raster bound")
    for char in payload:
        if not is_payload_char(char):
            raise SamGrammarError(
                f"mask payload has invalid char: {char!r}")
    return ParsedMask(object_id=object_id, raster_h=raster_h,
                      raster_w=raster_w, encoding=encoding, payload=payload,
                      confidence=confidence)


def _take_token(text: str, pos: int, kind: str) -> tuple[str, int]:
    opener = f"<|{kind};"
    if not text.startswith(opener, pos):
        raise SamGrammarError(f"expected {kind} token at offset {pos}")
    body_start = pos + len(opener)
    # First "|>" terminates: "|" never appears inside a token body
    # (excluded from the mask alphabet; box fields are numeric).
    end = text.find("|>", body_start)
    if end < 0:
        raise SamGrammarError(f"unterminated {kind} token")
    return text[body_start:end], end + 2


def _parse_record(text: str, pos: int
                  ) -> tuple[str, ParsedBox, ParsedMask, int]:
    match = _ID_RE.match(text, pos)
    if match is None:
        raise SamGrammarError(f"expected integer object id at offset {pos}")
    object_id = str(_safe_int(match.group(0), what="object id"))
    pos = match.end()
    box_body, pos = _take_token(text, pos, "box")
    mask_body, pos = _take_token(text, pos, "mask")
    box = _parse_box(object_id, box_body)
    mask = _parse_mask(object_id, mask_body)
    # Rasters are thumbnails of the frame, never larger than it.
    if mask.raster_h > box.height or mask.raster_w > box.width:
        raise SamGrammarError("mask raster larger than its frame")
    return object_id, box, mask, pos


def _parse_line_records(index: int, text: str) -> ParsedFrame:
    boxes: list[ParsedBox] = []
    masks: list[ParsedMask] = []
    confidences: list[tuple[str, float]] = []
    seen_ids: set[str] = set()
    if not text:
        raise SamGrammarError(f"frame {index} marker has no records")
    pos = 0
    while True:
        object_id, box, mask, pos = _parse_record(text, pos)
        if object_id in seen_ids:
            raise SamGrammarError(
                f"duplicate object id {object_id!r} on frame {index}")
        seen_ids.add(object_id)
        boxes.append(box)
        masks.append(mask)
        confidence = (box.confidence if box.confidence is not None
                      else mask.confidence)
        if confidence is not None:
            confidences.append((object_id, confidence))
        if pos >= len(text):
            break
        if text[pos] != ",":
            raise SamGrammarError(
                f"expected record separator at offset {pos}")
        pos += 1
        if pos >= len(text):
            raise SamGrammarError("trailing comma after last record")
    if len(seen_ids) > MAX_OBJECTS_PER_FRAME:
        raise SamGrammarError("frame exceeds object bound")
    return ParsedFrame(index=index, boxes=tuple(boxes), masks=tuple(masks),
                       confidences=tuple(confidences))


def parse_lane(lane: str) -> ParsedLane:
    """Parse one segmentation lane; empty lane = zero matches (valid)."""
    text = (lane or "").strip()
    if not text:
        return ParsedLane()
    frames: list[ParsedFrame] = []
    seen_frames: set[int] = set()
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            raise SamGrammarError("lane has an empty line")
        marker = _FRAME_RE.match(line)
        if marker is None:
            raise SamGrammarError("line has no frame marker")
        index = _safe_int(marker.group(1), what="frame index")
        if index in seen_frames:
            raise SamGrammarError(f"duplicate frame marker {index}")
        seen_frames.add(index)
        frames.append(_parse_line_records(index, line[marker.end():]))
        if len(frames) > MAX_FRAMES:
            raise SamGrammarError("lane exceeds frame bound")
    object_ids: set[str] = set()
    for frame in frames:
        object_ids.update(box.object_id for box in frame.boxes)
    return ParsedLane(frames=tuple(frames), object_ids=frozenset(object_ids))


def distinct_count(lane: ParsedLane) -> int:
    """Distinct object ids across all frames (track-aware count)."""
    return len(lane.object_ids)
