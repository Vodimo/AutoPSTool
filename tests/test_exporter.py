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
