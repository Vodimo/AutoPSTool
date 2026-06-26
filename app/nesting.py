"""Bottom-Left-Fill 紧凑排版：按面积降序，网格扫描找左上无碰撞位。"""
import shapely.geometry
import shapely.affinity

from app import geometry as g


def part_polygon(part):
    """零件轮廓 -> 板坐标多边形（含 scale 与 x/y 平移）。"""
    pts = [(px * part.scale, py * part.scale) for (px, py) in part.contour]
    poly = shapely.geometry.Polygon(pts)
    return shapely.affinity.translate(poly, part.x, part.y)


def _local_polygon(part):
    """零件在自身局部、已缩放、左上角对齐到 (0,0) 的多边形。"""
    pts = [(px * part.scale, py * part.scale) for (px, py) in part.contour]
    poly = shapely.geometry.Polygon(pts)
    minx, miny, _, _ = poly.bounds
    return shapely.affinity.translate(poly, -minx, -miny)


def nest(parts, padding_mm=None, grid_step=20):
    """原地排版，设置每个 part 的 x/y。放不下的标记 x=y=-1。"""
    if padding_mm is None:
        padding_mm = g.PADDING_MM
    padding_px = g.mm_to_px(padding_mm)

    board = shapely.geometry.box(0, 0, g.A4_WIDTH_PX, g.A4_HEIGHT_PX)
    items = sorted(parts, key=lambda p: p.image_layer.shape[0] * p.image_layer.shape[1],
                   reverse=True)
    placed = []

    for part in items:
        local = _local_polygon(part)
        minx, miny, maxx, maxy = local.bounds
        pw, ph = maxx - minx, maxy - miny
        best_x, best_y = -1, -1
        found = False

        for y in range(0, max(1, int(g.A4_HEIGHT_PX - ph)), grid_step):
            if found:
                break
            for x in range(0, max(1, int(g.A4_WIDTH_PX - pw)), grid_step):
                cand = shapely.affinity.translate(local, x, y)
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
