"""引擎C：rembg AI 抠图出主 mask，OpenCV 精修并分离多主体。"""
import cv2
import numpy as np

from app import cv_helpers as ch

_session = None


def _get_session():
    """惰性初始化 rembg 会话（首次调用才下载/加载模型）。
    使用 u2netp 轻量模型（~4MB），在多主体场景分离效果更佳。
    """
    global _session
    if _session is None:
        from rembg import new_session
        _session = new_session("u2netp")
    return _session


def get_alpha_mask(image_bgr: np.ndarray) -> np.ndarray:
    """用 rembg 抠出前景，返回 0/255 单通道掩膜。"""
    from rembg import remove
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    out = remove(rgb, session=_get_session())  # RGBA
    alpha = out[:, :, 3]
    _, mask = cv2.threshold(alpha, 127, 255, cv2.THRESH_BINARY)
    return mask


def segment_subjects(image_bgr: np.ndarray, min_area: int = 800) -> list:
    """抠图 + 精修 + 多主体分离。返回 [{'mask','bbox'}, ...]。"""
    mask = get_alpha_mask(image_bgr)
    mask = ch.clean_edges(mask, ksize=3)             # 去毛刺
    components = ch.separate_components(mask, min_area=min_area)

    parts = []
    for comp in components:
        solid = ch.fill_holes(comp)                  # 内部白区不变透明洞
        x, y, w, h = cv2.boundingRect(solid)
        parts.append({'mask': solid, 'bbox': (x, y, w, h)})
    return parts
