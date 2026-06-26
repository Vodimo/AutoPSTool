import numpy as np
import cv2
from app import part_builder as pb
from app.models import Part
from tests.conftest import make_white_bg_image, make_blob_mask


def _single_subject():
    img = make_white_bg_image(size=(400, 400), centers=((200, 200),), radius=60)
    mask = make_blob_mask(size=(400, 400), centers=((200, 200),), radius=60)
    return img, mask


def test_build_part_returns_part_with_rgba_layer():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    assert isinstance(part, Part)
    assert part.image_layer.shape[2] == 4           # RGBA
    assert part.w > 0 and part.h > 0


def test_build_part_white_border_grows_bbox():
    """白边应让零件比原主体外扩约 offset_px。"""
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    # 原主体直径 ~120px，外扩 2mm=20px 两侧 -> 约 160px
    assert part.w >= 150


def test_build_part_background_transparent():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    # 角落像素应透明（alpha=0）
    assert part.image_layer[0, 0, 3] == 0


def test_build_part_contour_nonempty():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    assert len(part.contour) >= 3


def test_cut_part_makes_two_overlapping_parts():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    # 竖直切一刀（从上到下）
    midx = part.w // 2
    a, b = pb.cut_part(part, (midx, 0), (midx, part.h), bleed_mm=1.5)
    # 两块各自有内容
    assert a.image_layer[:, :, 3].max() == 255
    assert b.image_layer[:, :, 3].max() == 255
    # 重叠：两块宽度之和应大于原宽（因为出血重叠）
    assert (a.w + b.w) > part.w


def test_build_part_mask_shape_and_values():
    """part.mask 应与 image_layer 同尺寸，且取值仅为 0/255。"""
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    assert part.mask.shape == (part.h, part.w)
    assert set(np.unique(part.mask)).issubset({0, 255})


def test_cut_part_zero_length_line_no_cut():
    """退化（零长）切割线：原样返回，不切出两份重叠整图。"""
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    midx = part.w // 2
    a, b = pb.cut_part(part, (midx, 10), (midx, 10), bleed_mm=1.5)
    assert a is part        # 原零件原样返回
    assert b is None        # 没有第二块


def test_build_part_has_vector_dieline():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    assert part.dieline_path                 # 非空
    assert "C" in part.dieline_path.upper()  # 平滑贝塞尔
