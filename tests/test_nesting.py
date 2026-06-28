"""test_nesting.py — 新契约：中心+角度坐标，覆盖旋转感知BLF、间距、统一缩放。"""
import numpy as np
import cv2
import pytest

from app import nesting, geometry as g
from app.models import Part
from app import part_builder as pb
from tests.conftest import make_white_bg_image, make_blob_mask


# ─── 构造辅助 ──────────────────────────────────────────────────────────────────

def _build_circle_part(pid="p", radius=60, offset_mm=2.0):
    """白底+单圆的合成零件（含 subject_outline，走参数化路径）。"""
    img = make_white_bg_image(size=(300, 300), centers=((150, 150),), radius=radius)
    mask = make_blob_mask(size=(300, 300), centers=((150, 150),), radius=radius)
    return pb.build_part(img, mask, offset_mm=offset_mm, part_id=pid)


def _build_ellipse_part(pid="e", w=600, h=80, offset_mm=2.0):
    """白底+水平椭圆的零件，用于旋转测试。"""
    size = (h + 80, w + 80)   # 留白边
    img = np.full((size[0], size[1], 3), 255, np.uint8)
    mask = np.zeros((size[0], size[1]), np.uint8)
    cy, cx = size[0] // 2, size[1] // 2
    cv2.ellipse(img,  (cx, cy), (w // 2, h // 2), 0, 0, 360, (0, 140, 200), -1)
    cv2.ellipse(mask, (cx, cy), (w // 2, h // 2), 0, 0, 360, 255, -1)
    return pb.build_part(img, mask, offset_mm=offset_mm, part_id=pid)


# ─── 测试 ──────────────────────────────────────────────────────────────────────

def test_nest_centers_within_page():
    """两个零件排版后 cx/cy 均在页面内，且多边形落在 A4 内。"""
    p1 = _build_circle_part("a", radius=60)
    p2 = _build_circle_part("b", radius=60)
    page_px = (g.A4_WIDTH_PX, g.A4_HEIGHT_PX)
    board = __import__("shapely.geometry", fromlist=["box"]).box(0, 0, *page_px)

    nesting.nest([p1, p2], angle_steps=1, page_px=page_px)

    for p in (p1, p2):
        assert p.cx is not None and p.cx >= 0, f"{p.id}: cx={p.cx} 表示未放置"
        assert p.cy is not None and p.cy >= 0, f"{p.id}: cy={p.cy} 表示未放置"
        poly = nesting.part_polygon(p)
        assert poly.within(board) or poly.intersects(board), \
            f"{p.id}: 多边形超出页面"
        # 更严格：多边形应在页面内（允许 spacing buffer 的少量浮动）
        tol = g.mm_to_px(g.PADDING_MM) + nesting.SIMPLIFY_TOLERANCE_PX
        minx, miny, maxx, maxy = poly.bounds
        assert minx >= -tol and miny >= -tol
        assert maxx <= g.A4_WIDTH_PX + tol and maxy <= g.A4_HEIGHT_PX + tol


def test_nest_no_overlap_centers():
    """两个零件排版后的碰撞多边形不互相交叉。"""
    p1 = _build_circle_part("a", radius=60)
    p2 = _build_circle_part("b", radius=60)
    page_px = (g.A4_WIDTH_PX, g.A4_HEIGHT_PX)

    nesting.nest([p1, p2], angle_steps=1, page_px=page_px)

    # 两者均需放置
    assert p1.cx >= 0 and p2.cx >= 0

    poly1 = nesting.part_polygon(p1)
    poly2 = nesting.part_polygon(p2)

    # 加上间距 buffer 后不相交
    spacing_px = g.mm_to_px(g.PADDING_MM)
    buf1 = poly1.buffer(spacing_px / 2.0, join_style=2)
    buf2 = poly2.buffer(spacing_px / 2.0, join_style=2)
    assert not buf1.intersects(buf2), "排版后两零件间距 buffer 不应相交"


def test_nest_rotation_helps_fit():
    """细长零件在窄页：angle_steps=1（只 0°）放不下，angle_steps=4（含 90°）可放下。"""
    # 椭圆：宽 400px，高 60px（加白边约 440×100）
    ellipse_w, ellipse_h = 400, 60
    # 窄页：宽 250px（放不下 440）、高 1500px（放得下 100）
    page_px = (250, 1500)

    p_no_rot = _build_ellipse_part("e1", w=ellipse_w, h=ellipse_h)
    nesting.nest([p_no_rot], angle_steps=1, page_px=page_px)

    p_with_rot = _build_ellipse_part("e2", w=ellipse_w, h=ellipse_h)
    nesting.nest([p_with_rot], angle_steps=4, page_px=page_px)

    # angle_steps=4（90° 旋转后变 100 宽）能放下；angle_steps=1 可能放不下
    assert p_with_rot.cx >= 0, \
        f"angle_steps=4 应能旋转放置，cx={p_with_rot.cx}"
    # angle_steps=1 时放不下（宽约 440 > 250）
    assert p_no_rot.cx < 0, \
        f"angle_steps=1 在宽 {page_px[0]}px 页面上不应能放下宽 {ellipse_w}px 的椭圆"


def test_uniform_scale_fits_more():
    """uniform_scale=True 时整体缩小，使多个在小页放不下的零件全部放下。"""
    # 4 个大圆（半径 100，约 240px），在 400×400 页面各自占大量空间
    parts = [_build_circle_part(f"u{i}", radius=100) for i in range(4)]
    page_px = (400, 400)  # 足够小，4 个大圆放不下

    # 不缩放排版：应有放不下的
    parts_no_scale = [_build_circle_part(f"n{i}", radius=100) for i in range(4)]
    nesting.nest(parts_no_scale, angle_steps=1, uniform_scale=False, page_px=page_px)
    no_scale_placed = sum(1 for p in parts_no_scale if p.cx >= 0)

    # 统一缩放排版：全部应能放下（缩放后 scale < 1）
    nesting.nest(parts, angle_steps=1, uniform_scale=True, page_px=page_px)
    scale_placed = sum(1 for p in parts if p.cx >= 0)

    assert scale_placed > no_scale_placed, \
        f"uniform_scale 应放置更多零件，但 {scale_placed} <= {no_scale_placed}"
    assert scale_placed == len(parts), \
        f"uniform_scale 应放置全部 {len(parts)} 个，实际 {scale_placed}"
    # 缩放系数应小于 1
    for p in parts:
        assert p.scale < 1.0, f"{p.id}: uniform_scale 后 scale={p.scale:.3f} 应 < 1"
