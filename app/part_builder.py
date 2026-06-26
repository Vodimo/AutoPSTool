"""主体掩膜 → 零件：生成白边、合成图片层、提取刀模轮廓。"""
import uuid
import cv2
import numpy as np

from app import geometry as g
from app import cv_helpers as ch
from app.models import Part


def build_part(image_bgr, subject_mask, offset_mm=None, part_id=None) -> Part:
    """把单个主体掩膜做成零件。subject_mask 为全图坐标 0/255。"""
    if offset_mm is None:
        offset_mm = g.OFFSET_MM
    if part_id is None:
        part_id = uuid.uuid4().hex[:8]

    offset_px = g.mm_to_px(offset_mm)

    # 防越界：先在四周补一圈安全垫
    pad = offset_px + 4
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

    return Part(id=part_id, image_layer=layer, mask=crop_die, contour=contour)


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
    return Part(id=part_id, image_layer=crop_layer, mask=crop_die, contour=contour)


def cut_part(part, p1, p2, bleed_mm=None):
    """沿 p1->p2 把零件切成两块，切口两侧重叠 bleed，切口平直。"""
    if bleed_mm is None:
        bleed_mm = g.BLEED_MM
    bleed_px = g.mm_to_px(bleed_mm)

    h, w = part.mask.shape
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    length = float(np.hypot(dx, dy)) or 1.0

    Y, X = np.indices((h, w))
    # 有向距离：>0 一侧，<0 另一侧
    dist = (dx * (Y - y1) - dy * (X - x1)) / length

    side_a = (dist >= -bleed_px).astype(np.uint8) * 255   # A 含 A 面 + 越界 bleed
    side_b = (dist <= bleed_px).astype(np.uint8) * 255    # B 含 B 面 + 越界 bleed

    die_a = cv2.bitwise_and(part.mask, side_a)
    die_b = cv2.bitwise_and(part.mask, side_b)

    pa = _rebuild_from_die(part.image_layer, die_a, uuid.uuid4().hex[:8])
    pb_ = _rebuild_from_die(part.image_layer, die_b, uuid.uuid4().hex[:8])
    return pa, pb_
