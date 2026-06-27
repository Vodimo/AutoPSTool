"""Bottom-Left-Fill 紧凑排版：按面积降序，网格扫描找左上无碰撞位。"""
import shapely.geometry
import shapely.affinity

from app import geometry as g

SIMPLIFY_TOLERANCE_PX = 8  # 排版碰撞用多边形的简化容差(像素)，大幅减顶点提速


def _scaled_polygon(part):
    """零件轮廓按 scale 缩放并简化后的多边形（未平移）。简化大幅减少顶点，加速碰撞计算。"""
    pts = [(px * part.scale, py * part.scale) for (px, py) in part.contour]
    poly = shapely.geometry.Polygon(pts)
    return poly.simplify(SIMPLIFY_TOLERANCE_PX, preserve_topology=True)


def part_polygon(part):
    """零件轮廓 -> 板坐标多边形（含 scale 与 x/y 平移）。"""
    poly = _scaled_polygon(part)
    return shapely.affinity.translate(poly, part.x, part.y)


def nest(parts, padding_mm=None, grid_step=20):
    """原地排版，设置每个 part 的 x/y。放不下的标记 x=y=-1。"""
    if padding_mm is None:
        padding_mm = g.PADDING_MM
    padding_px = g.mm_to_px(padding_mm)

    board = shapely.geometry.box(0, 0, g.A4_WIDTH_PX, g.A4_HEIGHT_PX)
    # Fix 2: 按缩放后面积降序排列，保证大零件优先放置
    items = sorted(parts,
                   key=lambda p: p.image_layer.shape[0] * p.image_layer.shape[1] * p.scale * p.scale,
                   reverse=True)
    placed = []

    for part in items:
        # Fix 1: 使用原始图像帧的多边形（不重新对齐到零点），保持与 image_layer 贴图的一致性
        local = _scaled_polygon(part)
        minx, miny, maxx, maxy = local.bounds
        pw, ph = maxx - minx, maxy - miny
        best_x, best_y = -1, -1
        found = False

        for y in range(0, max(1, int(g.A4_HEIGHT_PX - ph)), grid_step):
            if found:
                break
            for x in range(0, max(1, int(g.A4_WIDTH_PX - pw)), grid_step):
                # Fix 1: 平移使图像原点落在 (x, y)，与 render_png 的贴图位置对齐
                cand = shapely.affinity.translate(local, x - minx, y - miny)
                padded = cand.buffer(padding_px / 2.0, join_style=2)
                if not padded.within(board):
                    continue
                if any(padded.intersects(q) for q in placed):
                    continue
                best_x, best_y = x, y
                placed.append(padded)
                found = True
                break

        part.x, part.y = best_x, best_y
    return parts
