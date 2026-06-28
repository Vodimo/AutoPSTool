"""把排好版的零件渲染为单张 A4 PNG：白底 + 主体 + 洋红刀模线。

重构为「逐零件 tile → 按角度旋转 → 居中粘贴」，支持 part.rotation 与 part.cx/cy。
"""
import math

from PIL import Image, ImageDraw

from app import geometry as g
from app import vectorize as vz
from app import border


def _draw_polyline(draw, pts, fill, width=2):
    if len(pts) >= 2:
        draw.line(pts + [pts[0]], fill=fill, width=width)


def _build_tile(part, offset_px: float) -> tuple["Image.Image", float, float]:
    """构建未旋转的 RGBA tile，返回 (tile, tile_w0, tile_h0)。

    参数化零件：白多边形 + 主体图 + 洋红刀模线，以 poly 局部坐标为基准。
    固定零件：image_layer 缩放 + 洋红刀模线。
    返回 tile_w0/h0 为未旋转时的宽/高（浮点，供居中计算用）。
    """
    s = part.scale

    if part.subject_outline:
        # —— 参数化零件 ——
        poly = border.dieline_polygon(part.subject_outline, offset_px)
        if poly.is_empty:
            return Image.new("RGBA", (1, 1), (0, 0, 0, 0)), 1.0, 1.0
        minx, miny, maxx, maxy = poly.bounds
        tw = max(1, math.ceil((maxx - minx) * s))
        th = max(1, math.ceil((maxy - miny) * s))
        tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        draw = ImageDraw.Draw(tile)

        # 白底多边形（tile 局部坐标）
        ring = list(poly.exterior.coords)
        local_pts = [((px - minx) * s, (py - miny) * s) for (px, py) in ring]
        if len(local_pts) >= 3:
            draw.polygon(local_pts, fill=(255, 255, 255, 255))

        # 贴主体图：主体局部原点(0,0) 对应 poly 内位置 = (-minx,-miny)
        subj = Image.fromarray(part.subject_image, mode="RGBA")
        if s != 1.0:
            subj = subj.resize(
                (max(1, int(subj.width * s)), max(1, int(subj.height * s))),
                Image.LANCZOS,
            )
        sx_off = int(round((0 - minx) * s))
        sy_off = int(round((0 - miny) * s))
        tile.alpha_composite(subj, (sx_off, sy_off))

        # 洋红刀模线
        _draw_polyline(draw, local_pts, g.DIECUT_RGB + (255,))
    else:
        # —— 固定零件 ——
        layer = Image.fromarray(part.image_layer, mode="RGBA")
        if s != 1.0:
            layer = layer.resize(
                (max(1, int(part.w * s)), max(1, int(part.h * s))), Image.LANCZOS
            )
        tile = layer.copy()
        draw = ImageDraw.Draw(tile)
        src = part.dieline_path
        if src:
            for poly in vz.path_to_polylines(src):
                pts = [(px * s, py * s) for (px, py) in poly]
                _draw_polyline(draw, pts, g.DIECUT_RGB + (255,))
        else:
            pts = [(px * s, py * s) for (px, py) in part.contour]
            _draw_polyline(draw, pts, g.DIECUT_RGB + (255,))

    return tile, float(tile.width), float(tile.height)


def render_png(parts, offset_mm=None, page_px=None):
    """RGBA 画布：每个零件渲染 tile → 按 rotation 旋转 → 居中粘贴。
    page_px=(宽,高) 指定输出分辨率，默认 A4 (2100×2970)。
    part.cx/cy 给定则以其为中心；否则以 (x + tile_w0/2, y + tile_h0/2) 为中心（向后兼容）。
    """
    if offset_mm is None:
        offset_mm = g.OFFSET_MM
    if page_px is None:
        page_px = (g.A4_WIDTH_PX, g.A4_HEIGHT_PX)
    offset_px = g.mm_to_px(offset_mm)
    canvas = Image.new("RGBA", page_px, (255, 255, 255, 255))

    for part in parts:
        # 跳过未放置零件：cx/cy 均为 None 时依赖 x,y；x<0 则跳过
        if part.cx is None and (part.x < 0 or part.y < 0):
            continue

        tile, tile_w0, tile_h0 = _build_tile(part, offset_px)
        if tile.width <= 1 and tile.height <= 1:
            continue

        # 旋转（PIL 逆时针为正，fabric 顺时针为正，故取负）
        if part.rotation:
            tile = tile.rotate(-part.rotation, resample=Image.BICUBIC, expand=True)

        # 居中坐标：cx/cy 优先，否则用 topleft + 未旋转半尺寸
        if part.cx is not None:
            cx, cy = part.cx, part.cy
        else:
            cx = part.x + tile_w0 / 2
            cy = part.y + tile_h0 / 2

        paste_x = round(cx - tile.width / 2)
        paste_y = round(cy - tile.height / 2)
        canvas.alpha_composite(tile, (paste_x, paste_y))

    return canvas


def save_png(parts, out_path, offset_mm=None, page_px=None):
    render_png(parts, offset_mm=offset_mm, page_px=page_px).save(out_path)
