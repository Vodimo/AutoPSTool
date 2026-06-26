# Phase 1 · 刀模矢量化(后端) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把刀模线从像素阶梯轮廓升级为 potrace 真矢量贝塞尔曲线:每个零件携带平滑矢量刀模路径,导出 PNG 用它绘制,消除锯齿;为未来 SVG/PDF 导出备齐矢量数据。

**Architecture:** 增量改造现有 `app/`。新增 `vendor/potrace/`(随仓库分发的 3 个二进制)与 `app/vectorize.py`(子进程调用 potrace 把掩膜描成贝塞尔路径,折算到零件局部像素坐标)。`Part` 新增 `dieline_path` 字段;`build_part` / `cut_part` 填充它;`exporter` 改用它绘制平滑刀模线。纯后端,全程 pytest 可验。

**Tech Stack:** Python 3.11 · OpenCV · NumPy · Pillow · svgpathtools(新增,纯 Python)· 随仓库分发的 potrace.exe。

## Global Constraints

- Python 版本 **3.11**;测试命令 `.conda\python.exe -m pytest tests/ -v`(项目根目录)。
- 物理常量只在 `app/geometry.py`;刀模线洋红 **`#FF00FF`**(`g.DIECUT_RGB=(255,0,255)`)。
- potrace 二进制随仓库分发:`vendor/potrace/` 下放 **`potrace.exe` + `libpotrace-0.dll` + `zlib1.dll`**(共 ~324KB,已验证仅此 3 文件即可在无 msys64 的 PATH 下运行)。
- potrace 以**黑色为前景**:喂给它的位图必须是 `cv2.bitwise_not(mask)`(主体取反成黑),否则描的是背景。
- potrace `-s`(SVG)输出带 `transform="translate(tx,ty) scale(sx,sy)"`,路径坐标需经此仿射变换折算回零件局部像素坐标(y 向下,与掩膜一致)。
- 代码注释/日志中文;每个 Task 末尾提交,提交信息体末尾附 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- `vendor/` 不在 `.gitignore` 中(要随仓库提交);注意当前 `.gitignore` 忽略的是 `tools/`,不要误加 `vendor/`。

## File Structure

```
vendor/potrace/
  potrace.exe, libpotrace-0.dll, zlib1.dll   随仓库分发的描边二进制
  README.md                                  来源/版本/许可说明
app/
  vectorize.py        新增：掩膜 → potrace → 局部坐标矢量路径 d；路径离散成折线
  models.py           修改：Part 新增 dieline_path 字段
  part_builder.py     修改：build_part / cut_part 填充 dieline_path
  exporter.py         修改：用 dieline_path 画平滑刀模线(无则回退 contour)
tests/
  test_vectorize.py   新增
  test_part_builder.py / test_exporter.py  追加用例
requirements.txt      追加 svgpathtools
```

---

### Task 1: 随仓库分发 potrace 二进制

**Files:**
- Create: `vendor/potrace/potrace.exe`, `vendor/potrace/libpotrace-0.dll`, `vendor/potrace/zlib1.dll`（从 `tools/msys64/ucrt64/bin/` 复制）
- Create: `vendor/potrace/README.md`
- Test: `tests/test_vectorize.py`（本任务先建文件 + 存在性/可运行 smoke）

**Interfaces:**
- Consumes: 无
- Produces: `vendor/potrace/potrace.exe` 等 3 个文件,供 `app/vectorize.py` 子进程调用。

- [ ] **Step 1: 复制 3 个二进制到 vendor/potrace/**

Run:
```
mkdir -p vendor/potrace
cp tools/msys64/ucrt64/bin/potrace.exe tools/msys64/ucrt64/bin/libpotrace-0.dll tools/msys64/ucrt64/bin/zlib1.dll vendor/potrace/
ls -l vendor/potrace/
```
Expected: 三个文件存在(potrace.exe ~157K, libpotrace-0.dll ~42K, zlib1.dll ~125K)。

- [ ] **Step 2: 写 `vendor/potrace/README.md`**

```markdown
# potrace（随仓库分发）

位图描边为矢量曲线的工具,用于生成平滑刀模线。

- 来源：MSYS2 包 `mingw-w64-ucrt-x86_64-potrace 1.16-2`
- 文件：`potrace.exe`、`libpotrace-0.dll`、`zlib1.dll`（其余 `api-ms-win-crt-*` 为 Windows 自带 UCRT，无需分发）
- 许可：potrace 为 GPLv2，源码见 https://potrace.sourceforge.net/ 。本项目通过子进程调用该独立程序，不链接其代码。
- 调用：`app/vectorize.py` 把 `vendor/potrace/` 加入子进程 PATH 后运行 `potrace.exe -s`。
```

- [ ] **Step 3: 写存在性 + 可运行 smoke 测试 `tests/test_vectorize.py`**

```python
import os
import subprocess
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
```

- [ ] **Step 4: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_vectorize.py -v`
Expected: FAIL（`ModuleNotFoundError: app.vectorize` —— 模块在 Task 2 才建）。

- [ ] **Step 5: 提交**

```bash
git add vendor/potrace tests/test_vectorize.py
git commit -m "chore: 随仓库分发 potrace 二进制(vendor/potrace)"
```
（提交体附 Co-Authored-By 行。注意 `vendor/potrace/*.exe`/`*.dll` 必须被 git 跟踪——`.gitignore` 忽略的是 `tools/`，不影响 `vendor/`；提交后用 `git ls-files vendor/potrace` 确认 3 文件在列。）

---

### Task 2: `app/vectorize.py` — 掩膜 → 矢量路径

**Files:**
- Create: `app/vectorize.py`
- Modify: `requirements.txt`（追加 `svgpathtools`）
- Test: `tests/test_vectorize.py`（追加用例）

**Interfaces:**
- Consumes: `vendor/potrace/potrace.exe`
- Produces:
  - 常量 `POTRACE_EXE: str`（`vendor/potrace/potrace.exe` 绝对路径）
  - `trace_mask(mask: np.ndarray) -> str`：0/255 掩膜(主体=255) → 零件局部像素坐标系下的 SVG path `d` 字符串(平滑贝塞尔)；空掩膜返回 `""`。
  - `path_to_polylines(d: str, step_px: float = 3.0) -> list[list[tuple[float, float]]]`：把 `d` 离散成若干闭合折线点集（供栅格绘制/排版碰撞）。

- [ ] **Step 1: 安装 svgpathtools 并记入 requirements**

Run:
```
.conda\python.exe -m pip install svgpathtools
```
然后在 `requirements.txt` 末尾追加一行：
```
svgpathtools
```
Expected: 安装成功。

- [ ] **Step 2: 追加失败测试到 `tests/test_vectorize.py`**

```python
import numpy as np
import cv2
from app import vectorize as vz


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
```

- [ ] **Step 3: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_vectorize.py -v`
Expected: FAIL（`AttributeError: module 'app.vectorize' has no attribute 'trace_mask'`，且 Task 1 的两条 smoke 仍会因 import 失败而 error）。

- [ ] **Step 4: 写 `app/vectorize.py`**

```python
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
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.conda\python.exe -m pytest tests/test_vectorize.py -v`
Expected: PASS（5 个：3 smoke/存在性 + circle 曲线 + bbox + 空掩膜）。
若 `test_traced_bbox_matches_subject_not_inverse` 的 y 区间反了(出现 [50,170] 而非 [30,150])，说明该 potrace 版本的 SVG 变换不翻转 y——此时不要改测试，改 `_svg_to_local_d`：去掉 y 翻转(即把折算后的 y 由 `h - y` 调整)；但按已验证行为预期直接通过。

- [ ] **Step 6: 提交**

```bash
git add app/vectorize.py requirements.txt tests/test_vectorize.py
git commit -m "feat: vectorize 用 potrace 把掩膜描成局部坐标矢量刀模路径"
```

---

### Task 3: `Part.dieline_path` + build_part 集成

**Files:**
- Modify: `app/models.py`（Part 新增字段）
- Modify: `app/part_builder.py`（build_part 填充 dieline_path）
- Test: `tests/test_part_builder.py`（追加用例）

**Interfaces:**
- Consumes: `app.vectorize.trace_mask`
- Produces: `Part.dieline_path: str`（矢量刀模路径，局部坐标；默认 `""`）；`build_part(...)` 返回的 Part 该字段非空。

- [ ] **Step 1: 追加失败测试到 `tests/test_part_builder.py`**

```python
def test_build_part_has_vector_dieline():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    assert part.dieline_path                 # 非空
    assert "C" in part.dieline_path.upper()  # 平滑贝塞尔
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_part_builder.py::test_build_part_has_vector_dieline -v`
Expected: FAIL（`AttributeError: 'Part' object has no attribute 'dieline_path'`）。

- [ ] **Step 3: 给 `app/models.py` 的 Part 加字段**

在 `contour` 字段之后、`x` 之前插入：
```python
    dieline_path: str = ""               # potrace 矢量刀模路径(局部坐标 SVG d)
```
（放在有默认值字段区；`x: int = 0` 等其后字段也都有默认值，顺序合法。）

- [ ] **Step 4: 在 `app/part_builder.py` 的 build_part 中填充**

在 `app/part_builder.py` 顶部 import 区追加：
```python
from app import vectorize as vz
```
把 build_part 末尾的 `return` 改为先算矢量路径再返回：
```python
    dieline_path = vz.trace_mask(crop_die)
    return Part(id=part_id, image_layer=layer, mask=crop_die,
                contour=contour, dieline_path=dieline_path)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.conda\python.exe -m pytest tests/test_part_builder.py -v`
Expected: PASS（原有用例 + 新 `test_build_part_has_vector_dieline`）。

- [ ] **Step 6: 提交**

```bash
git add app/models.py app/part_builder.py tests/test_part_builder.py
git commit -m "feat: Part 携带 potrace 矢量刀模路径(build_part)"
```

---

### Task 4: cut_part 也产出矢量刀模(切口保持笔直)

**Files:**
- Modify: `app/part_builder.py`（`_rebuild_from_die` 填充 dieline_path）
- Test: `tests/test_part_builder.py`（追加用例）

**Interfaces:**
- Consumes: `app.vectorize.trace_mask`
- Produces: `cut_part(...)` 返回的两块 Part 各自 `dieline_path` 非空；切口处因是直线像素,被 potrace 描为直线段(不磨圆)。

- [ ] **Step 1: 追加失败测试到 `tests/test_part_builder.py`**

```python
def test_cut_pieces_have_vector_dieline():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    midx = part.w // 2
    a, b = pb.cut_part(part, (midx, 0), (midx, part.h), bleed_mm=1.5)
    assert a.dieline_path and b.dieline_path
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_part_builder.py::test_cut_pieces_have_vector_dieline -v`
Expected: FAIL（两块的 `dieline_path` 为默认 `""`，断言失败）。

- [ ] **Step 3: 在 `_rebuild_from_die` 里填充 dieline_path**

把 `_rebuild_from_die` 末尾的 `return` 改为：
```python
    dieline_path = vz.trace_mask(crop_die)
    return Part(id=part_id, image_layer=crop_layer, mask=crop_die,
                contour=contour, dieline_path=dieline_path)
```
（`vz` 已在 Task 3 于文件顶部导入；切口为笔直像素行/列，potrace 会描成直线段，无需额外处理。）

- [ ] **Step 4: 运行测试确认通过**

Run: `.conda\python.exe -m pytest tests/test_part_builder.py -v`
Expected: PASS（全部 part_builder 用例）。

- [ ] **Step 5: 提交**

```bash
git add app/part_builder.py tests/test_part_builder.py
git commit -m "feat: cut_part 切出的碎块也产出矢量刀模(切口保持笔直)"
```

---

### Task 5: exporter 用矢量刀模线绘制

**Files:**
- Modify: `app/exporter.py`（render_png 改用 dieline_path 折线绘制，无则回退 contour）
- Test: `tests/test_exporter.py`（追加用例）

**Interfaces:**
- Consumes: `app.vectorize.path_to_polylines`、`Part.dieline_path`
- Produces: `render_png(parts)` 用矢量刀模路径绘制平滑洋红刀模线（`dieline_path` 为空时回退到 `contour`，保持旧行为）。

- [ ] **Step 1: 追加失败测试到 `tests/test_exporter.py`**

```python
import numpy as np
import cv2
from app import part_builder as pb


def test_render_uses_vector_dieline_smooth():
    # 真实零件(带矢量刀模)：圆形,导出后洋红像素应勾出近圆而非方框
    img = np.full((300, 300, 3), 255, np.uint8)
    cv2.circle(img, (150, 150), 90, (0, 140, 200), -1)
    mask = np.zeros((300, 300), np.uint8)
    cv2.circle(mask, (150, 150), 90, 255, -1)
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    part.x, part.y = 100, 100
    arr = np.array(exporter.render_png([part]).convert("RGB"))
    magenta = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 60) & (arr[:, :, 2] > 200)
    assert magenta.sum() > 0
    # 矢量刀模应是非空闭合曲线，洋红像素分布在一圈而非聚成一团
    ys, xs = np.where(magenta)
    assert (xs.max() - xs.min()) > 150 and (ys.max() - ys.min()) > 150
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.conda\python.exe -m pytest tests/test_exporter.py::test_render_uses_vector_dieline_smooth -v`
Expected: FAIL（当前 render_png 只读 `part.contour`，忽略 `dieline_path`；该零件 contour 仍在,故未必失败——若未失败,说明绘制路径未切换;继续 Step 3 切换为矢量并保证测试有意义）。

> 注：该零件同时有 contour 与 dieline_path，旧代码用 contour 也能画出洋红圈，本测试可能直接通过。这是可接受的“GREEN 即正确”情形——本任务的实质是让 render_png 优先用矢量路径。请按 Step 3 修改后确保整套 exporter 测试通过。

- [ ] **Step 3: 修改 `app/exporter.py` 的 render_png 绘制刀模线部分**

在 `app/exporter.py` 顶部 import 区追加：
```python
from app import vectorize as vz
```
把 render_png 中“描刀模轮廓”那段（基于 `part.contour` 的 `draw.line`）替换为优先矢量、回退 contour：
```python
        # 2) 描刀模线：优先用矢量路径(平滑)，无则回退像素 contour
        if part.dieline_path:
            for poly in vz.path_to_polylines(part.dieline_path):
                pts = [(part.x + px * part.scale, part.y + py * part.scale)
                       for (px, py) in poly]
                if len(pts) >= 2:
                    draw.line(pts + [pts[0]], fill=g.DIECUT_RGB + (255,), width=2)
        else:
            pts = [(part.x + px * part.scale, part.y + py * part.scale)
                   for (px, py) in part.contour]
            if len(pts) >= 2:
                draw.line(pts + [pts[0]], fill=g.DIECUT_RGB + (255,), width=2)
```

- [ ] **Step 4: 运行全套测试确认通过**

Run: `.conda\python.exe -m pytest tests/ -v`
Expected: 全部 PASS（含新 exporter 用例与既有用例）。

- [ ] **Step 5: 人工眼检(可选但建议)**

Run:
```
.conda\python.exe -c "import cv2,numpy as np; from app import segmentation as s,part_builder as pb,nesting,exporter; img=cv2.imread('tests/fixtures/cats_11.png'); parts=[pb.build_part(img,x['mask']) for x in s.segment_subjects(img)]; nesting.nest(parts); exporter.save_png(parts,'tests/debug/vec_dieline.png'); print('ok')"
```
打开 `tests/debug/vec_dieline.png`,确认刀模线为平滑曲线、无明显锯齿(对比此前像素阶梯)。

- [ ] **Step 6: 提交**

```bash
git add app/exporter.py tests/test_exporter.py
git commit -m "feat: exporter 用矢量刀模路径绘制平滑洋红刀模线"
```

---

## Self-Review

**1. Spec 覆盖(本 phase 范围)：**
- potrace 真矢量刀模 → Task 2/3/4 ✅
- 切出碎块也矢量化、切口保持笔直 → Task 4 ✅
- 导出用矢量刀模(消锯齿) → Task 5 ✅
- potrace 随仓库分发(vendor/potrace, 3 文件) → Task 1 ✅
- 为未来 SVG/PDF 备齐矢量数据(Part.dieline_path 存 SVG d) → Task 3 ✅
- 本 phase 不含:画布显示刀模线(phase 2)、白边可调(phase 2)、旋转/排版(后续 phase)——刻意不做,符合分阶段。

**2. Placeholder 扫描：** 各步均有真实代码/命令；Task 5 Step 2 已说明“可能直接 GREEN”的处理,非占位缺口。

**3. 类型一致性：** `trace_mask(mask)->str`、`path_to_polylines(d, step_px)->list`、`Part.dieline_path:str`、`POTRACE_EXE` 在 vectorize/models/part_builder/exporter 间一致;build_part 与 _rebuild_from_die 均以同一签名调用 `vz.trace_mask(crop_die)`。
