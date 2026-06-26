import numpy as np
from app import nesting
from app.models import Part


def _box_part(pid, size=200):
    """一个边长 size 的实心方块零件（轮廓为方框）。"""
    layer = np.zeros((size, size, 4), np.uint8)
    layer[:, :, 3] = 255
    mask = np.full((size, size), 255, np.uint8)
    contour = [(0, 0), (size - 1, 0), (size - 1, size - 1), (0, size - 1)]
    return Part(id=pid, image_layer=layer, mask=mask, contour=contour)


def test_nest_positions_within_board():
    parts = [_box_part("a"), _box_part("b")]
    out = nesting.nest(parts, padding_mm=2.0)
    from app import geometry as g
    for p in out:
        assert 0 <= p.x and 0 <= p.y
        assert p.x + p.w <= g.A4_WIDTH_PX
        assert p.y + p.h <= g.A4_HEIGHT_PX


def test_nest_no_overlap():
    parts = [_box_part("a"), _box_part("b")]
    out = nesting.nest(parts, padding_mm=2.0)
    pa = nesting.part_polygon(out[0])
    pb = nesting.part_polygon(out[1])
    assert not pa.intersects(pb)
