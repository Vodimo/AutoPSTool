"""主体矢量轮廓 + 白边宽度 → 刀模多边形/路径（shapely 圆角缓冲）。"""
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


def dieline_polygon(outline_d: str, offset_px: float) -> Polygon:
    """主体轮廓向外缓冲 offset_px(圆角)，得到白边外缘=刀模多边形。"""
    ring = outer_polyline(outline_d)
    if len(ring) < 3:
        return Polygon()
    grown = Polygon(ring).buffer(offset_px, join_style=1, cap_style=1)  # round
    if isinstance(grown, MultiPolygon):
        grown = max(grown.geoms, key=lambda g: g.area)
    # 守卫退化几何（GeometryCollection/LineString 等）返回空多边形
    if not isinstance(grown, Polygon):
        return Polygon()
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
