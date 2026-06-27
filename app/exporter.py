"""把排好版的零件渲染为单张 A4 PNG：白底 + 主体 + 洋红刀模线。"""
from PIL import Image, ImageDraw

from app import geometry as g
from app import vectorize as vz
from app import border


def _draw_polyline(draw, pts, fill, width=2):
    if len(pts) >= 2:
        draw.line(pts + [pts[0]], fill=fill, width=width)


def render_png(parts, offset_mm=None, page_px=None):
    """RGBA 画布：参数化零件按 offset_mm 缓冲渲染白边+主体+刀模；固定零件用既有图层。
    page_px=(宽,高) 指定输出分辨率，默认 A4 (2100×2970)。"""
    if offset_mm is None:
        offset_mm = g.OFFSET_MM
    if page_px is None:
        page_px = (g.A4_WIDTH_PX, g.A4_HEIGHT_PX)
    offset_px = g.mm_to_px(offset_mm)
    canvas = Image.new("RGBA", page_px, (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    for part in parts:
        if part.x < 0 or part.y < 0:
            continue
        s = part.scale

        if part.subject_outline:
            # —— 参数化零件 ——
            poly = border.dieline_polygon(part.subject_outline, offset_px)
            if poly.is_empty:
                continue
            minx, miny, _, _ = poly.bounds
            ring = list(poly.exterior.coords)
            # 白底多边形(填白) + 刀模(描洋红)，以 poly.min 为局部原点对齐主体图
            white_pts = [(part.x + (px - minx) * s, part.y + (py - miny) * s)
                         for (px, py) in ring]
            if len(white_pts) >= 3:
                draw.polygon(white_pts, fill=(255, 255, 255, 255))
            # 贴主体图：主体局部原点(0,0)对应 poly 内主体位置 = (-minx,-miny)
            subj = Image.fromarray(part.subject_image, mode="RGBA")
            if s != 1.0:
                subj = subj.resize((max(1, int(subj.width * s)),
                                    max(1, int(subj.height * s))), Image.LANCZOS)
            sxoff = part.x + (0 - minx) * s
            syoff = part.y + (0 - miny) * s
            canvas.alpha_composite(subj, (int(sxoff), int(syoff)))
            _draw_polyline(draw, white_pts, g.DIECUT_RGB + (255,))
        else:
            # —— 固定零件(切割碎块/旧)：沿用 image_layer + dieline_path ——
            layer = Image.fromarray(part.image_layer, mode="RGBA")
            if s != 1.0:
                layer = layer.resize((max(1, int(part.w * s)),
                                      max(1, int(part.h * s))), Image.LANCZOS)
            canvas.alpha_composite(layer, (int(part.x), int(part.y)))
            src = part.dieline_path
            if src:
                for poly in vz.path_to_polylines(src):
                    pts = [(part.x + px * s, part.y + py * s) for (px, py) in poly]
                    _draw_polyline(draw, pts, g.DIECUT_RGB + (255,))
            else:
                pts = [(part.x + px * s, part.y + py * s) for (px, py) in part.contour]
                _draw_polyline(draw, pts, g.DIECUT_RGB + (255,))

    return canvas


def save_png(parts, out_path, offset_mm=None, page_px=None):
    render_png(parts, offset_mm=offset_mm, page_px=page_px).save(out_path)
