"""主体掩膜 → 零件：生成白边、合成图片层、提取刀模轮廓。"""
import uuid
import cv2
import numpy as np

from app import geometry as g
from app import cv_helpers as ch
from app import vectorize as vz
from app.models import Part

# 主体帧边距：subject_image / source_bgr / edit_mask 在主体 bbox 外扩此像素
SUBJECT_MARGIN = 60


def build_part(image_bgr, subject_mask, offset_mm=None, part_id=None) -> Part:
    """把单个主体掩膜做成零件。subject_mask 为全图坐标 0/255。"""
    if offset_mm is None:
        offset_mm = g.OFFSET_MM
    if part_id is None:
        part_id = uuid.uuid4().hex[:8]

    offset_px = g.mm_to_px(offset_mm)

    # 防越界：先在四周补一圈安全垫(至少覆盖 SUBJECT_MARGIN)
    pad = max(offset_px + 4, SUBJECT_MARGIN + 4)
    img = cv2.copyMakeBorder(image_bgr, pad, pad, pad, pad,
                             cv2.BORDER_CONSTANT, value=(255, 255, 255))
    msk = cv2.copyMakeBorder(subject_mask, pad, pad, pad, pad,
                             cv2.BORDER_CONSTANT, value=0)

    # 膨胀 = 白边；得到刀模掩膜
    dieline = ch.dilate_mask(msk, offset_px)

    # 裁剪到刀模包围盒
    x, y, w, h = cv2.boundingRect(dieline)
    crop_die = dieline[y:y + h, x:x + w]
    crop_subj = msk[y:y + h, x:x + w]
    crop_img = img[y:y + h, x:x + w]

    # 合成 RGBA：刀模区域填白底，主体区域填原像素
    layer = np.zeros((h, w, 4), np.uint8)
    layer[crop_die > 0] = (255, 255, 255, 255)        # 白边底（含主体范围）
    b, gg, r = cv2.split(crop_img)
    subj = crop_subj > 0
    layer[subj, 0] = r[subj]                           # 注意 RGBA 顺序：R
    layer[subj, 1] = gg[subj]                          # G
    layer[subj, 2] = b[subj]                           # B
    layer[subj, 3] = 255

    # 刀模轮廓（最外轮廓点集，局部坐标）
    contours, _ = cv2.findContours(crop_die, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    contour = []
    if contours:
        biggest = max(contours, key=cv2.contourArea)
        contour = [(int(p[0][0]), int(p[0][1])) for p in biggest]

    dieline_path = vz.trace_mask(crop_die)

    # 额外产出"主体帧(padded bbox)"：source_bgr / edit_mask / subject_image / subject_outline
    # 主体帧 = 主体 bbox 外扩 SUBJECT_MARGIN 并 clamp 到 padded 图边界
    M = SUBJECT_MARGIN
    sx, sy, sw, sh = cv2.boundingRect(msk)
    x0 = max(0, sx - M)
    y0 = max(0, sy - M)
    x1 = min(img.shape[1], sx + sw + M)
    y1 = min(img.shape[0], sy + sh + M)
    source_bgr = img[y0:y1, x0:x1].copy()      # BGR 全色（未掩膜）
    edit_mask  = msk[y0:y1, x0:x1].copy()      # 0/255 掩膜，与 source_bgr 同帧

    # subject_image：同帧 RGBA，主体像素着色，其余透明
    fh, fw = edit_mask.shape
    subject_image = np.zeros((fh, fw, 4), np.uint8)
    sb2, sg2, sr2 = cv2.split(source_bgr)
    sm = edit_mask > 0
    subject_image[sm, 0] = sr2[sm]
    subject_image[sm, 1] = sg2[sm]
    subject_image[sm, 2] = sb2[sm]
    subject_image[sm, 3] = 255
    subject_outline = vz.trace_mask(edit_mask)

    return Part(id=part_id, image_layer=layer, mask=crop_die,
                contour=contour, dieline_path=dieline_path,
                subject_image=subject_image, subject_outline=subject_outline,
                source_bgr=source_bgr, edit_mask=edit_mask,
                frame_ox=x0 - pad, frame_oy=y0 - pad)


def _rebuild_from_die(layer_rgba, die_mask, part_id):
    """由（已切好的）刀模掩膜与图片层重新裁剪成一个 Part。"""
    x, y, w, h = cv2.boundingRect(die_mask)
    if w == 0 or h == 0:
        return None
    crop_layer = layer_rgba[y:y + h, x:x + w].copy()
    crop_die = die_mask[y:y + h, x:x + w].copy()
    # 切口外的像素清零（透明）
    crop_layer[crop_die == 0] = (0, 0, 0, 0)
    contours, _ = cv2.findContours(crop_die, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    contour = []
    if contours:
        biggest = max(contours, key=cv2.contourArea)
        contour = [(int(p[0][0]), int(p[0][1])) for p in biggest]
    dieline_path = vz.trace_mask(crop_die)
    return Part(id=part_id, image_layer=crop_layer, mask=crop_die,
                contour=contour, dieline_path=dieline_path)


def materialize_parametric(part, offset_mm=None):
    """把参数化零件（含 subject_image）实体化为固定零件（image_layer+mask）。
    用于切割前将带白边预览的参数化零件转为可切割的固定零件。
    """
    si = part.subject_image
    bgr = cv2.cvtColor(si[:, :, :3], cv2.COLOR_RGB2BGR)
    mask = (si[:, :, 3] > 0).astype(np.uint8) * 255
    return build_part(bgr, mask, offset_mm=offset_mm, part_id=part.id)


def apply_brush(part, stroke_mask, mode) -> list:
    """把笔迹掩膜应用到零件的 edit_mask 上，返回新零件列表（可能分裂为多块）。

    Args:
        part: 含 source_bgr 与 edit_mask 的参数化零件。
        stroke_mask: 与 edit_mask 同尺寸的 0/255 uint8 掩膜（白=涂抹处）。
        mode: 'add' 或 'erase'。

    Returns:
        [(Part, (frame_dx, frame_dy)), ...]：每个连通分量一个零件；
        frame_dx/dy = 新零件主体帧原点在旧零件主体帧中的坐标（前端据此
        把新零件放回原位使图像内容严格对齐，不跳位）。全擦没返回 []。
    """
    em = part.edit_mask.copy()
    # 二值化笔迹
    _, st = cv2.threshold(stroke_mask, 127, 255, cv2.THRESH_BINARY)
    if mode == "add":
        em = cv2.bitwise_or(em, st)
    else:  # erase
        em = cv2.bitwise_and(em, cv2.bitwise_not(st))

    em = ch.clean_edges(em)
    comps = ch.separate_components(em, min_area=800)
    out = []
    for c in comps:
        # 复用 build_part：source_bgr 帧 + 该连通分量的掩膜，重新推导白边/刀模/参数化
        newp = build_part(part.source_bgr, c)
        fdx, fdy = newp.frame_ox, newp.frame_oy
        # 切割块修补后保留其切割平面（换算到新帧），切口白边不还原
        if part.cut_planes:
            newp.cut_planes = [[px1 - fdx, py1 - fdy, px2 - fdx, py2 - fdy]
                               for (px1, py1, px2, py2) in part.cut_planes]
        out.append((newp, (fdx, fdy)))
    return out


def cut_part_parametric(part, p1, p2) -> list:
    """参数化切割：沿 p1->p2（主体帧坐标）把参数化零件切成若干参数化块。

    主体掩膜沿切线平直截断，切割平面记录在 cut_planes 上；渲染时刀模
    = buffer(outline, offset) ∩ 半平面，故**刀模线正好落在切割线上**，
    切口平直、两端锋利，且白边宽度仍随全局设定实时可调。

    Returns:
        [(Part, (frame_dx, frame_dy)), ...]：每块为新参数化零件，
        cut_planes 已换算/累积到其新主体帧；frame_dx/dy 含义同 apply_brush。
        某侧无有效主体时该侧无块；切线不穿过主体时可能只返回一块。
    """
    em = part.edit_mask
    h, w = em.shape
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    dx, dy = x2 - x1, y2 - y1
    length = float(np.hypot(dx, dy))
    if length < 1.0:
        return [(part, (0, 0))]

    Y, X = np.indices((h, w))
    dist = (dx * (Y - y1) - dy * (X - x1)) / length

    out = []
    # dist>0 侧保留线段方向 (p1→p2)；dist<0 侧取反向 (p2→p1)，使各自保留侧均为 dist>0 约定
    for side_mask, plane in (
        ((dist >= 0), [x1, y1, x2, y2]),
        ((dist <= 0), [x2, y2, x1, y1]),
    ):
        m = cv2.bitwise_and(em, side_mask.astype(np.uint8) * 255)
        comps = ch.separate_components(m, min_area=800)
        for c in comps:
            newp = build_part(part.source_bgr, c)
            fdx, fdy = newp.frame_ox, newp.frame_oy
            # 累积切割平面并换算到新主体帧
            planes = [[px1 - fdx, py1 - fdy, px2 - fdx, py2 - fdy]
                      for (px1, py1, px2, py2) in (part.cut_planes or [])]
            planes.append([plane[0] - fdx, plane[1] - fdy,
                           plane[2] - fdx, plane[3] - fdy])
            newp.cut_planes = planes
            out.append((newp, (fdx, fdy)))
    return out


def cut_part(part, p1, p2):
    """沿 p1->p2 把固定零件切成两块，切口平直。"""
    h, w = part.mask.shape
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    length = float(np.hypot(dx, dy))
    if length < 1.0:
        # 切割线太短（几乎零长）：无法定义切口方向，原样返回不切，避免切出两份重叠整图
        return part, None

    Y, X = np.indices((h, w))
    # 有向距离：>0 一侧，<0 另一侧
    dist = (dx * (Y - y1) - dy * (X - x1)) / length

    side_a = (dist >= 0).astype(np.uint8) * 255
    side_b = (dist <= 0).astype(np.uint8) * 255

    die_a = cv2.bitwise_and(part.mask, side_a)
    die_b = cv2.bitwise_and(part.mask, side_b)

    pa = _rebuild_from_die(part.image_layer, die_a, uuid.uuid4().hex[:8])
    pb_ = _rebuild_from_die(part.image_layer, die_b, uuid.uuid4().hex[:8])
    return pa, pb_
