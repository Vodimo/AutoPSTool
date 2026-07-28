"""把排好版的零件渲染为单张 A4 PNG：白底 + 主体 + 洋红刀模线。

重构为「逐零件 tile → 按角度旋转 → 居中粘贴」，支持 part.rotation 与 part.cx/cy。
"""
import math

from PIL import Image, ImageChops, ImageDraw

from app import geometry as g
from app import vectorize as vz
from app import border


def _draw_polyline(draw, pts, fill, width=2):
    if len(pts) >= 2:
        draw.line(pts + [pts[0]], fill=fill, width=width)


# tile 四周对称留白（px）：刀模描边宽 2px 且居中于轮廓，
# 无留白时贴着包围盒边缘的描边会被裁掉一半
TILE_PAD = 2


def _build_tile(part, offset_px: float,
                smooth_iters: int = 0) -> tuple["Image.Image", float, float]:
    """构建未旋转的 RGBA tile，返回 (tile, content_w, content_h)。

    参数化零件：白多边形 + 主体图 + 洋红刀模线，以 poly 局部坐标为基准。
    固定零件：image_layer 缩放 + 洋红刀模线。
    tile 四周各留 TILE_PAD（对称，故内容中心 = tile 中心，锚点不变）；
    返回 content_w/h 为不含留白的内容宽/高（浮点，供旧契约 x/y 居中计算用）。
    """
    s = part.scale

    if part.subject_outline:
        # —— 参数化零件 ——
        poly = border.dieline_polygon(part.subject_outline, offset_px, smooth_iters,
                                      cut_planes=part.cut_planes)
        if poly.is_empty:
            return Image.new("RGBA", (1, 1), (0, 0, 0, 0)), 1.0, 1.0
        minx, miny, maxx, maxy = poly.bounds
        cw = max(1, math.ceil((maxx - minx) * s))
        ch = max(1, math.ceil((maxy - miny) * s))
        tile = Image.new("RGBA", (cw + 2 * TILE_PAD, ch + 2 * TILE_PAD), (0, 0, 0, 0))
        draw = ImageDraw.Draw(tile)

        # 白底多边形（tile 局部坐标）
        local_pts = [((px - minx) * s + TILE_PAD, (py - miny) * s + TILE_PAD)
                     for (px, py) in poly.exterior.coords]
        if len(local_pts) >= 3:
            draw.polygon(local_pts, fill=(255, 255, 255, 255))

        # 贴主体图：主体局部原点(0,0) 对应 poly 内位置 = (-minx,-miny)
        subj = Image.fromarray(part.subject_image, mode="RGBA")
        if s != 1.0:
            subj = subj.resize(
                (max(1, int(subj.width * s)), max(1, int(subj.height * s))),
                Image.LANCZOS,
            )
        sx_off = int(round((0 - minx) * s)) + TILE_PAD
        sy_off = int(round((0 - miny) * s)) + TILE_PAD
        tile.alpha_composite(subj, (sx_off, sy_off))

        # 切割块：主体图沿切线是像素级截断，可能溢出刀模区，按刀模区裁掉
        if part.cut_planes and len(local_pts) >= 3:
            region = Image.new("L", tile.size, 0)
            ImageDraw.Draw(region).polygon(local_pts, fill=255)
            tile.putalpha(ImageChops.multiply(tile.getchannel("A"), region))

        # 洋红刀模线（切口处 = 切割线本身）
        _draw_polyline(draw, local_pts, g.DIECUT_RGB + (255,))
        return tile, float(cw), float(ch)

    # —— 固定零件 ——
    layer = Image.fromarray(part.image_layer, mode="RGBA")
    if s != 1.0:
        layer = layer.resize(
            (max(1, int(part.w * s)), max(1, int(part.h * s))), Image.LANCZOS
        )
    tile = Image.new("RGBA", (layer.width + 2 * TILE_PAD, layer.height + 2 * TILE_PAD),
                     (0, 0, 0, 0))
    tile.alpha_composite(layer, (TILE_PAD, TILE_PAD))
    draw = ImageDraw.Draw(tile)
    src = part.dieline_path
    if src:
        for poly in vz.path_to_polylines(src):
            pts = [(px * s + TILE_PAD, py * s + TILE_PAD) for (px, py) in poly]
            _draw_polyline(draw, pts, g.DIECUT_RGB + (255,))
    else:
        pts = [(px * s + TILE_PAD, py * s + TILE_PAD) for (px, py) in part.contour]
        _draw_polyline(draw, pts, g.DIECUT_RGB + (255,))

    return tile, float(layer.width), float(layer.height)


def render_png(parts, offset_mm=None, page_px=None, smooth_iters=0):
    """RGBA 画布：每个零件渲染 tile → 按 rotation 旋转 → 居中粘贴。
    page_px=(宽,高) 指定输出分辨率，默认 A4 (2100×2970)。
    part.cx/cy 给定则以其为中心；否则以 (x + tile_w0/2, y + tile_h0/2) 为中心（向后兼容）。
    smooth_iters: 刀模 Chaikin 平滑迭代数（与前端画布一致）。
    """
    if offset_mm is None:
        offset_mm = g.OFFSET_MM
    if page_px is None:
        page_px = (g.A4_WIDTH_PX, g.A4_HEIGHT_PX)
    offset_px = g.mm_to_px(offset_mm)
    canvas = Image.new("RGBA", page_px, (255, 255, 255, 255))

    for part in parts:
        # 跳过未放置零件：新契约 cx<0，旧契约 x/y<0，均表示排版未成功
        if part.cx is not None:
            if part.cx < 0 or part.cy < 0:
                continue
        elif part.x < 0 or part.y < 0:
            continue

        tile, tile_w0, tile_h0 = _build_tile(part, offset_px, smooth_iters)
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


def save_png(parts, out_path, offset_mm=None, page_px=None, smooth_iters=0):
    render_png(parts, offset_mm=offset_mm, page_px=page_px,
               smooth_iters=smooth_iters).save(out_path)
