"""测试公用：生成合成掩膜与图像，避免依赖外部素材即可单测 CV 逻辑。"""
import numpy as np
import cv2
import pytest


def make_blob_mask(size=(400, 400), centers=((200, 200),), radius=80):
    """在黑底上画若干白色实心圆，返回 uint8 (0/255) 掩膜。"""
    h, w = size
    mask = np.zeros((h, w), np.uint8)
    for (cx, cy) in centers:
        cv2.circle(mask, (cx, cy), radius, 255, -1)
    return mask


def make_ring_mask(size=(400, 400), center=(200, 200), outer=120, inner=50):
    """带中心镂空的圆环掩膜，用于测试『填洞』。"""
    h, w = size
    mask = np.zeros((h, w), np.uint8)
    cv2.circle(mask, center, outer, 255, -1)
    cv2.circle(mask, center, inner, 0, -1)
    return mask


def make_white_bg_image(size=(400, 400), centers=((200, 200),), radius=80, color=(0, 140, 200)):
    """白底 + 实心彩色圆的 BGR 图，用于集成测试抠图。"""
    h, w = size
    img = np.full((h, w, 3), 255, np.uint8)
    for (cx, cy) in centers:
        cv2.circle(img, (cx, cy), radius, color, -1)
    return img


@pytest.fixture
def blob_mask():
    return make_blob_mask()
