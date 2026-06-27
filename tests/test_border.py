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
