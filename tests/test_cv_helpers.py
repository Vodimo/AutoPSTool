import cv2
import numpy as np
from app import cv_helpers as ch
from tests.conftest import make_ring_mask, make_blob_mask


def test_fill_holes_removes_interior_hole():
    ring = make_ring_mask()
    filled = ch.fill_holes(ring)
    # 中心点原本是洞(0)，填洞后应为 255
    assert filled[200, 200] == 255


def test_separate_components_counts_blobs():
    mask = make_blob_mask(centers=((100, 100), (300, 300)), radius=50)
    parts = ch.separate_components(mask, min_area=200)
    assert len(parts) == 2
    # 每块只含一个圆
    for p in parts:
        assert p.shape == mask.shape
        assert cv2.countNonZero(p) > 0


def test_separate_components_filters_noise():
    mask = make_blob_mask(centers=((200, 200),), radius=60)
    mask[10, 10] = 255  # 单像素噪点
    parts = ch.separate_components(mask, min_area=200)
    assert len(parts) == 1


def test_dilate_grows_outward():
    mask = make_blob_mask(centers=((200, 200),), radius=50)
    before = cv2.countNonZero(mask)
    after = cv2.countNonZero(ch.dilate_mask(mask, 20))
    assert after > before
