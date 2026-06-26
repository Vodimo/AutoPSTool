# 刀模流水线重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 AutoPSTool 重写为一个一键启动、稳定的网页工具：导入白底卡通图 → AI 抠图+CV 精修分离出多个主体 → 每个主体生成白边与刀模轮廓 → 交互式拖/缩/切 → 紧凑排版 → 导出单张含洋红刀模线的 PNG。

**Architecture:** Flask 后端（同时托管前端页面）围绕一个统一的 `Part` 数据模型组织五个独立、可单测的模块（geometry / segmentation / part_builder / nesting / exporter）。后端持有内存中的 `Part` 会话状态，前端 fabric.js 画布通过 part id 引用。抠图用引擎 C：`rembg` 出主 mask + OpenCV 边界精修与连通域分离。

**Tech Stack:** Python 3.11（conda 项目内 `.conda`）、Flask、OpenCV、NumPy、Shapely、Pillow、rembg + onnxruntime、pytest；前端 fabric.js 5.3.1（CDN）。

## Global Constraints

- Python 版本：**3.11**（onnxruntime/rembg 在 3.14 无轮子）。
- 物理比例：**`PIXEL_RATIO = 10`（1mm = 10px）**，A4 = **2100 × 2970 px**。所有常量只在 `app/geometry.py` 定义一次，其它模块 import，禁止重复定义。
- 默认参数：白边 `OFFSET_MM = 2.0`、出血 `BLEED_MM = 1.5`、排版间距 `PADDING_MM = 2.0`。
- 刀模线颜色：洋红 **`#FF00FF`**（RGB `(255, 0, 255)`）。
- 第一版**不做**：SVG/PDF 导出、专色分版、旋转排版、批量队列、撤销历史、potrace 矢量化（v1 用 cv2 轮廓点，输出栅格 PNG）。
- 代码注释与日志用中文，与现有风格一致。
- 测试运行约定：项目根目录下执行 `.conda\python.exe -m pytest tests/ -v`（Windows）。
- 提交粒度：每个 Task 末尾提交一次；提交信息末尾附 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

---

## File Structure

```
AutoPSTool/
  app/
    __init__.py
    geometry.py        物理常量 + mm/px 换算（单一来源）
    models.py          Part 数据模型（dataclass）
    cv_helpers.py      纯 CV 工具：填洞 / 连通域分离 / 去毛刺 / 膨胀
    segmentation.py    引擎C：rembg 出 mask → 精修 → 分离出主体 mask 列表
    part_builder.py    主体 mask → Part（白边 + 刀模轮廓）；切割
    nesting.py         Shapely 紧凑排版
    exporter.py        渲染最终 PNG
    server.py          Flask：托管前端 + API + 内存会话 + 浏览器自启
  web/
    index.html
    app.js
    style.css
  tests/
    __init__.py
    conftest.py        合成 mask/图工具
    fixtures/cats_11.png   主测试样张（用户提供，实施时放入）
    test_geometry.py
    test_cv_helpers.py
    test_segmentation.py
    test_part_builder.py
    test_nesting.py
    test_exporter.py
    test_server.py
    debug/             调试视图输出（gitignore）
  requirements.txt
  start.bat
```

---

### Task 1: 环境与项目骨架

**Files:**
- Create: `requirements.txt`
- Create: `start.bat`
- Create: `app/__init__.py`（空）
- Create: `tests/__init__.py`（空）
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Consumes: 无
- Produces: 可运行的 `.conda`（py3.11）环境与 pytest；`tests/conftest.py` 提供 `make_blob_mask(...)` 合成工具供后续 Task 使用。

- [ ] **Step 1: 创建项目内 conda 环境（py3.11）**

Run（项目根目录）:
```
conda create -p .\.conda python=3.11 -y
```
Expected: `.conda\` 目录生成，`.conda\python.exe --version` 输出 `Python 3.11.x`。

- [ ] **Step 2: 写 `requirements.txt`**

```
flask==3.0.*
opencv-python==4.*
numpy==1.26.*
shapely==2.*
pillow==10.*
rembg==2.0.*
onnxruntime==1.*
pytest==8.*
```
（注：v1 不装 pypotrace/svgpathtools，输出栅格 PNG 用 cv2 轮廓即可，避免 Windows 上 potrace 的编译麻烦。）

- [ ] **Step 3: 安装依赖**

Run:
```
.conda\python.exe -m pip install -r requirements.txt
```
Expected: 全部安装成功（rembg 首次运行时才下载模型，这里不下载）。

- [ ] **Step 4: 写 `app/__init__.py` 与 `tests/__init__.py`（空文件）**

两个文件内容均为空。

- [ ] **Step 5: 写 `tests/conftest.py`（合成测试工具）**

```python
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
```

- [ ] **Step 6: 写 `tests/test_smoke.py`**

```python
def test_imports_ok():
    import numpy, cv2, shapely, flask, PIL  # noqa: F401
    assert True
```

- [ ] **Step 7: 运行冒烟测试**

Run: `.conda\python.exe -m pytest tests/test_smoke.py -v`
Expected: PASS（1 passed）。

- [ ] **Step 8: 写 `start.bat`**

```bat
@echo off
cd /d "%~dp0"
".conda\python.exe" -m app.server
pause
```

- [ ] **Step 9: 提交**

```bash
git add requirements.txt start.bat app/__init__.py tests/__init__.py tests/conftest.py tests/test_smoke.py
git commit -m "chore: 项目骨架与 conda 环境 + pytest 冒烟"
```

---

### Task 2: geometry.py — 物理常量与换算（单一来源）

**Files:**
- Create: `app/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - 常量 `PIXEL_RATIO:int=10`、`A4_WIDTH_PX:int=2100`、`A4_HEIGHT_PX:int=2970`、`OFFSET_MM:float=2.0`、`BLEED_MM:float=1.5`、`PADDING_MM:float=2.0`
  - `mm_to_px(mm: float) -> int`
  - `px_to_mm(px: float) -> float`

- [ ] **Step 1: 写失败测试 `tests/test_geometry.py`**

```python
from app import geometry as g


def test_constants():
    assert g.PIXEL_RATIO == 10
    assert g.A4_WIDTH_PX == 2100
    assert g.A4_HEIGHT_PX == 2970


def test_mm_to_px():
    assert g.mm_to_px(1) == 10
    assert g.mm_to_px(2.0) == 20
    assert isinstance(g.mm_to_px(2.0), int)


def test_px_to_mm():
    assert g.px_to_mm(20) == 2.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_geometry.py -v`
Expected: FAIL（`ModuleNotFoundError: app.geometry` 或属性缺失）。

- [ ] **Step 3: 写 `app/geometry.py`**

```python
"""物理常量与单位换算的唯一来源。其它模块一律从这里 import。"""

PIXEL_RATIO = 10                       # 1mm = 10px
A4_WIDTH_MM = 210
A4_HEIGHT_MM = 297
A4_WIDTH_PX = A4_WIDTH_MM * PIXEL_RATIO   # 2100
A4_HEIGHT_PX = A4_HEIGHT_MM * PIXEL_RATIO # 2970

OFFSET_MM = 2.0    # 主体轮廓外扩白边宽度
BLEED_MM = 1.5     # 切割出血（两块重叠量）
PADDING_MM = 2.0   # 排版零件间安全间距

DIECUT_RGB = (255, 0, 255)  # 刀模线洋红


def mm_to_px(mm: float) -> int:
    """毫米换算为像素（四舍五入取整）。"""
    return int(round(mm * PIXEL_RATIO))


def px_to_mm(px: float) -> float:
    """像素换算为毫米。"""
    return px / PIXEL_RATIO
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.conda\python.exe -m pytest tests/test_geometry.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
git add app/geometry.py tests/test_geometry.py
git commit -m "feat: geometry 物理常量与 mm/px 换算单一来源"
```

---

### Task 3: cv_helpers.py — 纯 CV 工具（填洞 / 分离 / 去毛刺 / 膨胀）

**Files:**
- Create: `app/cv_helpers.py`
- Test: `tests/test_cv_helpers.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `fill_holes(mask: np.ndarray) -> np.ndarray`：取最外轮廓填实，消除内部镂空。
  - `separate_components(mask: np.ndarray, min_area: int = 200) -> list[np.ndarray]`：连通域分离，过滤小噪点，返回每个主体的 0/255 掩膜（与输入同尺寸）。
  - `clean_edges(mask: np.ndarray, ksize: int = 3) -> np.ndarray`：形态学开运算去毛刺。
  - `dilate_mask(mask: np.ndarray, radius_px: int) -> np.ndarray`：椭圆核向外膨胀（生成白边用）。

- [ ] **Step 1: 写失败测试 `tests/test_cv_helpers.py`**

```python
import cv2
import numpy as np
from app import cv_helpers as ch
from tests.conftest import make_ring_mask, make_blob_mask


def test_fill_holes_removes_interior_hole():
    ring = make_ring_mask()
    filled = ch.fill_holes(ring)
    # 中心点原本是洞(0)，填洞后应为 255
    assert filled[200, 200] == 255


def test_separate_components_counts_blobs():
    mask = make_blob_mask(centers=((100, 100), (300, 300)), radius=50)
    parts = ch.separate_components(mask, min_area=200)
    assert len(parts) == 2
    # 每块只含一个圆
    for p in parts:
        assert p.shape == mask.shape
        assert cv2.countNonZero(p) > 0


def test_separate_components_filters_noise():
    mask = make_blob_mask(centers=((200, 200),), radius=60)
    mask[10, 10] = 255  # 单像素噪点
    parts = ch.separate_components(mask, min_area=200)
    assert len(parts) == 1


def test_dilate_grows_outward():
    mask = make_blob_mask(centers=((200, 200),), radius=50)
    before = cv2.countNonZero(mask)
    after = cv2.countNonZero(ch.dilate_mask(mask, 20))
    assert after > before
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_cv_helpers.py -v`
Expected: FAIL（`ModuleNotFoundError: app.cv_helpers`）。

- [ ] **Step 3: 写 `app/cv_helpers.py`**

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.conda\python.exe -m pytest tests/test_cv_helpers.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 提交**

```bash
git add app/cv_helpers.py tests/test_cv_helpers.py
git commit -m "feat: cv_helpers 填洞/连通域分离/去毛刺/膨胀"
```

---

### Task 4: segmentation.py — 引擎C 抠图 + 调试视图（用 cats_11.png 验证）

**Files:**
- Create: `app/segmentation.py`
- Create: `scripts/debug_segmentation.py`
- Test: `tests/test_segmentation.py`
- 放入: `tests/fixtures/cats_11.png`（用户提供的十一只猫图）

**Interfaces:**
- Consumes: `app.cv_helpers`（fill_holes / clean_edges / separate_components）
- Produces:
  - `segment_subjects(image_bgr: np.ndarray, min_area: int = 800) -> list[dict]`
    返回 `[{'mask': np.uint8(HxW 0/255), 'bbox': (x, y, w, h)}, ...]`；`mask` 与输入同尺寸、已去毛刺已填洞、每个主体一项。
  - 内部 `get_alpha_mask(image_bgr) -> np.ndarray`：rembg 出 0/255 前景掩膜。

- [ ] **Step 1: 写测试 `tests/test_segmentation.py`（用合成白底图，先不依赖 rembg 大模型断言数量）**

```python
import os
import cv2
import numpy as np
import pytest
from app import segmentation as seg
from tests.conftest import make_white_bg_image

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cats_11.png")


def test_segment_synthetic_two_subjects():
    """合成白底 + 两个分离色块：应分出 2 个主体，且掩膜无内部洞。"""
    img = make_white_bg_image(size=(500, 300),
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_segmentation.py -v`
Expected: FAIL（`ModuleNotFoundError: app.segmentation`）。

- [ ] **Step 3: 写 `app/segmentation.py`**

```python
"""引擎C：rembg AI 抠图出主 mask，OpenCV 精修并分离多主体。"""
import cv2
import numpy as np

from app import cv_helpers as ch

_session = None


def _get_session():
    """惰性初始化 rembg 会话（首次调用才下载/加载模型）。"""
    global _session
    if _session is None:
        from rembg import new_session
        _session = new_session("u2net")
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
```

- [ ] **Step 4: 运行合成测试确认通过**

Run: `.conda\python.exe -m pytest tests/test_segmentation.py::test_segment_synthetic_two_subjects -v`
Expected: PASS。
（注：首次会触发 rembg 下载约 170MB 模型，需联网，耗时较长属正常。）

- [ ] **Step 5: 写调试视图脚本 `scripts/debug_segmentation.py`**

```python
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
```

- [ ] **Step 6: 人工验收（放入 cats_11.png 后运行调试视图）**

Run: `.conda\python.exe scripts\debug_segmentation.py tests\fixtures\cats_11.png`
Expected: 控制台输出 `分离出 >=8 个主体`；打开 `tests/debug/seg_overlay.png` 肉眼确认：①白猫被正确抠出（不被当背景）；②无内部透明洞；③毛刺边缘干净；④橘/灰/白猫都各自成块。若 cats fixture 测试此时可跑，运行 `.conda\python.exe -m pytest tests/test_segmentation.py -v` 应全 PASS。

- [ ] **Step 7: 提交**

```bash
git add app/segmentation.py scripts/debug_segmentation.py tests/test_segmentation.py tests/fixtures/cats_11.png
git commit -m "feat: segmentation 引擎C(rembg+CV精修) 与调试视图"
```

---

### Task 5: models.py + part_builder.build_part — 主体→零件（白边+刀模轮廓）

**Files:**
- Create: `app/models.py`
- Create: `app/part_builder.py`
- Test: `tests/test_part_builder.py`

**Interfaces:**
- Consumes: `app.geometry`、`app.cv_helpers`
- Produces:
  - `Part` dataclass（`app/models.py`）字段：
    `id:str`、`image_layer:np.ndarray(HxWx4 RGBA uint8)`、`mask:np.ndarray(HxW 0/255)`、`contour:list[tuple[int,int]]`、`x:int=0`、`y:int=0`、`scale:float=1.0`、`rotation:float=0.0`；只读属性 `w`、`h`。
  - `build_part(image_bgr, subject_mask, offset_mm=None, part_id=None) -> Part`
    其中 `subject_mask` 为全图坐标 0/255；返回的 `Part` 已裁剪到包围盒，`image_layer` 为「白边底 + 主体像素、透明背景」，`mask` 为膨胀后的刀模掩膜（局部坐标），`contour` 为该掩膜最外轮廓点集（局部坐标）。

- [ ] **Step 1: 写失败测试 `tests/test_part_builder.py`**

```python
import numpy as np
import cv2
from app import part_builder as pb
from app.models import Part
from tests.conftest import make_white_bg_image, make_blob_mask


def _single_subject():
    img = make_white_bg_image(size=(400, 400), centers=((200, 200),), radius=60)
    mask = make_blob_mask(size=(400, 400), centers=((200, 200),), radius=60)
    return img, mask


def test_build_part_returns_part_with_rgba_layer():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    assert isinstance(part, Part)
    assert part.image_layer.shape[2] == 4           # RGBA
    assert part.w > 0 and part.h > 0


def test_build_part_white_border_grows_bbox():
    """白边应让零件比原主体外扩约 offset_px。"""
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    # 原主体直径 ~120px，外扩 2mm=20px 两侧 -> 约 160px
    assert part.w >= 150


def test_build_part_background_transparent():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    # 角落像素应透明（alpha=0）
    assert part.image_layer[0, 0, 3] == 0


def test_build_part_contour_nonempty():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    assert len(part.contour) >= 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_part_builder.py -v`
Expected: FAIL（`ModuleNotFoundError: app.part_builder`）。

- [ ] **Step 3: 写 `app/models.py`**

```python
"""贯穿前后端的零件数据模型。"""
from dataclasses import dataclass, field
import numpy as np


@dataclass
class Part:
    id: str
    image_layer: np.ndarray              # HxWx4 RGBA uint8：白边底+主体，透明背景
    mask: np.ndarray                     # HxW 0/255：膨胀后的刀模掩膜（局部坐标）
    contour: list                        # [(x,y), ...] 刀模轮廓（局部坐标）
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
```

- [ ] **Step 4: 写 `app/part_builder.py`（仅 build_part；cut_part 在 Task 6 加）**

```python
"""主体掩膜 → 零件：生成白边、合成图片层、提取刀模轮廓。"""
import uuid
import cv2
import numpy as np

from app import geometry as g
from app import cv_helpers as ch
from app.models import Part


def build_part(image_bgr, subject_mask, offset_mm=None, part_id=None) -> Part:
    """把单个主体掩膜做成零件。subject_mask 为全图坐标 0/255。"""
    if offset_mm is None:
        offset_mm = g.OFFSET_MM
    if part_id is None:
        part_id = uuid.uuid4().hex[:8]

    offset_px = g.mm_to_px(offset_mm)

    # 防越界：先在四周补一圈安全垫
    pad = offset_px + 4
    img = cv2.copyMakeBorder(image_bgr, pad, pad, pad, pad,
                             cv2.BORDER_CONSTANT, value=(255, 255, 255))
    msk = cv2.copyMakeBorder(subject_mask, pad, pad, pad, pad,
                             cv2.BORDER_CONSTANT, value=0)

    # 膨胀 = 白边；得到刀模掩膜
    dieline = ch.dilate_mask(msk, offset_px)

    # 裁剪到刀模包围盒
    x, y, w, h = cv2.boundingRect(dieline)
    crop_die = dieline[y:y + h, x:x + w]
    crop_subj = msk[y:y + h, x:x + w]
    crop_img = img[y:y + h, x:x + w]

    # 合成 RGBA：刀模区域填白底，主体区域填原像素
    layer = np.zeros((h, w, 4), np.uint8)
    layer[crop_die > 0] = (255, 255, 255, 255)        # 白边底（含主体范围）
    b, gg, r = cv2.split(crop_img)
    subj = crop_subj > 0
    layer[subj, 0] = r[subj]                           # 注意 RGBA 顺序：R
    layer[subj, 1] = gg[subj]                          # G
    layer[subj, 2] = b[subj]                           # B
    layer[subj, 3] = 255

    # 刀模轮廓（最外轮廓点集，局部坐标）
    contours, _ = cv2.findContours(crop_die, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    contour = []
    if contours:
        biggest = max(contours, key=cv2.contourArea)
        contour = [(int(p[0][0]), int(p[0][1])) for p in biggest]

    return Part(id=part_id, image_layer=layer, mask=crop_die, contour=contour)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.conda\python.exe -m pytest tests/test_part_builder.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 6: 提交**

```bash
git add app/models.py app/part_builder.py tests/test_part_builder.py
git commit -m "feat: Part 模型与 build_part(白边+刀模轮廓)"
```

---

### Task 6: part_builder.cut_part — SDF 出血切割

**Files:**
- Modify: `app/part_builder.py`（新增 `cut_part`）
- Test: `tests/test_part_builder.py`（追加用例）

**Interfaces:**
- Consumes: `app.part_builder.build_part`、`app.geometry`
- Produces:
  - `cut_part(part: Part, p1: tuple[int,int], p2: tuple[int,int], bleed_mm=None) -> tuple[Part, Part]`
    `p1`/`p2` 为切割线两端点（part 局部坐标）。返回两个新 `Part`，两块在切口处**重叠 `bleed_px`**，切口边缘平直。

- [ ] **Step 1: 追加失败测试到 `tests/test_part_builder.py`**

```python
def test_cut_part_makes_two_overlapping_parts():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    # 竖直切一刀（从上到下）
    midx = part.w // 2
    a, b = pb.cut_part(part, (midx, 0), (midx, part.h), bleed_mm=1.5)
    # 两块各自有内容
    assert a.image_layer[:, :, 3].max() == 255
    assert b.image_layer[:, :, 3].max() == 255
    # 重叠：两块宽度之和应大于原宽（因为出血重叠）
    assert (a.w + b.w) > part.w
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_part_builder.py::test_cut_part_makes_two_overlapping_parts -v`
Expected: FAIL（`AttributeError: module has no attribute 'cut_part'`）。

- [ ] **Step 3: 在 `app/part_builder.py` 末尾追加 `cut_part`**

```python
def _rebuild_from_die(layer_rgba, die_mask, part_id):
    """由（已切好的）刀模掩膜与图片层重新裁剪成一个 Part。"""
    x, y, w, h = cv2.boundingRect(die_mask)
    if w == 0 or h == 0:
        return None
    crop_layer = layer_rgba[y:y + h, x:x + w].copy()
    crop_die = die_mask[y:y + h, x:x + w].copy()
    # 切口外的像素清零（透明）
    crop_layer[crop_die == 0] = (0, 0, 0, 0)
    contours, _ = cv2.findContours(crop_die, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    contour = []
    if contours:
        biggest = max(contours, key=cv2.contourArea)
        contour = [(int(p[0][0]), int(p[0][1])) for p in biggest]
    return Part(id=part_id, image_layer=crop_layer, mask=crop_die, contour=contour)


def cut_part(part, p1, p2, bleed_mm=None):
    """沿 p1->p2 把零件切成两块，切口两侧重叠 bleed，切口平直。"""
    if bleed_mm is None:
        bleed_mm = g.BLEED_MM
    bleed_px = g.mm_to_px(bleed_mm)

    h, w = part.mask.shape
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    length = float(np.hypot(dx, dy)) or 1.0

    Y, X = np.indices((h, w))
    # 有向距离：>0 一侧，<0 另一侧
    dist = (dx * (Y - y1) - dy * (X - x1)) / length

    side_a = (dist >= -bleed_px).astype(np.uint8) * 255   # A 含 A 面 + 越界 bleed
    side_b = (dist <= bleed_px).astype(np.uint8) * 255    # B 含 B 面 + 越界 bleed

    die_a = cv2.bitwise_and(part.mask, side_a)
    die_b = cv2.bitwise_and(part.mask, side_b)

    pa = _rebuild_from_die(part.image_layer, die_a, uuid.uuid4().hex[:8])
    pb_ = _rebuild_from_die(part.image_layer, die_b, uuid.uuid4().hex[:8])
    return pa, pb_
```

- [ ] **Step 4: 运行全部 part_builder 测试确认通过**

Run: `.conda\python.exe -m pytest tests/test_part_builder.py -v`
Expected: PASS（5 passed）。

- [ ] **Step 5: 提交**

```bash
git add app/part_builder.py tests/test_part_builder.py
git commit -m "feat: cut_part SDF 出血切割(切口平直,两块重叠)"
```

---

### Task 7: nesting.py — Shapely 紧凑排版

**Files:**
- Create: `app/nesting.py`
- Test: `tests/test_nesting.py`

**Interfaces:**
- Consumes: `app.geometry`、`app.models.Part`、`shapely`
- Produces:
  - `part_polygon(part: Part) -> shapely.geometry.Polygon`：按 `part.scale` 缩放、平移到 `(part.x, part.y)` 后的轮廓多边形（板坐标）。
  - `nest(parts: list[Part], padding_mm=None, grid_step=20) -> list[Part]`：原地设置每个 `part.x/part.y`（Bottom-Left-Fill），返回同一列表；放不下的零件 `x=y=-1` 标记。

- [ ] **Step 1: 写失败测试 `tests/test_nesting.py`**

```python
import numpy as np
from app import nesting
from app.models import Part


def _box_part(pid, size=200):
    """一个边长 size 的实心方块零件（轮廓为方框）。"""
    layer = np.zeros((size, size, 4), np.uint8)
    layer[:, :, 3] = 255
    mask = np.full((size, size), 255, np.uint8)
    contour = [(0, 0), (size - 1, 0), (size - 1, size - 1), (0, size - 1)]
    return Part(id=pid, image_layer=layer, mask=mask, contour=contour)


def test_nest_positions_within_board():
    parts = [_box_part("a"), _box_part("b")]
    out = nesting.nest(parts, padding_mm=2.0)
    from app import geometry as g
    for p in out:
        assert 0 <= p.x and 0 <= p.y
        assert p.x + p.w <= g.A4_WIDTH_PX
        assert p.y + p.h <= g.A4_HEIGHT_PX


def test_nest_no_overlap():
    parts = [_box_part("a"), _box_part("b")]
    out = nesting.nest(parts, padding_mm=2.0)
    pa = nesting.part_polygon(out[0])
    pb = nesting.part_polygon(out[1])
    assert not pa.intersects(pb)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_nesting.py -v`
Expected: FAIL（`ModuleNotFoundError: app.nesting`）。

- [ ] **Step 3: 写 `app/nesting.py`**

```python
"""Bottom-Left-Fill 紧凑排版：按面积降序，网格扫描找左上无碰撞位。"""
import shapely.geometry
import shapely.affinity

from app import geometry as g


def part_polygon(part):
    """零件轮廓 -> 板坐标多边形（含 scale 与 x/y 平移）。"""
    pts = [(px * part.scale, py * part.scale) for (px, py) in part.contour]
    poly = shapely.geometry.Polygon(pts)
    return shapely.affinity.translate(poly, part.x, part.y)


def _local_polygon(part):
    """零件在自身局部、已缩放、左上角对齐到 (0,0) 的多边形。"""
    pts = [(px * part.scale, py * part.scale) for (px, py) in part.contour]
    poly = shapely.geometry.Polygon(pts)
    minx, miny, _, _ = poly.bounds
    return shapely.affinity.translate(poly, -minx, -miny)


def nest(parts, padding_mm=None, grid_step=20):
    """原地排版，设置每个 part 的 x/y。放不下的标记 x=y=-1。"""
    if padding_mm is None:
        padding_mm = g.PADDING_MM
    padding_px = g.mm_to_px(padding_mm)

    board = shapely.geometry.box(0, 0, g.A4_WIDTH_PX, g.A4_HEIGHT_PX)
    items = sorted(parts, key=lambda p: p.image_layer.shape[0] * p.image_layer.shape[1],
                   reverse=True)
    placed = []

    for part in items:
        local = _local_polygon(part)
        minx, miny, maxx, maxy = local.bounds
        pw, ph = maxx - minx, maxy - miny
        best_x, best_y = -1, -1
        found = False

        for y in range(0, max(1, int(g.A4_HEIGHT_PX - ph)), grid_step):
            if found:
                break
            for x in range(0, max(1, int(g.A4_WIDTH_PX - pw)), grid_step):
                cand = shapely.affinity.translate(local, x, y)
                padded = cand.buffer(padding_px / 2.0, join_style=2)
                if not padded.within(board):
                    continue
                if any(padded.intersects(q) for q in placed):
                    continue
                best_x, best_y = x, y
                placed.append(padded)
                found = True
                break

        part.x, part.y = best_x, best_y
    return parts
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.conda\python.exe -m pytest tests/test_nesting.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: 提交**

```bash
git add app/nesting.py tests/test_nesting.py
git commit -m "feat: nesting Bottom-Left-Fill 紧凑排版"
```

---

### Task 8: exporter.py — 渲染单张 PNG

**Files:**
- Create: `app/exporter.py`
- Test: `tests/test_exporter.py`

**Interfaces:**
- Consumes: `app.geometry`、`app.models.Part`、`app.nesting.part_polygon`、Pillow
- Produces:
  - `render_png(parts: list[Part]) -> PIL.Image.Image`：白底 A4 画布；按 `x/y/scale` 贴每个零件图片层；再用洋红 `#FF00FF` 描每个零件刀模轮廓。返回 RGBA PIL 图。
  - `save_png(parts: list[Part], out_path: str) -> None`

- [ ] **Step 1: 写失败测试 `tests/test_exporter.py`**

```python
import numpy as np
from PIL import Image
from app import exporter
from app import geometry as g
from app.models import Part


def _box_part(pid, size=200, x=100, y=100):
    layer = np.zeros((size, size, 4), np.uint8)
    layer[:, :, :3] = 255
    layer[:, :, 3] = 255
    mask = np.full((size, size), 255, np.uint8)
    contour = [(0, 0), (size - 1, 0), (size - 1, size - 1), (0, size - 1)]
    p = Part(id=pid, image_layer=layer, mask=mask, contour=contour)
    p.x, p.y = x, y
    return p


def test_render_size_is_a4():
    img = exporter.render_png([_box_part("a")])
    assert img.size == (g.A4_WIDTH_PX, g.A4_HEIGHT_PX)


def test_render_has_magenta_dieline():
    img = exporter.render_png([_box_part("a")]).convert("RGB")
    arr = np.array(img)
    # 存在洋红像素
    magenta = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 60) & (arr[:, :, 2] > 200)
    assert magenta.sum() > 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_exporter.py -v`
Expected: FAIL（`ModuleNotFoundError: app.exporter`）。

- [ ] **Step 3: 写 `app/exporter.py`**

```python
"""把排好版的零件渲染为单张 A4 PNG：图片层 + 洋红刀模线。"""
from PIL import Image, ImageDraw

from app import geometry as g


def render_png(parts):
    """返回 A4 大小 RGBA 图：白底 + 各零件图片层 + 洋红刀模轮廓。"""
    canvas = Image.new("RGBA", (g.A4_WIDTH_PX, g.A4_HEIGHT_PX), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    for part in parts:
        if part.x < 0 or part.y < 0:
            continue
        # 1) 贴图片层（按 scale 缩放）
        layer = Image.fromarray(part.image_layer, mode="RGBA")
        if part.scale != 1.0:
            new_w = max(1, int(part.w * part.scale))
            new_h = max(1, int(part.h * part.scale))
            layer = layer.resize((new_w, new_h), Image.LANCZOS)
        canvas.alpha_composite(layer, (int(part.x), int(part.y)))

        # 2) 描刀模轮廓（洋红，闭合）
        pts = [(part.x + px * part.scale, part.y + py * part.scale)
               for (px, py) in part.contour]
        if len(pts) >= 2:
            draw.line(pts + [pts[0]], fill=g.DIECUT_RGB + (255,), width=2)

    return canvas


def save_png(parts, out_path):
    render_png(parts).save(out_path)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.conda\python.exe -m pytest tests/test_exporter.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: 提交**

```bash
git add app/exporter.py tests/test_exporter.py
git commit -m "feat: exporter 渲染单张 A4 PNG(图+洋红刀模线)"
```

---

### Task 9: server.py — Flask 托管前端 + API + 内存会话

**Files:**
- Create: `app/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: 全部后端模块（segmentation / part_builder / nesting / exporter）
- Produces（HTTP API，前端依赖）：
  - `GET /` → 返回 `web/index.html`
  - `GET /app.js`、`GET /style.css` → 静态资源
  - `POST /api/segment` body `{image_base64}` → `{parts:[{id,image_base64,w,h}]}`，并把 Part 存入内存 `PARTS`
  - `POST /api/cut` body `{id,x1,y1,x2,y2}`（局部坐标）→ `{parts:[{id,image_base64,w,h},...]}`，替换会话中的该零件
  - `POST /api/nest` body `{items:[{id,scale}]}` → `{positions:[{id,x,y}]}`
  - `POST /api/export` body `{items:[{id,x,y,scale}]}` → `image/png` 附件下载
  - 模块级 `PARTS: dict[str, Part]`、`part_to_dict(part) -> dict`（含 base64 PNG）
  - `main()`：起线程 1 秒后 `webbrowser.open`，再 `app.run(port=5000)`

- [ ] **Step 1: 写失败测试 `tests/test_server.py`**

```python
import base64
import io
import numpy as np
import cv2
from app import server
from app.models import Part


def _png_b64_white_circle():
    img = np.full((300, 300, 3), 255, np.uint8)
    cv2.circle(img, (150, 150), 70, (0, 140, 200), -1)
    ok, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf).decode()


def _fake_part(pid):
    layer = np.zeros((100, 100, 4), np.uint8)
    layer[:, :, 3] = 255
    mask = np.full((100, 100), 255, np.uint8)
    contour = [(0, 0), (99, 0), (99, 99), (0, 99)]
    return Part(id=pid, image_layer=layer, mask=mask, contour=contour)


def setup_function():
    server.PARTS.clear()


def test_index_served():
    client = server.app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200


def test_nest_returns_positions():
    server.PARTS["a"] = _fake_part("a")
    server.PARTS["b"] = _fake_part("b")
    client = server.app.test_client()
    resp = client.post("/api/nest", json={"items": [{"id": "a", "scale": 1.0},
                                                      {"id": "b", "scale": 1.0}]})
    assert resp.status_code == 200
    pos = {p["id"]: p for p in resp.get_json()["positions"]}
    assert pos["a"]["x"] >= 0 and pos["b"]["x"] >= 0


def test_export_returns_png():
    p = _fake_part("a"); p.x, p.y = 50, 50
    server.PARTS["a"] = p
    client = server.app.test_client()
    resp = client.post("/api/export", json={"items": [{"id": "a", "x": 50, "y": 50, "scale": 1.0}]})
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_server.py -v`
Expected: FAIL（`ModuleNotFoundError: app.server`）。

- [ ] **Step 3: 写 `app/server.py`**

```python
"""Flask 后端：托管前端、抠图/切割/排版/导出 API、内存会话、浏览器自启。"""
import os
import io
import base64
import threading
import webbrowser

import cv2
import numpy as np
from flask import Flask, request, jsonify, send_file, send_from_directory

from app import segmentation, part_builder, nesting, exporter
from app.models import Part

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
app = Flask(__name__, static_folder=None)

PARTS = {}  # id -> Part（单用户本地工具，内存会话足够）


def _decode_image(b64: str):
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    data = base64.b64decode(b64)
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # 统一 BGR 3 通道
    return img


def part_to_dict(part: Part) -> dict:
    """零件图片层编码为 base64 PNG 给前端。"""
    rgba = part.image_layer
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    b64 = base64.b64encode(buf).decode()
    return {
        "id": part.id,
        "image_base64": "data:image/png;base64," + b64,
        "w": part.w, "h": part.h,
        "contour": part.contour,
    }


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/<path:fname>")
def static_files(fname):
    return send_from_directory(WEB_DIR, fname)


@app.route("/api/segment", methods=["POST"])
def api_segment():
    img = _decode_image(request.json["image_base64"])
    subjects = segmentation.segment_subjects(img)
    out = []
    for s in subjects:
        part = part_builder.build_part(img, s["mask"])
        PARTS[part.id] = part
        out.append(part_to_dict(part))
    return jsonify({"parts": out})


@app.route("/api/cut", methods=["POST"])
def api_cut():
    d = request.json
    part = PARTS.get(d["id"])
    if part is None:
        return jsonify({"error": "part not found"}), 404
    a, b = part_builder.cut_part(part, (d["x1"], d["y1"]), (d["x2"], d["y2"]))
    del PARTS[d["id"]]
    res = []
    for np_ in (a, b):
        if np_ is None:
            continue
        PARTS[np_.id] = np_
        res.append(part_to_dict(np_))
    return jsonify({"parts": res})


@app.route("/api/nest", methods=["POST"])
def api_nest():
    items = request.json["items"]
    parts = []
    for it in items:
        p = PARTS.get(it["id"])
        if p is None:
            continue
        p.scale = it.get("scale", 1.0)
        parts.append(p)
    nesting.nest(parts)
    return jsonify({"positions": [{"id": p.id, "x": p.x, "y": p.y} for p in parts]})


@app.route("/api/export", methods=["POST"])
def api_export():
    items = request.json["items"]
    parts = []
    for it in items:
        p = PARTS.get(it["id"])
        if p is None:
            continue
        p.x, p.y, p.scale = int(it["x"]), int(it["y"]), it.get("scale", 1.0)
        parts.append(p)
    img = exporter.render_png(parts)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", as_attachment=True,
                     download_name="diecut_layout.png")


def main():
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    print("🚀 AutoPSTool 已启动: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.conda\python.exe -m pytest tests/test_server.py -v`
Expected: PASS（3 passed）。（`test_index_served` 需要 `web/index.html` 存在——若此时尚未建，先在 Step 5 建一个占位 index.html 再跑；或将该用例放到 Task 10 后。建议先建占位文件。）

- [ ] **Step 5: 建占位 `web/index.html`（Task 10 会替换为完整前端）**

```html
<!doctype html><html><head><meta charset="utf-8"><title>AutoPSTool</title></head>
<body><p>占位页，Task 10 替换。</p></body></html>
```

- [ ] **Step 6: 重新运行全部测试确认通过**

Run: `.conda\python.exe -m pytest tests/ -v`
Expected: 全 PASS。

- [ ] **Step 7: 提交**

```bash
git add app/server.py tests/test_server.py web/index.html
git commit -m "feat: server 托管前端+抠图/切割/排版/导出 API+浏览器自启"
```

---

### Task 10: 前端交互画布（fabric.js）

**Files:**
- Modify: `web/index.html`（完整页面）
- Create: `web/app.js`
- Create: `web/style.css`

**Interfaces:**
- Consumes: 后端 API（`/api/segment` `/api/cut` `/api/nest` `/api/export`）
- Produces: 浏览器交互画布。无自动化测试，用末尾**人工验收清单**。

- [ ] **Step 1: 写 `web/style.css`**

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; background: #f1f5f9; color: #1e293b; }
header { display: flex; gap: 12px; align-items: center; padding: 10px 16px;
         background: #fff; border-bottom: 1px solid #e2e8f0; }
header h1 { font-size: 16px; }
button { padding: 6px 12px; border: 1px solid #cbd5e1; border-radius: 6px;
         background: #fff; cursor: pointer; font-size: 13px; }
button:hover { background: #f8fafc; }
button.active { background: #ec4899; color: #fff; border-color: #ec4899; }
#wrap { display: flex; justify-content: center; padding: 16px; }
#status { margin-left: auto; font-size: 12px; color: #64748b; }
canvas { box-shadow: 0 1px 4px rgba(0,0,0,.15); background: #fff; }
```

- [ ] **Step 2: 写 `web/index.html`（完整）**

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AutoPSTool 刀模排版</title>
  <link rel="stylesheet" href="/style.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/fabric.js/5.3.1/fabric.min.js"></script>
</head>
<body>
  <header>
    <h1>AutoPSTool</h1>
    <input type="file" id="file" accept="image/png,image/jpeg" style="display:none">
    <button id="btn-import">导入图片</button>
    <button id="btn-cut">切割模式</button>
    <button id="btn-tidy">整理排版</button>
    <button id="btn-delete">删除选中</button>
    <button id="btn-export">导出 PNG</button>
    <span id="status">就绪</span>
  </header>
  <div id="wrap">
    <canvas id="c" width="630" height="891"></canvas>
  </div>
  <script src="/app.js"></script>
</body>
</html>
```
（画布 630×891 = 2100×2970 的 0.3 缩放显示；内部坐标换算见 app.js 的 `VIEW_SCALE`。）

- [ ] **Step 3: 写 `web/app.js`**

```javascript
// 视图缩放：画布显示 630x891，对应物理 2100x2970 px
const VIEW_SCALE = 0.3;
const canvas = new fabric.Canvas('c', { selection: true, backgroundColor: '#fff' });
const statusEl = document.getElementById('status');
const setStatus = (t) => statusEl.textContent = t;

let cutMode = false;
// part id -> fabric.Image
const objById = new Map();

async function api(path, body) {
  const r = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error(await r.text());
  return r;
}

// 把后端返回的零件加到画布
function addPart(p, x = 20, y = 20) {
  fabric.Image.fromURL(p.image_base64, (img) => {
    img.set({
      left: x, top: y,
      scaleX: VIEW_SCALE, scaleY: VIEW_SCALE,
      partId: p.id, contour: p.contour,
      cornerSize: 8, transparentCorners: false
    });
    objById.set(p.id, img);
    canvas.add(img);
    canvas.requestRenderAll();
  });
}

// 导入图片 -> /api/segment
document.getElementById('btn-import').onclick = () => document.getElementById('file').click();
document.getElementById('file').onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  setStatus('抠图中…');
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const r = await api('/api/segment', { image_base64: reader.result });
      const { parts } = await r.json();
      let i = 0;
      for (const p of parts) { addPart(p, 20 + (i % 5) * 110, 20 + Math.floor(i / 5) * 110); i++; }
      setStatus(`分离出 ${parts.length} 个零件`);
    } catch (err) { setStatus('抠图失败: ' + err.message); }
  };
  reader.readAsDataURL(f);
};

// 切割模式
const cutBtn = document.getElementById('btn-cut');
cutBtn.onclick = () => {
  cutMode = !cutMode;
  cutBtn.classList.toggle('active', cutMode);
  canvas.selection = !cutMode;
  setStatus(cutMode ? '切割模式：在选中零件上拖一条线' : '就绪');
};

// 切割：在选中对象上按下->抬起，取两端点（换算为零件局部像素）
let cutStart = null;
canvas.on('mouse:down', (opt) => {
  if (!cutMode) return;
  const t = canvas.getActiveObject();
  if (!t || !t.partId) { setStatus('请先选中一个零件再切割'); return; }
  cutStart = canvas.getPointer(opt.e);
});
canvas.on('mouse:up', async (opt) => {
  if (!cutMode || !cutStart) return;
  const t = canvas.getActiveObject();
  const end = canvas.getPointer(opt.e);
  cutStart = (() => { const s = cutStart; cutStart = null; return s; })();
  if (!t || !t.partId) return;
  // 画布坐标 -> 零件局部像素坐标
  const toLocal = (pt) => ({
    x: Math.round((pt.x - t.left) / t.scaleX),
    y: Math.round((pt.y - t.top) / t.scaleY)
  });
  const a = toLocal(cutStart), b = toLocal(end);
  setStatus('切割中…');
  try {
    const r = await api('/api/cut', { id: t.partId, x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    const { parts } = await r.json();
    canvas.remove(t); objById.delete(t.partId);
    let i = 0;
    for (const p of parts) { addPart(p, t.left + i * 20, t.top + i * 20); i++; }
    setStatus(`切成 ${parts.length} 块`);
  } catch (err) { setStatus('切割失败: ' + err.message); }
});

// 整理排版 -> /api/nest
document.getElementById('btn-tidy').onclick = async () => {
  const items = [...objById.values()].map(o => ({ id: o.partId, scale: o.scaleX / VIEW_SCALE }));
  if (!items.length) return;
  setStatus('排版中…');
  try {
    const r = await api('/api/nest', { items });
    const { positions } = await r.json();
    for (const pos of positions) {
      const o = objById.get(pos.id);
      if (!o || pos.x < 0) continue;
      o.set({ left: pos.x * VIEW_SCALE, top: pos.y * VIEW_SCALE });
      o.setCoords();
    }
    canvas.requestRenderAll();
    setStatus('排版完成');
  } catch (err) { setStatus('排版失败: ' + err.message); }
};

// 删除选中
document.getElementById('btn-delete').onclick = () => {
  const t = canvas.getActiveObject();
  if (t && t.partId) { objById.delete(t.partId); canvas.remove(t); }
};

// 导出 PNG -> /api/export
document.getElementById('btn-export').onclick = async () => {
  const items = [...objById.values()].map(o => ({
    id: o.partId,
    x: Math.round(o.left / VIEW_SCALE),
    y: Math.round(o.top / VIEW_SCALE),
    scale: o.scaleX / VIEW_SCALE
  }));
  if (!items.length) { setStatus('画布为空'); return; }
  setStatus('导出中…');
  try {
    const r = await api('/api/export', { items });
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'diecut_layout.png'; a.click();
    URL.revokeObjectURL(url);
    setStatus('已导出');
  } catch (err) { setStatus('导出失败: ' + err.message); }
};
```

- [ ] **Step 4: 启动并人工验收**

Run: `.conda\python.exe -m app.server`（或双击 `start.bat`）
Expected: 浏览器自动打开 `http://127.0.0.1:5000`。逐项验收：
1. 「导入图片」选 `cats_11.png` → 画布上散落出 ≥8 个猫零件，每个带白边、透明背景。
2. 拖动任一零件可移动；拖角可缩放（改相对大小）。
3. 点「切割模式」高亮 → 选中一个零件 → 在其上拖一条线 → 该零件变成两块（重叠出血）。
4. 点「整理排版」→ 所有零件紧凑重排、互不重叠、不超出画布。
5. 点「删除选中」可删除当前零件。
6. 点「导出 PNG」→ 下载 `diecut_layout.png`，打开后：白底 A4、各零件白边底、每个零件外圈有洋红 `#FF00FF` 刀模线。

- [ ] **Step 5: 提交**

```bash
git add web/index.html web/app.js web/style.css
git commit -m "feat: 前端交互画布(导入/拖缩/切割/整理/导出)"
```

---

### Task 11: 清理旧实现 + 更新 CLAUDE.md

**Files:**
- Delete: `Gemini/app.py`、`Gemini/core_engine.py`、`Gemini/nesting_packer.py`、`Gemini/index.html`
- Delete: `src/`（Illustrator 实验，v1 不再维护；如想保留则跳过此删除）
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: 无
- Produces: 仓库只剩新 `app/` + `web/` 架构；CLAUDE.md 与现状一致。

- [ ] **Step 1: 确认新流水线全绿**

Run: `.conda\python.exe -m pytest tests/ -v`
Expected: 全 PASS。

- [ ] **Step 2: 删除旧实现**

Run:
```
git rm -r Gemini src
```
（若决定保留 `src/` Illustrator 实验，改为只 `git rm -r Gemini`，并在 CLAUDE.md 注明 src 为独立旧实验。）

- [ ] **Step 3: 重写 `CLAUDE.md` 的「运行」「架构」「依赖」章节**

将 CLAUDE.md 中关于 `Gemini/`、`core_engine.py`、`nesting_packer.py`、坏路由等描述，替换为新架构说明：

```markdown
## 运行

双击 `start.bat`（或 `.conda\python.exe -m app.server`）。它会启动 Flask 并自动打开
`http://127.0.0.1:5000`。前端由 Flask 同源托管，无需单独打开 html。

## 测试

`.conda\python.exe -m pytest tests/ -v`。抠图调试视图：
`.conda\python.exe scripts\debug_segmentation.py tests\fixtures\cats_11.png`。

## 架构（app/）

五个独立可单测模块 + Flask 服务，围绕 `app/models.py:Part` 数据模型：
geometry(常量单一来源) → segmentation(引擎C: rembg+CV精修+连通域分离) →
part_builder(白边/刀模轮廓/SDF出血切割) → nesting(BLF紧凑排版) →
exporter(单张A4 PNG: 图+洋红刀模线)。server.py 托管前端、持有内存 Part 会话、
提供 /api/segment|cut|nest|export。物理常量只在 geometry.py 定义。

## 环境

项目内 conda 环境 `.conda`（Python 3.11）。依赖见 requirements.txt
（关键：rembg + onnxruntime 做 AI 抠图，首次运行下载约 170MB 模型）。
```

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "chore: 删除旧 Gemini/src 实现并更新 CLAUDE.md"
```

---

## Self-Review

**1. Spec coverage（逐条核对）：**
- 环境 conda `.conda`/py3.11/requirements/start.bat → Task 1 ✅
- 常量单一来源 → Task 2 ✅
- 引擎C(rembg+CV精修)+多主体分离+调试视图 → Task 3/4 ✅
- 白边+刀模轮廓 → Task 5 ✅
- SDF 出血切割(切口平直/重叠) → Task 6 ✅
- Shapely 紧凑排版 → Task 7 ✅
- 单张 PNG(图+白边+洋红刀模) → Task 8 ✅
- Flask 托管前端+一键启动+API → Task 9 ✅
- 交互画布(拖/缩/切/整理/导出) → Task 10 ✅
- 图片层/矢量刀模层分离(Part 模型) → Task 5(models) ✅
- 废弃旧坏路由与重复实现 → Task 11 ✅
- 主测试样张 cats_11.png → Task 4 集成测试 + Task 10 人工验收 ✅

**2. Placeholder scan：** 各步骤均含真实代码与命令；占位 `web/index.html`（Task 9 Step 5）在 Task 10 被完整替换，已注明，非计划缺口。

**3. Type consistency：** `Part` 字段（id/image_layer/mask/contour/x/y/scale/rotation/w/h）在 models→part_builder→nesting→exporter→server 全程一致；`segment_subjects` 返回 `{'mask','bbox'}` 与 part_builder 消费一致；`build_part(image_bgr, subject_mask, offset_mm, part_id)`、`cut_part(part,p1,p2,bleed_mm)`、`nest(parts,padding_mm,grid_step)`、`render_png(parts)`、`part_to_dict(part)` 跨任务签名一致。
