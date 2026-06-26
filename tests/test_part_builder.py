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
