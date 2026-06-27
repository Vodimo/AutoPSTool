"""主体矢量轮廓 + 白边宽度 → 刀模多边形/路径（shapely 圆角缓冲）。"""
import shapely.geometry
from shapely.geometry import Polygon, MultiPolygon

from app import vectorize as vz


def dieline_polygon(outline_d: str, offset_px: float) -> Polygon:
    """主体轮廓向外缓冲 offset_px(圆角)，得到白边外缘=刀模多边形。"""
    polylines = vz.path_to_polylines(outline_d)
    if not polylines:
        return Polygon()
    # 取最大环作为主体外轮廓
    rings = [Polygon(pl) for pl in polylines if len(pl) >= 3]
    rings = [r for r in rings if r.is_valid and r.area > 0]
    if not rings:
        return Polygon()
    base = max(rings, key=lambda r: r.area)
    grown = base.buffer(offset_px, join_style=1, cap_style=1)  # round
    if isinstance(grown, MultiPolygon):
        grown = max(grown.geoms, key=lambda g: g.area)
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
