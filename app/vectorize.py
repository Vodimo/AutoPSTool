"""把 0/255 掩膜用 potrace 描成平滑矢量刀模路径（零件局部像素坐标）。"""
import os
import re
import subprocess
import tempfile

import cv2
import numpy as np
from svgpathtools import parse_path

VENDOR_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vendor", "potrace")
POTRACE_EXE = os.path.join(VENDOR_DIR, "potrace.exe")

_TRANSFORM_RE = re.compile(
    r'transform="translate\(([-\d.]+),([-\d.]+)\)\s*scale\(([-\d.]+),([-\d.]+)\)"')
_PATH_D_RE = re.compile(r'<path[^>]*\sd="([^"]+)"')


def _run_potrace_svg(bmp_path: str) -> str:
    """对位图运行 potrace，返回 SVG 文本。"""
    env = dict(os.environ)
    env["PATH"] = VENDOR_DIR + os.pathsep + env.get("PATH", "")
    with tempfile.TemporaryDirectory() as td:
        svg_path = os.path.join(td, "out.svg")
        subprocess.run([POTRACE_EXE, "-s", "-o", svg_path, bmp_path],
                       env=env, check=True, capture_output=True)
        with open(svg_path, encoding="utf-8") as f:
            return f.read()


def _svg_to_local_d(svg_text: str) -> str:
    """把 potrace SVG(带 translate+scale)的路径折算到零件局部像素坐标，合并为一个 d。"""
    m = _TRANSFORM_RE.search(svg_text)
    tx, ty, sx, sy = (float(g) for g in m.groups()) if m else (0.0, 0.0, 1.0, 1.0)
    out = []
    for d in _PATH_D_RE.findall(svg_text):
        p = parse_path(d).scaled(sx, sy).translated(complex(tx, ty))
        out.append(p.d())
    return " ".join(out)


def trace_mask(mask: np.ndarray) -> str:
    """0/255 掩膜(主体=255) → 平滑矢量路径 d(局部像素坐标)；空掩膜返回 ""。"""
    if cv2.countNonZero(mask) == 0:
        return ""
    with tempfile.TemporaryDirectory() as td:
        bmp = os.path.join(td, "m.bmp")
        # potrace 以黑为前景：取反让主体(255)变黑被描出，否则描的是背景
        cv2.imwrite(bmp, cv2.bitwise_not(mask))
        svg = _run_potrace_svg(bmp)
    return _svg_to_local_d(svg)


def path_to_polylines(d: str, step_px: float = 3.0) -> list:
    """把矢量路径 d 离散成若干闭合折线([(x,y),...])，供栅格绘制/排版碰撞用。"""
    if not d:
        return []
    polylines = []
    for sub in parse_path(d).continuous_subpaths():
        n = max(8, int(sub.length() / step_px))
        pts = [(float(z.real), float(z.imag))
               for z in (sub.point(t) for t in np.linspace(0.0, 1.0, n))]
        polylines.append(pts)
    return polylines
