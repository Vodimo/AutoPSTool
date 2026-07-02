import numpy as np
import cv2
from PIL import Image
from app import exporter
from app import geometry as g
from app import part_builder as pb
from app.models import Part


def _box_part(pid, size=200, x=100, y=100):
    layer = np.zeros((size, size, 4), np.uint8)
    layer[:, :, :3] = 255
    layer[:, :, 3] = 255
    mask = np.full((size, size), 255, np.uint8)
    contour = [(0, 0), (size - 1, 0), (size - 1, size - 1), (0, size - 1)]
    p = Part(id=pid, image_layer=layer, mask=mask, contour=contour)
    p.x, p.y = x, y
    return p


def test_render_size_is_a4():
    img = exporter.render_png([_box_part("a")])
    assert img.size == (g.A4_WIDTH_PX, g.A4_HEIGHT_PX)


def test_render_has_magenta_dieline():
    img = exporter.render_png([_box_part("a")]).convert("RGB")
    arr = np.array(img)
    # 存在洋红像素
    magenta = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 60) & (arr[:, :, 2] > 200)
    assert magenta.sum() > 0


def test_render_uses_vector_dieline_smooth():
    # 真实零件(带矢量刀模)：圆形,导出后洋红像素应勾出近圆而非方框
    img = np.full((300, 300, 3), 255, np.uint8)
    cv2.circle(img, (150, 150), 90, (0, 140, 200), -1)
    mask = np.zeros((300, 300), np.uint8)
    cv2.circle(mask, (150, 150), 90, 255, -1)
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    part.x, part.y = 100, 100
    arr = np.array(exporter.render_png([part]).convert("RGB"))
    magenta = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 60) & (arr[:, :, 2] > 200)
    assert magenta.sum() > 0
    # 矢量刀模应是非空闭合曲线，洋红像素分布在一圈而非聚成一团
    ys, xs = np.where(magenta)
    assert (xs.max() - xs.min()) > 150 and (ys.max() - ys.min()) > 150


def _para_part(x=100, y=100):
    img = np.full((300, 300, 3), 255, np.uint8)
    cv2.circle(img, (150, 150), 90, (0, 140, 200), -1)
    mask = np.zeros((300, 300), np.uint8)
    cv2.circle(mask, (150, 150), 90, 255, -1)
    p = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    p.x, p.y = x, y
    return p


def test_render_offset_grows_white_and_magenta_extent():
    p = _para_part()
    a = np.array(exporter.render_png([p], offset_mm=2.0).convert("RGB"))
    b = np.array(exporter.render_png([p], offset_mm=6.0).convert("RGB"))

    def magenta_extent(arr):
        m = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 60) & (arr[:, :, 2] > 200)
        ys, xs = np.where(m)
        return (xs.max() - xs.min()) if len(xs) else 0

    ea, eb = magenta_extent(a), magenta_extent(b)
    assert ea > 0 and eb > ea          # 白边越大，刀模外延越大


def test_render_custom_page_size():
    """render_png page_px 参数：自定义尺寸返回对应 PIL 图；默认仍 A4。"""
    p = _para_part()
    # 自定义页面尺寸 800×600
    img_custom = exporter.render_png([p], page_px=(800, 600))
    assert img_custom.size == (800, 600), f"期望 (800,600)，实际 {img_custom.size}"
    # 默认仍为 A4
    img_default = exporter.render_png([p])
    assert img_default.size == (g.A4_WIDTH_PX, g.A4_HEIGHT_PX), \
        f"期望 A4 ({g.A4_WIDTH_PX},{g.A4_HEIGHT_PX})，实际 {img_default.size}"


def test_render_skips_unplaced_cx():
    """cx<0（排版未放下）的零件不应被渲染（原实现会部分画在页角）。"""
    p = _para_part()
    p.cx = p.cy = -1.0
    arr = np.array(exporter.render_png([p]).convert("RGB"))
    magenta = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 60) & (arr[:, :, 2] > 200)
    assert magenta.sum() == 0, "未放置零件不应出现在导出图中"


def _ellipse_part():
    """构建明显非方形的参数化零件（宽扁椭圆：240px 宽 × 100px 高）。"""
    img = np.full((300, 300, 3), 255, np.uint8)
    cv2.ellipse(img, (150, 150), (120, 50), 0, 0, 360, (0, 140, 200), -1)
    mask = np.zeros((300, 300), np.uint8)
    cv2.ellipse(mask, (150, 150), (120, 50), 0, 0, 360, 255, -1)
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="ellipse")
    return part


def _magenta_bbox(arr_rgb):
    """返回洋红像素的宽高 (w, h)；若无洋红像素则返回 (0, 0)。"""
    magenta = (arr_rgb[:, :, 0] > 200) & (arr_rgb[:, :, 1] < 60) & (arr_rgb[:, :, 2] > 200)
    ys, xs = np.where(magenta)
    if len(xs) == 0:
        return 0, 0
    return int(xs.max() - xs.min()), int(ys.max() - ys.min())


def test_render_rotation_swaps_bbox():
    """旋转 90° 后洋红刀模 bbox 的宽高应互换（误差 < 20%）。"""
    p = _ellipse_part()
    cx, cy = 1000.0, 1000.0

    # rotation=0 → 量宽高 (w0, h0)
    p.cx, p.cy = cx, cy
    p.rotation = 0.0
    arr0 = np.array(exporter.render_png([p]).convert("RGB"))
    w0, h0 = _magenta_bbox(arr0)
    assert w0 > 0 and h0 > 0, "rotation=0 时应有洋红像素"

    # rotation=90 → 量宽高 (w1, h1)，预期 w1≈h0，h1≈w0
    p.rotation = 90.0
    arr1 = np.array(exporter.render_png([p]).convert("RGB"))
    w1, h1 = _magenta_bbox(arr1)
    assert w1 > 0 and h1 > 0, "rotation=90 时应有洋红像素"

    # 旋转 90° 后宽高近似互换（20% 容差）
    assert abs(w1 - h0) < 0.2 * h0, f"旋转后宽({w1})应≈原高({h0})"
    assert abs(h1 - w0) < 0.2 * w0, f"旋转后高({h1})应≈原宽({w0})"
