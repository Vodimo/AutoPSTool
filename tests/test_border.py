import numpy as np
import cv2
from app import border
from app import vectorize as vz


def _circle_outline_d(r=60, cx=100, cy=100, size=200):
    m = np.zeros((size, size), np.uint8)
    cv2.circle(m, (cx, cy), r, 255, -1)
    return vz.trace_mask(m)


def test_dieline_polygon_grows_with_offset():
    d = _circle_outline_d(r=60)
    p0 = border.dieline_polygon(d, 0.0)
    p20 = border.dieline_polygon(d, 20.0)
    assert p20.area > p0.area
    # 半径约从 60 增到 80：面积比 ~ (80/60)^2 ≈ 1.78
    assert 1.5 < (p20.area / p0.area) < 2.1


def test_dieline_polygon_bbox_expands_by_offset():
    d = _circle_outline_d(r=60, cx=100, cy=100)
    minx, miny, maxx, maxy = border.dieline_polygon(d, 20.0).bounds
    # 圆心 100，半径 60+20=80 → bbox ≈ [20,180]
    assert 12 <= minx <= 28 and 172 <= maxx <= 188


def test_smooth_ring_chaikin():
    """Chaikin 平滑：点数每迭代×2；方形折角被切圆（顶点远离原角点）；0 迭代原样。"""
    square = [(0, 0), (100, 0), (100, 100), (0, 100)]
    assert border.smooth_ring(square, 0) == [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    s2 = border.smooth_ring(square, 2)
    assert len(s2) == 16
    # 平滑后所有点到最近原角点的距离 > 0（角被切掉）
    import math
    for x, y in s2:
        dmin = min(math.hypot(x - cx, y - cy) for cx, cy in square)
        assert dmin > 5, "折角应被切圆"


def test_dieline_polygon_smooth_keeps_shape():
    """平滑后的刀模多边形面积与 bbox 变化很小（切角收缩有限）。"""
    d = _circle_outline_d(r=60)
    p0 = border.dieline_polygon(d, 20.0)
    p2 = border.dieline_polygon(d, 20.0, smooth_iters=2)
    assert 0.97 < (p2.area / p0.area) <= 1.0 + 1e-9
    b0, b2 = p0.bounds, p2.bounds
    assert all(abs(a - b) < 4 for a, b in zip(b0, b2))


def test_dieline_path_at_is_closed_d():
    d = _circle_outline_d(r=50)
    out = border.dieline_path_at(d, 10.0)
    assert out.startswith("M") and out.strip().endswith("Z")


def test_empty_outline_returns_empty():
    assert border.dieline_polygon("", 10.0).is_empty
    assert border.dieline_path_at("", 10.0) == ""


def test_outer_polyline_ignores_hole_single_smooth_ring():
    # 带洞主体：外圈 r=90 + 内洞 r=30。potrace 出 2 条子路径(外+洞)。
    m = np.zeros((300, 300), np.uint8)
    cv2.circle(m, (150, 150), 90, 255, -1)
    cv2.circle(m, (150, 150), 30, 0, -1)
    d = vz.trace_mask(m)
    ring = border.outer_polyline(d)
    # 平滑(远多于端点法的寥寥几点)但已简化(不至于上百冗余点)
    assert 12 <= len(ring) < 200
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    # 取的是外环(直径~180)，不是洞(直径~60)
    assert (max(xs) - min(xs)) > 150 and (max(ys) - min(ys)) > 150
    # 元素是 [x, y] 数值对
    assert len(ring[0]) == 2


def test_outer_polyline_empty_outline():
    assert border.outer_polyline("") == []
