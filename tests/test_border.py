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
