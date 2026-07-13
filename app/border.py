"""主体矢量轮廓 + 白边宽度 → 刀模多边形/路径（shapely 圆角缓冲）。"""
import math

from shapely.geometry import Polygon, MultiPolygon

from app import vectorize as vz


_OUTLINE_SIMPLIFY_PX = 1.5  # 外环简化容差：≈1.5px 视觉无损，但点数从数百降到一两百，避免画布卡顿


def outer_polyline(outline_d: str) -> list:
    """主体轮廓的最外环(最大面积)折线点集 [[x,y],...]；忽略内部洞的子路径；空则 []。
    前端与导出共用此唯一来源：只取外环(无洞连线斜杠)、平滑(无端点法粗棱角)、且经简化(点数可控)。"""
    best, best_area = None, 0.0
    for pl in vz.path_to_polylines(outline_d):
        if len(pl) < 3:
            continue
        poly = Polygon(pl)
        if not poly.is_valid or poly.area <= 0:
            continue
        if poly.area > best_area:
            best_area, best = poly.area, poly
    if best is None:
        return []
    s = best.simplify(_OUTLINE_SIMPLIFY_PX, preserve_topology=True)
    if s.is_empty or not hasattr(s, "exterior"):
        s = best
    return [[float(x), float(y)] for (x, y) in s.exterior.coords]


def smooth_ring(pts, iterations: int) -> list:
    """Chaikin 切角平滑：每次迭代把每个顶点替换为相邻边上 1/4、3/4 两点，
    折角越切越圆（收敛于二次 B 样条）。与前端 JS 版算法一致，保证碰撞/渲染同形。

    pts: [(x,y), ...] 闭合环（首尾不重复）。iterations<=0 原样返回。
    """
    ring = [(float(x), float(y)) for x, y in pts]
    for _ in range(max(0, int(iterations))):
        if len(ring) < 3:
            break
        out = []
        n = len(ring)
        for i in range(n):
            x0, y0 = ring[i]
            x1, y1 = ring[(i + 1) % n]
            out.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            out.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        ring = out
    return ring


_PLANE_EXTENT = 1e5   # 半平面矩形的延伸长度(px)，远大于任何零件尺寸即可


def halfplane_polygon(plane, bleed_px: float) -> Polygon:
    """切割半平面 → 大矩形多边形（与刀模求交用）。

    plane=[x1,y1,x2,y2]，保留侧 = dist>0（dist=(dx*(Y-y1)-dy*(X-x1))/L，
    即法线 n=(-dy,dx)/L 指向的一侧）；边界向对侧平移 bleed_px（白边越线出血）。
    """
    x1, y1, x2, y2 = plane
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux            # 指向保留侧的单位法线
    e = _PLANE_EXTENT
    # 边界线 = 切线向非保留侧平移 bleed_px
    bx1, by1 = x1 - nx * bleed_px, y1 - ny * bleed_px
    bx2, by2 = x2 - nx * bleed_px, y2 - ny * bleed_px
    p1 = (bx1 - ux * e, by1 - uy * e)
    p2 = (bx2 + ux * e, by2 + uy * e)
    p3 = (p2[0] + nx * e, p2[1] + ny * e)
    p4 = (p1[0] + nx * e, p1[1] + ny * e)
    return Polygon([p1, p2, p3, p4])


def dieline_polygon(outline_d: str, offset_px: float, smooth_iters: int = 0,
                    cut_planes=None, bleed_px: float = 0.0) -> Polygon:
    """主体轮廓向外缓冲 offset_px(圆角)，得到白边外缘=刀模多边形。
    smooth_iters>0 时对结果外环做 Chaikin 平滑（消除轮廓简化留下的直边折线感）。
    cut_planes 非空时逐个与半平面求交：切口保持平直，白边越线 bleed_px 作出血。
    （先平滑后裁剪，保证切口直线不被平滑磨圆。）"""
    ring = outer_polyline(outline_d)
    if len(ring) < 3:
        return Polygon()
    grown = Polygon(ring).buffer(offset_px, join_style=1, cap_style=1)  # round
    if isinstance(grown, MultiPolygon):
        grown = max(grown.geoms, key=lambda g: g.area)
    # 守卫退化几何（GeometryCollection/LineString 等）返回空多边形
    if not isinstance(grown, Polygon):
        return Polygon()
    if smooth_iters > 0:
        sm = smooth_ring(list(grown.exterior.coords)[:-1], smooth_iters)
        cand = Polygon(sm)
        if cand.is_valid and not cand.is_empty:
            grown = cand
    for plane in (cut_planes or []):
        clipped = grown.intersection(halfplane_polygon(plane, bleed_px))
        if isinstance(clipped, MultiPolygon):
            clipped = max(clipped.geoms, key=lambda g: g.area)
        if isinstance(clipped, Polygon) and not clipped.is_empty:
            grown = clipped
    return grown


def polygon_to_d(poly: Polygon) -> str:
    """多边形外环 → 闭合 SVG path d。"""
    if poly.is_empty:
        return ""
    coords = list(poly.exterior.coords)
    if len(coords) < 3:
        return ""
    head = f"M{coords[0][0]:.2f},{coords[0][1]:.2f}"
    body = "".join(f"L{x:.2f},{y:.2f}" for x, y in coords[1:])
    return head + body + "Z"


def dieline_path_at(outline_d: str, offset_px: float) -> str:
    """主体轮廓 + offset → 闭合刀模路径 d。"""
    return polygon_to_d(dieline_polygon(outline_d, offset_px))
