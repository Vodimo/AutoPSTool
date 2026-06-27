"""Bottom-Left-Fill 紧凑排版：按面积降序，网格扫描找左上无碰撞位。"""
import shapely.geometry
import shapely.affinity

from app import geometry as g
from app import border

SIMPLIFY_TOLERANCE_PX = 8  # 排版碰撞用多边形的简化容差(像素)，大幅减顶点提速


def _collision_polygon(part, offset_px):
    """零件在当前白边下的碰撞多边形(按 scale 缩放、简化、未平移)。
    参数化零件按当前 offset 由主体轮廓缓冲出刀模多边形(与画布/导出同一几何)；
    固定零件(切割碎块)用其冻结的 contour。"""
    if getattr(part, "subject_outline", ""):
        poly = border.dieline_polygon(part.subject_outline, offset_px)
        if poly.is_empty:
            poly = shapely.geometry.Polygon([(px, py) for (px, py) in part.contour])
        elif part.scale != 1.0:
            poly = shapely.affinity.scale(poly, xfact=part.scale, yfact=part.scale, origin=(0, 0))
    else:
        pts = [(px * part.scale, py * part.scale) for (px, py) in part.contour]
        poly = shapely.geometry.Polygon(pts)
    return poly.simplify(SIMPLIFY_TOLERANCE_PX, preserve_topology=True)


def part_polygon(part, offset_mm=None):
    """零件碰撞多边形 -> 板坐标多边形。
    与 nest/导出/画布一致：使多边形 bbox 左上角落在 (part.x, part.y)。"""
    offset_px = g.mm_to_px(g.OFFSET_MM if offset_mm is None else offset_mm)
    poly = _collision_polygon(part, offset_px)
    minx, miny, _, _ = poly.bounds
    return shapely.affinity.translate(poly, part.x - minx, part.y - miny)


def nest(parts, offset_mm=None, padding_mm=None, grid_step=20):
    """原地排版，设置每个 part 的 x/y。放不下的标记 x=y=-1。
    offset_mm 为当前全局白边：参数化零件按它计算真实占位(与画布所见一致)。"""
    offset_px = g.mm_to_px(g.OFFSET_MM if offset_mm is None else offset_mm)
    if padding_mm is None:
        padding_mm = g.PADDING_MM
    padding_px = g.mm_to_px(padding_mm)

    board = shapely.geometry.box(0, 0, g.A4_WIDTH_PX, g.A4_HEIGHT_PX)
    # 按缩放后面积降序排列，保证大零件优先放置
    items = sorted(parts,
                   key=lambda p: p.image_layer.shape[0] * p.image_layer.shape[1] * p.scale * p.scale,
                   reverse=True)
    placed = []

    for part in items:
        local = _collision_polygon(part, offset_px)
        minx, miny, maxx, maxy = local.bounds
        pw, ph = maxx - minx, maxy - miny
        best_x, best_y = -1, -1
        found = False

        for y in range(0, max(1, int(g.A4_HEIGHT_PX - ph)), grid_step):
            if found:
                break
            for x in range(0, max(1, int(g.A4_WIDTH_PX - pw)), grid_step):
                # 平移使刀模多边形 bbox 左上角落在 (x, y)，与画布 Group 原点/导出贴图位置对齐
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
