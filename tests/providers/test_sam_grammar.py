"""SAM lane grammar parser tests (pure, offline).

Vectors follow the documented grammar (dev.meta.ai/docs/sam/
reading-segmentation): one line per frame, `<Nf>` markers,
integer object ids, exactly one box then one mask per record,
inclusive box corners, literal `x=0;y=0` mask origins, optional
`;c=` confidences, official base85 payload alphabet. The error
matrix pins fail-closed behavior for every deviation class.
"""

from __future__ import annotations

import pytest

from app.providers.sam_parse import (
    SamGrammarError,
    distinct_count,
    parse_lane,
)

BOX = "<|box;x1=100;y1=100;x2=200;y2=220;w=640;h=480|>"
MASK = "<|mask;x=0;y=0;data=12,10,~ABABABAB|>"
MASK_ONE_BIT = "<|mask;x=0;y=0;data=27,60,!ABABABAB|>"

# Verbatim documented example (video frame 0, two objects, 320x334).
DOC_LINE = (
    "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|>"
    "<|mask;x=0;y=0;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/"
    "#Xd8%dX9x(|>,1<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334|>"
    "<|mask;x=0;y=0;data=27,48,~!!!!J!0c[q=Pj_zs=*4C4(/./x#:/`S_GnD`=o3?X{"
    "emCgO$y@|>"
)


def test_empty_lane_is_zero_matches():
    lane = parse_lane("")
    assert lane.frames == ()
    assert distinct_count(lane) == 0
    assert parse_lane("   \n ").frames == ()


def test_single_object_single_frame():
    lane = parse_lane(f"<0f>1{BOX}{MASK}")
    assert len(lane.frames) == 1
    frame = lane.frames[0]
    assert frame.index == 0
    assert len(frame.boxes) == 1
    box = frame.boxes[0]
    assert (box.object_id, box.x1, box.y1, box.x2, box.y2) == ("1", 100, 100,
                                                              200, 220)
    assert (box.width, box.height) == (640, 480)
    assert len(frame.masks) == 1
    mask = frame.masks[0]
    assert (mask.raster_h, mask.raster_w, mask.encoding) == (12, 10, "lossless")
    assert mask.payload == "ABABABAB"
    assert distinct_count(lane) == 1


def test_one_bit_marker_and_confidence_tokens():
    lane_text = (
        "<0f>1<|box;x1=0;y1=0;x2=10;y2=10;w=640;h=480;c=0.82|>"
        "<|mask;x=0;y=0;c=0.82;data=4,4,!ZZZZ|>")
    lane = parse_lane(lane_text)
    assert distinct_count(lane) == 1
    assert lane.frames[0].masks[0].encoding == "one_bit"
    assert lane.frames[0].confidences == (("1", 0.82),)


def test_multi_frame_newline_tracking_ids():
    lane = parse_lane(f"<0f>1{BOX}{MASK}\n<2f>1{BOX}{MASK},3{BOX}{MASK}")
    assert [frame.index for frame in lane.frames] == [0, 2]
    assert distinct_count(lane) == 2  # id 1 spans frames, counted once


def test_sparse_and_non_ascending_frames():
    lane = parse_lane(f"<30f>1{BOX}{MASK}\n<29f>2{BOX}{MASK}\n<0f>0{BOX}{MASK}")
    assert [frame.index for frame in lane.frames] == [30, 29, 0]
    assert lane.object_ids == frozenset({"1", "2", "0"})


def test_documented_example_line():
    lane = parse_lane(DOC_LINE)
    assert len(lane.frames) == 1
    frame = lane.frames[0]
    assert frame.index == 0
    assert [box.object_id for box in frame.boxes] == ["0", "1"]
    assert (frame.boxes[0].width, frame.boxes[0].height) == (320, 334)
    assert (frame.masks[0].raster_h, frame.masks[0].raster_w) == (27, 60)
    assert (frame.masks[1].raster_h, frame.masks[1].raster_w) == (27, 48)
    assert all(mask.encoding == "lossless" for mask in frame.masks)
    assert distinct_count(lane) == 2


@pytest.mark.parametrize("lane_text", [
    "1<|box;x1=0;y1=0;x2=1;y2=1;w=9;h=9|>",  # no frame marker
    "junk<0f>1" + BOX + MASK,  # leading content
    "<0f>",  # marker with no records
    "<0f>\n<1f>1" + BOX + MASK,  # marker with no records, multiline lane
    "<0f>1" + BOX + MASK + "<2f>1" + BOX + MASK,  # two markers, one line
    f"<0f>1{BOX}{MASK}<0f>1{BOX}{MASK}",  # duplicate frame
    f"<0f>1{BOX}{MASK}\n<0f>2{BOX}{MASK}",  # duplicate frame marker
    f"<0f>1{BOX}{MASK},1{BOX}{MASK}",  # duplicate id in frame
    f"<0f>obj-a{BOX}{MASK}",  # non-integer object id
    f"<0f>1.5{BOX}{MASK}",  # decimal object id
    "<0f>1",  # id with no tokens
    f"<0f>7{BOX}",  # box without mask
    "<0f>1<|mask;x=0;y=0;data=4,4,~ZZ|>",  # mask without box
    "<0f>1<|mask;x=0;y=0;data=4,4,~ZZ|>" + BOX,  # mask before box
    f"<0f>1{BOX}{MASK},",  # trailing comma
    f"<0f>1{BOX}{MASK},0.82",  # standalone confidence (not a record)
    "<0f>1<|box;x1=0;y1=0;x2=1;y2=1;w=9|>",  # box missing h
    "<0f>1<|box;x1=0;y1=0;x2=1;y2=1;w=9;h=9;z=1|>",  # unknown field
    "<0f>1<|box;x1=0;y1=0;x2=1;x2=2;y2=1;w=9;h=9|>",  # dup field
    "<0f>1<|box;x1=a;y1=0;x2=1;y2=1;w=9;h=9|>",  # non-int
    "<0f>1<|box;x1=5;y1=0;x2=1;y2=1;w=9;h=9|>",  # inverted x
    "<0f>1<|box;x1=0;y1=0;x2=9;y2=1;w=9;h=9|>",  # x2 out of bounds
    "<0f>1<|box;x1=0;y1=0;x2=1;y2=1;w=0;h=9|>",  # zero w
    "<0f>1<|box;x1=0;y1=0;x2=1;y2=1;w=9;h=9;c=2|>",  # c out of range
    "<0f>1<|box;x1=0;y1=0;x2=1;y2=1;w=9;h=9;c=no|>",  # c malformed
    "<0f>1" + BOX + "<|mask;x=1;y=0;data=4,4,~ZZ|>",  # mask origin not 0
    "<0f>1" + BOX + "<|mask;x=0;y=1;data=4,4,~ZZ|>",  # mask origin not 0
    "<0f>1<|mask;x=0;y=0|>" + BOX,  # mask missing data
    "<0f>1<|mask;x=0;y=0;data=4|>" + BOX,  # data missing raster header
    "<0f>1<|mask;x=0;y=0;data=4,4,ZZZ|>" + BOX,  # missing enc marker
    "<0f>1<|mask;x=0;y=0;data=4,4,~|>" + BOX,  # empty payload
    "<0f>1<|mask;x=0;y=0;data=0,4,~ZZ|>" + BOX,  # zero raster dim
    "<0f>1<|mask;x=0;y=0;data=4,4,~ZZ ZZ|>" + BOX,  # payload whitespace
    "<0f>1<|mask;x=0;y=0;data=4,4,~ZZ}ZZ|>" + BOX,  # payload invalid char
    "<0f>1<|mask;x=0;y=0;data=4,4,~ZZ|ZZ|>" + BOX,  # payload pipe char
    f"<0f>1{BOX}{MASK},abc",  # trailing garbage id without tokens
    "<0f>1<|box;x1=0;y1=0;x2=1;y2=1;w=9;h=9|>"
    "<|mask;x=0;y=0;data=10,10,~ZZ|>",  # raster larger than frame
])
def test_grammar_error_matrix(lane_text):
    with pytest.raises(SamGrammarError):
        parse_lane(lane_text)


def test_mask_payload_size_bound():
    with pytest.raises(SamGrammarError):
        parse_lane("<0f>1<|box;x1=0;y1=0;x2=7;y2=7;w=8;h=8|>"
                   "<|mask;x=0;y=0;data=2,2,~" + "A" * 5000 + "|>")


def test_box_confidence_without_mask_confidence():
    # `c` is accepted on either token; only range and placement are
    # enforced, and the box value is recorded.
    lane = parse_lane(
        "<0f>3<|box;x1=0;y1=0;x2=1;y2=1;w=9;h=9;c=1|>"
        "<|mask;x=0;y=0;data=2,2,~AB|>")
    assert lane.frames[0].confidences == (("3", 1.0),)
