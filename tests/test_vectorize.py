import os
import subprocess
import numpy as np
import cv2
from app import vectorize as vz


def test_vendor_binaries_exist():
    assert os.path.exists(vz.POTRACE_EXE)
    d = os.path.dirname(vz.POTRACE_EXE)
    assert os.path.exists(os.path.join(d, "libpotrace-0.dll"))
    assert os.path.exists(os.path.join(d, "zlib1.dll"))


def test_potrace_runs():
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(vz.POTRACE_EXE) + os.pathsep + env.get("PATH", "")
    r = subprocess.run([vz.POTRACE_EXE, "--version"], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "potrace" in (r.stdout + r.stderr).lower()


def test_trace_circle_returns_curved_path():
    m = np.zeros((200, 200), np.uint8)
    cv2.circle(m, (100, 100), 70, 255, -1)
    d = vz.trace_mask(m)
    assert d
    assert "C" in d.upper()           # 含贝塞尔曲线指令


def test_traced_bbox_matches_subject_not_inverse():
    # 偏心矩形主体；若描成背景(取反错误)，bbox 会是整幅图
    m = np.zeros((200, 300), np.uint8)
    cv2.rectangle(m, (40, 30), (180, 150), 255, -1)
    polys = vz.path_to_polylines(vz.trace_mask(m))
    pts = [p for poly in polys for p in poly]
    xs = [a[0] for a in pts]
    ys = [a[1] for a in pts]
    assert 33 <= min(xs) <= 47 and 173 <= max(xs) <= 187   # x ≈ [40,180]
    assert 23 <= min(ys) <= 37 and 143 <= max(ys) <= 157   # y ≈ [30,150]（y 向下，与掩膜一致）


def test_empty_mask_returns_empty():
    assert vz.trace_mask(np.zeros((50, 50), np.uint8)) == ""
