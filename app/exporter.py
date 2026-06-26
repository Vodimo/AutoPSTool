"""把排好版的零件渲染为单张 A4 PNG：图片层 + 洋红刀模线。"""
from PIL import Image, ImageDraw

from app import geometry as g


def render_png(parts):
    """返回 A4 大小 RGBA 图：白底 + 各零件图片层 + 洋红刀模轮廓。"""
    canvas = Image.new("RGBA", (g.A4_WIDTH_PX, g.A4_HEIGHT_PX), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    for part in parts:
        if part.x < 0 or part.y < 0:
            continue
        # 1) 贴图片层（按 scale 缩放）
        layer = Image.fromarray(part.image_layer, mode="RGBA")
        if part.scale != 1.0:
            new_w = max(1, int(part.w * part.scale))
            new_h = max(1, int(part.h * part.scale))
            layer = layer.resize((new_w, new_h), Image.LANCZOS)
        canvas.alpha_composite(layer, (int(part.x), int(part.y)))

        # 2) 描刀模轮廓（洋红，闭合）
        pts = [(part.x + px * part.scale, part.y + py * part.scale)
               for (px, py) in part.contour]
        if len(pts) >= 2:
            draw.line(pts + [pts[0]], fill=g.DIECUT_RGB + (255,), width=2)

    return canvas


def save_png(parts, out_path):
    render_png(parts).save(out_path)
