"""旋转感知 Bottom-Left-Fill 紧凑排版：支持中心+角度坐标契约、间距、统一缩放。"""
import math
import shapely.geometry
import shapely.affinity
import shapely.prepared

from app import border, geometry as g

SIMPLIFY_TOLERANCE_PX = 4  # 碰撞多边形简化容差（像素）
# 简化会使多边形内缩最多 tol，两件之间实际间距因此偏小最多 2*tol；
# 碰撞缓冲时每件补回 tol/2*2=tol 的一半（见 _place），保证「间距」设定值基本精确。


def _base_poly(part, offset_px: float, smooth_iters: int = 0):
    """返回零件的碰撞基础多边形（未缩放、未旋转、局部坐标）。
    优先用参数化主体轮廓缓冲；否则用 contour 直接构建。
    smooth_iters/cut_planes 与渲染端一致，保证锚点(bbox 中心)对齐。
    """
    if part.subject_outline:
        poly = border.dieline_polygon(part.subject_outline, offset_px, smooth_iters,
                                       cut_planes=part.cut_planes)
    else:
        poly = shapely.geometry.Polygon(part.contour)

    if poly is None or poly.is_empty:
        # 退化兜底：以图像尺寸构造小矩形
        w = getattr(part, 'w', 50) or 50
        h = getattr(part, 'h', 50) or 50
        poly = shapely.geometry.box(0, 0, w, h)

    return poly.simplify(SIMPLIFY_TOLERANCE_PX, preserve_topology=True)


def _footprint(base_poly, scale: float, angle_deg: float):
    """按 scale 缩放后绕未旋转包围盒中心旋转 angle_deg 度。
    返回 (footprint, anchor)：anchor = 未旋转包围盒中心（旋转不动点）。

    锚点必须与前端/导出一致：fabric group 与导出 tile 均以「未旋转包围盒中心」
    为旋转/摆放锚点。若这里用质心，不对称零件在渲染时会相对碰撞几何整体偏移，
    间距小时可能产生实际重叠。
    """
    p = shapely.affinity.scale(base_poly, scale, scale, origin=(0, 0))
    minx, miny, maxx, maxy = p.bounds
    anchor = ((minx + maxx) / 2.0, (miny + maxy) / 2.0)
    p = shapely.affinity.rotate(p, angle_deg, origin=anchor)
    return p, anchor


def _place(parts, offset_px: float, spacing_px: float, angle_steps: int,
           page_w: int, page_h: int, grid_step: int, progress_cb=None,
           smooth_iters: int = 0):
    """执行一轮 BLF 排版，原地更新每个 part 的 cx/cy/rotation/x/y。
    返回成功放置的零件数量。progress_cb(done, total) 每处理完一个零件回调一次。

    性能要点：board 判定与碰撞预筛全用 AABB 算术(纸框为矩形,bbox 在框内⟺几何在框内),
    仅当候选 AABB 与已放置 AABB 真正相交时才做一次精确 prepared.intersects;
    空白区域的网格点是纯算术,避免百万次多边形运算(原实现 ~27-40s → 数秒)。
    """
    # 按旋转 0° 时的 footprint 面积降序排列，大零件优先
    def _area_key(part):
        return _footprint(_base_poly(part, offset_px, smooth_iters),
                          part.scale, 0)[0].area

    items = sorted(parts, key=_area_key, reverse=True)
    placed = []  # [(prepared_poly, (minx,miny,maxx,maxy))]
    placed_count = 0

    for idx, part in enumerate(items):
        base = _base_poly(part, offset_px, smooth_iters)

        # 候选角度：锁角件只用当前角度；自由件按均匀步数试所有角度
        if part.locked:
            candidate_angles = [part.rotation]
        else:
            n = max(1, angle_steps)
            candidate_angles = [k * 360.0 / n for k in range(n)]

        best = None  # (cy_top, cx_left, fp_buf, dx, dy, angle, cx, cy)

        for angle in candidate_angles:
            fp, anchor = _footprint(base, part.scale, angle)
            fminx, fminy, fmaxx, fmaxy = fp.bounds
            fw = fmaxx - fminx
            fh = fmaxy - fminy
            # 每角度只 buffer 一次；后续靠算术 + 平移
            # +tol/2：补偿 simplify 内缩，使两件实际间距 ≈ spacing 设定值
            fp_buf = fp.buffer(spacing_px / 2.0 + SIMPLIFY_TOLERANCE_PX / 2.0,
                               join_style=2)
            bminx, bminy, bmaxx, bmaxy = fp_buf.bounds

            max_y = max(1, int(page_h - fh) + 1)
            max_x = max(1, int(page_w - fw) + 1)
            found_for_angle = False

            for cy_top in range(0, max_y, grid_step):
                if found_for_angle:
                    break
                # 若本角度的最优只可能比已有 best 更差(cy 更大)，可提前终止
                if best is not None and cy_top >= best[0]:
                    break
                for cx_left in range(0, max_x, grid_step):
                    dx = cx_left - fminx
                    dy = cy_top - fminy
                    cminx = bminx + dx; cminy = bminy + dy
                    cmaxx = bmaxx + dx; cmaxy = bmaxy + dy
                    # 纸框判定(算术)：缓冲后 bbox 须在 [0,page]
                    if cminx < 0 or cminy < 0 or cmaxx > page_w or cmaxy > page_h:
                        continue
                    # AABB 预筛：找出 bbox 真正重叠的已放置件
                    overlappers = [pp for (pp, pb) in placed
                                   if not (cmaxx <= pb[0] or cminx >= pb[2]
                                           or cmaxy <= pb[1] or cminy >= pb[3])]
                    if overlappers:
                        cand = shapely.affinity.translate(fp_buf, dx, dy)
                        if any(pp.intersects(cand) for pp in overlappers):
                            continue
                    # 命中(最靠左上)
                    best = (cy_top, cx_left, fp_buf, dx, dy, angle,
                            anchor[0] + dx, anchor[1] + dy)
                    found_for_angle = True
                    break

        if best is not None:
            cy_top, cx_left, fp_buf, dx, dy, chosen_angle, cen_x, cen_y = best
            cand = shapely.affinity.translate(fp_buf, dx, dy)
            placed.append((shapely.prepared.prep(cand), cand.bounds))
            part.cx = cen_x
            part.cy = cen_y
            part.rotation = chosen_angle
            part.x = int(round(cx_left))
            part.y = int(round(cy_top))
            placed_count += 1
        else:
            part.cx = -1.0
            part.cy = -1.0
            part.x = -1
            part.y = -1

        if progress_cb is not None:
            progress_cb(idx + 1, len(items))

    return placed_count


def nest(parts, offset_mm=None, spacing_mm=None, angle_steps=8,
         uniform_scale=False, grid_step=40, page_px=None, progress_cb=None,
         smooth_iters=0):
    """旋转感知 BLF 排版，原地更新每个 part 的 cx/cy/rotation/scale/x/y。

    参数：
        parts: Part 列表（含 scale/rotation/locked）。
        offset_mm: 白边宽度(mm)，None 用 geometry.OFFSET_MM。
        spacing_mm: 零件间距(mm)，None 用 geometry.PADDING_MM。
        angle_steps: 每个自由件试验的角度数（1=只 0°，4=0/90/180/270，8=45° 步长…）。
        uniform_scale: True 时整体等比缩放以最大化利用率，False 时按各自 scale 排版。
        grid_step: 网格扫描步长（像素）。
        page_px: (page_w, page_h) 元组（像素），None 用 A4。
        progress_cb: 可选 progress_cb(done, total)，每放置/放弃一个零件回调一次
            （uniform_scale 重试时进度会从头重新计）。

    放不下的零件设 cx=cy=x=y=-1，放下的设锚点（未旋转包围盒中心）cx/cy 与包围盒左上 x/y。
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
            max(_footprint(_base_poly(p, offset_px, smooth_iters),
                           p.scale, 0)[0].area, 1.0)
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
                                  page_w, page_h, grid_step, progress_cb=progress_cb,
                                  smooth_iters=smooth_iters)
            if placed_count == len(parts):
                break  # 全部放下
            if attempt < 2:
                # 缩减后重试
                for p in parts:
                    p.scale *= 0.85
    else:
        _place(parts, offset_px, spacing_px, angle_steps, page_w, page_h, grid_step,
               progress_cb=progress_cb, smooth_iters=smooth_iters)

    return parts


def part_polygon(part, offset_mm=None, smooth_iters=0):
    """返回零件在页面坐标中的碰撞多边形（已按 cx/cy/angle/scale 定位）。
    用于测试和可视化。
    """
    if offset_mm is None:
        offset_mm = g.OFFSET_MM
    offset_px = g.mm_to_px(offset_mm)

    base = _base_poly(part, offset_px, smooth_iters)
    fp, anchor = _footprint(base, part.scale, part.rotation)

    # 若零件已放置，将锚点（未旋转包围盒中心）对齐到 (cx, cy)
    if part.cx is not None and part.cx >= 0:
        fp = shapely.affinity.translate(fp, part.cx - anchor[0], part.cy - anchor[1])

    return fp
