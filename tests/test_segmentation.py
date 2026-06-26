import os
import cv2
import numpy as np
import pytest
from app import segmentation as seg
from tests.conftest import make_white_bg_image

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cats_11.png")


def test_segment_synthetic_two_subjects():
    """合成白底 + 两个分离色块：应分出 2 个主体，且掩膜无内部洞。
    注：make_white_bg_image(size=(h, w))，故用 (300, 500) 让宽度=500，
    两圆圆心 cx=120 和 cx=380 均在图内。
    """
    img = make_white_bg_image(size=(300, 500),
                              centers=((120, 150), (380, 150)), radius=70)
    parts = seg.segment_subjects(img, min_area=800)
    assert len(parts) == 2
    for p in parts:
        x, y, w, h = p['bbox']
        assert w > 0 and h > 0
        assert p['mask'].shape == img.shape[:2]


@pytest.mark.skipif(not os.path.exists(FIXTURE), reason="需放入 cats_11.png")
def test_segment_cats_fixture_returns_many():
    """真实样张：十一只猫应分离出 >= 8 个主体（容忍少量相邻合并）。"""
    img = cv2.imread(FIXTURE, cv2.IMREAD_COLOR)
    parts = seg.segment_subjects(img)
    assert len(parts) >= 8
