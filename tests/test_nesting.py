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


def test_nest_simplifies_high_vertex_contour():
    import numpy as np
    th = np.linspace(0, 2 * np.pi, 720, endpoint=False)
    contour = [(int(300 + 250 * np.cos(t)), int(300 + 250 * np.sin(t))) for t in th]
    layer = np.zeros((600, 600, 4), np.uint8); layer[:, :, 3] = 255
    mask = np.full((600, 600), 255, np.uint8)
    p = Part(id="c", image_layer=layer, mask=mask, contour=contour)
    poly = nesting.part_polygon(p)
    assert len(poly.exterior.coords) < 120   # 顶点大幅减少
    out = nesting.nest([p])
    assert out[0].x >= 0                      # 仍能放下


def test_nest_footprint_matches_image_for_build_part():
    """nest 后，零件碰撞多边形应与其 image_layer 矩形对齐(导出贴图不偏移/不溢出板)。"""
    import numpy as np, cv2
    from app import part_builder as pb
    from app import geometry as g
    img = np.full((400, 400, 3), 255, np.uint8)
    cv2.circle(img, (200, 200), 70, (0, 140, 200), -1)
    mask = np.zeros((400, 400), np.uint8)
    cv2.circle(mask, (200, 200), 70, 255, -1)
    part = pb.build_part(img, mask)
    nesting.nest([part])
    assert part.x >= 0 and part.y >= 0
    poly = nesting.part_polygon(part)
    minx, miny, maxx, maxy = poly.bounds
    # 碰撞多边形必须落在 image_layer 在(x,y)处占据的矩形内(含少量简化容差)
    tol = nesting.SIMPLIFY_TOLERANCE_PX + 1
    assert minx >= part.x - tol and miny >= part.y - tol
    assert maxx <= part.x + part.w + tol and maxy <= part.y + part.h + tol
    # 整体在 A4 板内
    assert maxx <= g.A4_WIDTH_PX and maxy <= g.A4_HEIGHT_PX
