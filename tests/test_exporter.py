import numpy as np
from PIL import Image
from app import exporter
from app import geometry as g
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
