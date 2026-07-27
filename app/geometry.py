"""物理常量与单位换算的唯一来源。其它模块一律从这里 import。"""

PIXEL_RATIO = 10                       # 1mm = 10px
A4_WIDTH_MM = 210
A4_HEIGHT_MM = 297
A4_WIDTH_PX = A4_WIDTH_MM * PIXEL_RATIO   # 2100
A4_HEIGHT_PX = A4_HEIGHT_MM * PIXEL_RATIO # 2970

OFFSET_MM = 2.0    # 主体轮廓外扩白边宽度
BLEED_MM = 1.5     # 切割出血：图像越过刀模线继续延伸的量（防裁切偏移露白）
MAX_BLEED_MM = 10.0  # 出血上限：切割时按此量预留素材，之后调出血无需重切
PADDING_MM = 2.0   # 排版零件间安全间距

DIECUT_RGB = (255, 0, 255)  # 刀模线洋红

# 常用纸张预设，单位毫米 (宽, 高)
PAGE_PRESETS = {
    "A4":     (210, 297),
    "A3":     (297, 420),
    "A5":     (148, 210),
    "Letter": (216, 279),
}


def mm_to_px(mm: float) -> int:
    """毫米换算为像素（四舍五入取整）。"""
    return int(round(mm * PIXEL_RATIO))


def px_to_mm(px: float) -> float:
    """像素换算为毫米。"""
    return px / PIXEL_RATIO
