"""纯 OpenCV 掩膜处理工具，全部确定性、可单测。"""
import cv2
import numpy as np


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """取最外轮廓重新填实，消除主体内部的镂空（白猫内部白区不会变透明洞）。"""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(mask)
    cv2.drawContours(out, contours, -1, 255, thickness=cv2.FILLED)
    return out


def separate_components(mask: np.ndarray, min_area: int = 200) -> list:
    """连通域分离：每个主体一张同尺寸 0/255 掩膜；过滤面积 < min_area 的噪点。"""
    num_labels, labels = cv2.connectedComponents(mask)
    result = []
    for i in range(1, num_labels):  # 0 是背景
        comp = np.uint8(labels == i) * 255
        if cv2.countNonZero(comp) < min_area:
            continue
        result.append(comp)
    return result


def clean_edges(mask: np.ndarray, ksize: int = 3) -> np.ndarray:
    """形态学开运算（先腐蚀后膨胀）去除毛刺与孤立小点。"""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)


def dilate_mask(mask: np.ndarray, radius_px: int) -> np.ndarray:
    """椭圆核向外膨胀 radius_px，用于生成白边。"""
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * radius_px + 1, 2 * radius_px + 1)
    )
    return cv2.dilate(mask, kernel)
