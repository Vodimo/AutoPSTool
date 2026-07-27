"""主体矢量轮廓 + 白边宽度 → 刀模多边形/路径（shapely 圆角缓冲）。"""
import math

from shapely.geometry import Polygon, MultiPolygon
from shapely.affinity import translate as _translate
from shapely.ops import unary_union

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


def _largest_polygon(geom):
    """从任意 shapely 结果中取面积最大的 Polygon；无则 None。"""
    if isinstance(geom, Polygon):
        return geom if not geom.is_empty else None
    if isinstance(geom, MultiPolygon) and len(geom.geoms):
        return max(geom.geoms, key=lambda g: g.area)
    if hasattr(geom, "geoms"):
        polys = [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
        if polys:
            return max(polys, key=lambda g: g.area)
    return None


def clip_with_bleed(poly: Polygon, plane, bleed_px: float) -> Polygon:
    """按切割平面裁剪刀模多边形，出血做成「矩形凸台」。

    出血凸台 = 贴线切平后的块沿越线方向扫掠 bleed_px、再限制在切线~出血线
    之间的带内。这样出血宽度独立于白边宽度（不再被白边"越线只剩 offset"
    饱和），且切口两端是干净的直角——完全锋利。
    """
    p0 = _largest_polygon(poly.intersection(halfplane_polygon(plane, 0.0)))
    if p0 is None:
        return poly
    if bleed_px <= 0:
        return p0
    x1, y1, x2, y2 = plane
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length      # 指向保留侧；越线方向 = -n
    # 沿 -n 扫掠（分步平移并集近似，步长远小于块厚度）
    steps = 3
    sweep = unary_union([p0] + [
        _translate(p0, -nx * bleed_px * k / steps, -ny * bleed_px * k / steps)
        for k in range(1, steps + 1)
    ])
    # 带状区：切线与出血线之间（= 保留侧半平面取反 ∩ 出血半平面）
    band = halfplane_polygon(plane, bleed_px).intersection(
        halfplane_polygon([x2, y2, x1, y1], 0.0))
    bulge = sweep.intersection(band)
    merged = _largest_polygon(unary_union([p0, bulge]))
    return merged if merged is not None else p0


def dieline_polygon(outline_d: str, offset_px: float, smooth_iters: int = 0,
                    cut_planes=None, bleed_px: float = 0.0) -> Polygon:
    """主体轮廓向外缓冲 offset_px(圆角)，得到白边外缘=刀模多边形。
    smooth_iters>0 时：先按档位简化（合并轮廓细碎抖动成长边）再 Chaikin 切角，
    档位越高越顺滑。cut_planes 非空时逐个裁剪：切口平直、出血为矩形凸台
    （见 clip_with_bleed）。先平滑后裁剪，切口直线与直角不被平滑磨圆。"""
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
        # 档位越高简化越强：细碎抖动并成长边，Chaikin 再把长边交角切圆 → 大弧顺滑
        # （容差与前端 rdpSimplify 保持一致）
        simp = grown.simplify(0.8 + 0.6 * smooth_iters, preserve_topology=True)
        if isinstance(simp, Polygon) and not simp.is_empty:
            grown = simp
        sm = smooth_ring(list(grown.exterior.coords)[:-1], smooth_iters)
        cand = Polygon(sm)
        if cand.is_valid and not cand.is_empty:
            grown = cand
    for plane in (cut_planes or []):
        grown = clip_with_bleed(grown, plane, bleed_px)
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
