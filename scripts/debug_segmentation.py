"""调试视图：对一张图跑抠图，把每个主体 mask 叠色输出，供肉眼验收。
用法: .conda\\python.exe scripts\\debug_segmentation.py tests\\fixtures\\cats_11.png
"""
import os
import sys
import cv2
import numpy as np
from app import segmentation as seg

COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
          (255, 0, 255), (0, 255, 255), (128, 0, 255), (255, 128, 0)]


def main(path):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        sys.exit(f"无法读取图像: {path}")
    parts = seg.segment_subjects(img)
    overlay = img.copy()
    for i, p in enumerate(parts):
        color = COLORS[i % len(COLORS)]
        overlay[p['mask'] > 0] = (
            0.5 * np.array(color) + 0.5 * overlay[p['mask'] > 0]
        ).astype(np.uint8)
        x, y, w, h = p['bbox']
        cv2.rectangle(overlay, (x, y), (x + w, y + h), color, 2)
    os.makedirs("tests/debug", exist_ok=True)
    out = "tests/debug/seg_overlay.png"
    cv2.imwrite(out, overlay)
    print(f"分离出 {len(parts)} 个主体 -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/cats_11.png")
