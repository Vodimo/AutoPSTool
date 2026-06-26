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
    x: int = 0
    y: int = 0
    scale: float = 1.0
    rotation: float = 0.0

    @property
    def w(self) -> int:
        return self.image_layer.shape[1]

    @property
    def h(self) -> int:
        return self.image_layer.shape[0]
