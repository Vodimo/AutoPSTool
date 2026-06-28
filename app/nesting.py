"""旋转感知 Bottom-Left-Fill 紧凑排版：支持中心+角度坐标契约、间距、统一缩放。"""
import math
import shapely.geometry
import shapely.affinity

from app import border, geometry as g

SIMPLIFY_TOLERANCE_PX = 8  # 碰撞多边形简化容差（像素）


def _base_poly(part, offset_px: float):
    """返回零件的碰撞基础多边形（未缩放、未旋转、局部坐标）。
    优先用参数化主体轮廓缓冲；否则用 contour 直接构建。
    """
    if part.subject_outline:
        poly = border.dieline_polygon(part.subject_outline, offset_px)
    else:
        poly = shapely.geometry.Polygon(part.contour)

    if poly is None or poly.is_empty:
        # 退化兜底：以图像尺寸构造小矩形
        w = getattr(part, 'w', 50) or 50
        h = getattr(part, 'h', 50) or 50
        poly = shapely.geometry.box(0, 0, w, h)

    return poly.simplify(SIMPLIFY_TOLERANCE_PX, preserve_topology=True)


def _footprint(base_poly, scale: float, angle_deg: float):
    """按 scale 缩放后绕自身质心旋转 angle_deg 度，返回 footprint 多边形。"""
    p = shapely.affinity.scale(base_poly, scale, scale, origin=(0, 0))
    p = shapely.affinity.rotate(p, angle_deg, origin='centroid')
    return p


def _place(parts, offset_px: float, spacing_px: float, angle_steps: int,
           page_w: int, page_h: int, grid_step: int):
    """执行一轮 BLF 排版，原地更新每个 part 的 cx/cy/rotation/x/y。
    返回成功放置的零件数量。
    """
    board = shapely.geometry.box(0, 0, page_w, page_h)

    # 按旋转 0° 时的 footprint 面积降序排列，大零件优先
    def _area_key(part):
        base = _base_poly(part, offset_px)
        fp = _footprint(base, part.scale, 0)
        return fp.area

    items = sorted(parts, key=_area_key, reverse=True)
    placed = []  # 已放置零件的 buffer 多边形列表（用于碰撞）
    placed_count = 0

    for part in items:
        base = _base_poly(part, offset_px)

        # 候选角度：锁角件只用当前角度；自由件按均匀步数试所有角度
        if part.locked:
            candidate_angles = [part.rotation]
        else:
            n = max(1, angle_steps)
            candidate_angles = [k * 360.0 / n for k in range(n)]

        best = None  # (cy_top, cx_left, angle, cand_poly, center_x, center_y)

        for angle in candidate_angles:
            fp = _footprint(base, part.scale, angle)
            fminx, fminy, fmaxx, fmaxy = fp.bounds
            fw = fmaxx - fminx
            fh = fmaxy - fminy

            # 扫描候选位置（BLF：左上角网格）
            max_y = max(1, int(page_h - fh) + 1)
            max_x = max(1, int(page_w - fw) + 1)
            found_for_angle = False

            for cy_top in range(0, max_y, grid_step):
                if found_for_angle:
                    break
                for cx_left in range(0, max_x, grid_step):
                    # 将 footprint 的 bbox 左上角对齐到 (cx_left, cy_top)
                    cand = shapely.affinity.translate(fp, cx_left - fminx, cy_top - fminy)
                    padded = cand.buffer(spacing_px / 2.0, join_style=2)

                    if not padded.within(board):
                        continue
                    if any(padded.intersects(q) for q in placed):
                        continue

                    # 找到可放位置，比较是否比当前 best 更靠左上
                    if best is None or (cy_top, cx_left) < (best[0], best[1]):
                        c = cand.centroid
                        best = (cy_top, cx_left, angle, padded, c.x, c.y,
                                cand.bounds[0], cand.bounds[1])
                    found_for_angle = True
                    break  # 本角度只取最靠左上的那个位置

        if best is not None:
            _, _, chosen_angle, chosen_padded, cen_x, cen_y, bx, by = best
            placed.append(chosen_padded)
            part.cx = cen_x
            part.cy = cen_y
            part.rotation = chosen_angle
            part.x = int(round(bx))
            part.y = int(round(by))
            placed_count += 1
        else:
            part.cx = -1.0
            part.cy = -1.0
            part.x = -1
            part.y = -1

    return placed_count


def nest(parts, offset_mm=None, spacing_mm=None, angle_steps=8,
         uniform_scale=False, grid_step=20, page_px=None):
    """旋转感知 BLF 排版，原地更新每个 part 的 cx/cy/rotation/scale/x/y。

    参数：
        parts: Part 列表（含 scale/rotation/locked）。
        offset_mm: 白边宽度(mm)，None 用 geometry.OFFSET_MM。
        spacing_mm: 零件间距(mm)，None 用 geometry.PADDING_MM。
        angle_steps: 每个自由件试验的角度数（1=只 0°，4=0/90/180/270，8=45° 步长…）。
        uniform_scale: True 时整体等比缩放以最大化利用率，False 时按各自 scale 排版。
        grid_step: 网格扫描步长（像素）。
        page_px: (page_w, page_h) 元组（像素），None 用 A4。

    放不下的零件设 cx=cy=x=y=-1，放下的设质心 cx/cy 与包围盒左上 x/y。
    """
    if offset_mm is None:
        offset_mm = g.OFFSET_MM
    if spacing_mm is None:
        spacing_mm = g.PADDING_MM
    offset_px = g.mm_to_px(offset_mm)
    spacing_px = g.mm_to_px(spacing_mm)

    if page_px is None:
        page_w, page_h = g.A4_WIDTH_PX, g.A4_HEIGHT_PX
    else:
        page_w, page_h = int(page_px[0]), int(page_px[1])

    if not parts:
        return parts

    if uniform_scale:
        # 估算使总面积约占页面 72% 的全局缩放系数
        total_area = sum(
            max(_footprint(_base_poly(p, offset_px), p.scale, 0).area, 1.0)
            for p in parts
        )
        page_area = page_w * page_h
        s0 = math.sqrt(0.72 * page_area / total_area)
        s0 = max(0.05, min(3.0, s0))  # 夹持到合理范围

        # 记录原始 scale
        orig_scales = {id(p): p.scale for p in parts}

        # 应用全局缩放系数
        for p in parts:
            p.scale = orig_scales[id(p)] * s0

        # 尝试排版，失败则缩减 0.85，最多重试 2 次
        for attempt in range(3):
            placed_count = _place(parts, offset_px, spacing_px, angle_steps,
                                  page_w, page_h, grid_step)
            if placed_count == len(parts):
                break  # 全部放下
            if attempt < 2:
                # 缩减后重试
                for p in parts:
                    p.scale *= 0.85
    else:
        _place(parts, offset_px, spacing_px, angle_steps, page_w, page_h, grid_step)

    return parts


def part_polygon(part, offset_mm=None):
    """返回零件在页面坐标中的碰撞多边形（已按 cx/cy/angle/scale 定位）。
    用于测试和可视化。
    """
    if offset_mm is None:
        offset_mm = g.OFFSET_MM
    offset_px = g.mm_to_px(offset_mm)

    base = _base_poly(part, offset_px)
    fp = _footprint(base, part.scale, part.rotation)

    # 若零件已放置，将质心对齐到 (cx, cy)
    if part.cx is not None and part.cx >= 0:
        cur_cx = fp.centroid.x
        cur_cy = fp.centroid.y
        fp = shapely.affinity.translate(fp, part.cx - cur_cx, part.cy - cur_cy)

    return fp
