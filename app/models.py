"""贯穿前后端的零件数据模型。"""
from dataclasses import dataclass
import numpy as np


@dataclass
class Part:
    id: str
    image_layer: np.ndarray              # HxWx4 RGBA uint8：白边底+主体，透明背景
    mask: np.ndarray                     # HxW 0/255：膨胀后的刀模掩膜（局部坐标）
    contour: list[tuple[int, int]]       # [(x,y), ...] 刀模轮廓（局部坐标）
    dieline_path: str = ""               # potrace 矢量刀模路径(局部坐标 SVG d)
    subject_image: "np.ndarray | None" = None   # 纯主体 RGBA(透明底,不含白边)
    subject_outline: str = ""                    # 主体掩膜矢量轮廓(主体 bbox 局部坐标)
    source_bgr: "np.ndarray | None" = None      # 主体帧 BGR 原色(未掩膜,与 edit_mask 同帧)
    edit_mask: "np.ndarray | None" = None       # 主体帧 0/255 掩膜(与 subject_image 同帧)
    x: int = 0
    y: int = 0
    scale: float = 1.0
    rotation: float = 0.0
    cx: "float | None" = None
    cy: "float | None" = None

    @property
    def w(self) -> int:
        return self.image_layer.shape[1]

    @property
    def h(self) -> int:
        return self.image_layer.shape[0]
