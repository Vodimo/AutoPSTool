# Phase 2 · 白边参数化 + 画布刀模线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让白边宽度成为全局、实时(纯前端逐帧)、所见即所得的参数，并在画布上实时显示洋红刀模线；导出按当前白边渲染。

**Architecture:** 增量、最小波及。`build_part` 在保留现有烤白边输出(向后兼容 nesting/旧测试)之外，额外产出「纯主体图 + 主体矢量轮廓」。前端用 clipper.js 对主体轮廓实时缓冲 offset，合成「白底+主体+洋红刀模」并随滑块逐帧更新。后端 `exporter` 对带主体轮廓的零件按全局 offset 用 shapely 缓冲渲染。切割沿用现有实现，产出的碎块无主体轮廓=固定零件。

**Tech Stack:** Python 3.11 · OpenCV · NumPy · Shapely · Pillow · svgpathtools · potrace(vendor) · 前端 fabric.js + clipper.js(新增, CDN)。

## Global Constraints

- Python 3.11；测试 `.conda\python.exe -m pytest tests/ -v`（项目根）。
- 物理常量只在 `app/geometry.py`；白边默认 `OFFSET_MM=2.0`；刀模洋红 `g.DIECUT_RGB=(255,0,255)`。
- 单位 mm/px 贯穿白边滑块；内部 `g.mm_to_px`。
- 缓冲一致：后端 shapely `buffer(offset_px, join_style=1, cap_style=1)`(round)；前端 clipper `JT_ROUND`，使白边/刀模两端视觉一致。
- 向后兼容：`build_part` 现有字段(`image_layer`/`mask`/`contour`/`dieline_path`)保持产出，新增 `subject_image`/`subject_outline`；既有测试不得回归。
- 代码注释中文；每 Task 末尾提交，提交体末尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

## File Structure

```
app/
  border.py        新增：主体轮廓 + offset → 刀模多边形 / d（shapely 缓冲）
  models.py        修改：Part 增 subject_image / subject_outline
  part_builder.py  修改：build_part 额外产出主体图+主体轮廓
  exporter.py      修改：render_png(parts, offset_mm) 对参数化零件按 offset 缓冲渲染
  server.py        修改：会话 offset_mm + /api/set_border + part_to_dict 带主体字段
web/
  lib/clipper.js   新增：vendored clipper（或 CDN 引用）
  index.html       修改：引入 clipper + 白边滑块 + 进度条 DOM
  app.js           修改：参数化渲染(白底+主体+刀模) + 白边滑块 + 进度
  style.css        修改：滑块/进度样式
tests/
  test_border.py           新增
  test_part_builder.py     追加
  test_exporter.py         追加
  test_server.py           追加
```

---

### Task 1: `app/border.py` — 缓冲生成刀模多边形

**Files:**
- Create: `app/border.py`
- Test: `tests/test_border.py`

**Interfaces:**
- Consumes: `app.vectorize.path_to_polylines`、`shapely`、`app.geometry`
- Produces:
  - `dieline_polygon(outline_d: str, offset_px: float) -> shapely.geometry.Polygon`：主体轮廓向外缓冲 offset_px(圆角)，返回白边外缘=刀模多边形；空轮廓或退化返回空 Polygon。
  - `polygon_to_d(poly: shapely.geometry.Polygon) -> str`：多边形外环转 SVG path `d`（闭合）。
  - `dieline_path_at(outline_d: str, offset_px: float) -> str`：上面两步合成。

- [ ] **Step 1: 写失败测试 `tests/test_border.py`**

```python
import numpy as np
import cv2
from app import border
from app import vectorize as vz


def _circle_outline_d(r=60, cx=100, cy=100, size=200):
    m = np.zeros((size, size), np.uint8)
    cv2.circle(m, (cx, cy), r, 255, -1)
    return vz.trace_mask(m)


def test_dieline_polygon_grows_with_offset():
    d = _circle_outline_d(r=60)
    p0 = border.dieline_polygon(d, 0.0)
    p20 = border.dieline_polygon(d, 20.0)
    assert p20.area > p0.area
    # 半径约从 60 增到 80：面积比 ~ (80/60)^2 ≈ 1.78
    assert 1.5 < (p20.area / p0.area) < 2.1


def test_dieline_polygon_bbox_expands_by_offset():
    d = _circle_outline_d(r=60, cx=100, cy=100)
    minx, miny, maxx, maxy = border.dieline_polygon(d, 20.0).bounds
    # 圆心 100，半径 60+20=80 → bbox ≈ [20,180]
    assert 12 <= minx <= 28 and 172 <= maxx <= 188


def test_dieline_path_at_is_closed_d():
    d = _circle_outline_d(r=50)
    out = border.dieline_path_at(d, 10.0)
    assert out.startswith("M") and out.strip().endswith("Z")


def test_empty_outline_returns_empty():
    assert border.dieline_polygon("", 10.0).is_empty
    assert border.dieline_path_at("", 10.0) == ""
```

- [ ] **Step 2: 运行确认失败**

Run: `.conda\python.exe -m pytest tests/test_border.py -v`
Expected: FAIL（`ModuleNotFoundError: app.border`）。

- [ ] **Step 3: 写 `app/border.py`**

```python
"""主体矢量轮廓 + 白边宽度 → 刀模多边形/路径（shapely 圆角缓冲）。"""
import shapely.geometry
from shapely.geometry import Polygon, MultiPolygon

from app import vectorize as vz


def dieline_polygon(outline_d: str, offset_px: float) -> Polygon:
    """主体轮廓向外缓冲 offset_px(圆角)，得到白边外缘=刀模多边形。"""
    polylines = vz.path_to_polylines(outline_d)
    if not polylines:
        return Polygon()
    # 取最大环作为主体外轮廓
    rings = [Polygon(pl) for pl in polylines if len(pl) >= 3]
    rings = [r for r in rings if r.is_valid and r.area > 0]
    if not rings:
        return Polygon()
    base = max(rings, key=lambda r: r.area)
    grown = base.buffer(offset_px, join_style=1, cap_style=1)  # round
    if isinstance(grown, MultiPolygon):
        grown = max(grown.geoms, key=lambda g: g.area)
    return grown


def polygon_to_d(poly: Polygon) -> str:
    """多边形外环 → 闭合 SVG path d。"""
    if poly.is_empty:
        return ""
    coords = list(poly.exterior.coords)
    if len(coords) < 3:
        return ""
    head = f"M{coords[0][0]:.2f},{coords[0][1]:.2f}"
    body = "".join(f"L{x:.2f},{y:.2f}" for x, y in coords[1:])
    return head + body + "Z"


def dieline_path_at(outline_d: str, offset_px: float) -> str:
    """主体轮廓 + offset → 闭合刀模路径 d。"""
    return polygon_to_d(dieline_polygon(outline_d, offset_px))
```

- [ ] **Step 4: 运行确认通过**

Run: `.conda\python.exe -m pytest tests/test_border.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 提交**

```bash
git add app/border.py tests/test_border.py
git commit -m "feat: border 用 shapely 缓冲由主体轮廓生成刀模多边形"
```

---

### Task 2: `build_part` 额外产出主体图 + 主体轮廓

**Files:**
- Modify: `app/models.py`
- Modify: `app/part_builder.py`
- Test: `tests/test_part_builder.py`（追加）

**Interfaces:**
- Consumes: `app.vectorize.trace_mask`
- Produces:
  - `Part.subject_image: np.ndarray | None`（HxWx4 RGBA，主体像素+透明底，裁到主体 bbox，**不含白边**；默认 None）
  - `Part.subject_outline: str`（主体掩膜的矢量轮廓 d，主体 bbox 局部坐标；默认 ""）
  - `build_part(...)` 仍返回含 `image_layer`/`mask`/`contour`/`dieline_path` 的零件，**额外**填充 `subject_image`/`subject_outline`。

- [ ] **Step 1: 追加失败测试到 `tests/test_part_builder.py`**

```python
def test_build_part_has_subject_image_and_outline():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    # 主体图：透明底、RGBA、裁到主体(不含白边，应比含白边的 image_layer 小)
    assert part.subject_image is not None
    assert part.subject_image.shape[2] == 4
    assert part.subject_image.shape[0] <= part.image_layer.shape[0]
    assert part.subject_image[0, 0, 3] == 0          # 角落透明
    # 主体轮廓：非空且含曲线
    assert part.subject_outline and "C" in part.subject_outline.upper()
```

- [ ] **Step 2: 运行确认失败**

Run: `.conda\python.exe -m pytest tests/test_part_builder.py::test_build_part_has_subject_image_and_outline -v`
Expected: FAIL（`AttributeError: 'Part' object has no attribute 'subject_image'`）。

- [ ] **Step 3: 给 `app/models.py` 的 Part 加字段**

在 `dieline_path` 之后、`x` 之前插入：
```python
    subject_image: "np.ndarray | None" = None   # 纯主体 RGBA(透明底,不含白边)
    subject_outline: str = ""                    # 主体掩膜矢量轮廓(主体 bbox 局部坐标)
```

- [ ] **Step 4: 在 `app/part_builder.py` 的 build_part 末尾补算主体图/轮廓**

build_part 当前末尾为：
```python
    dieline_path = vz.trace_mask(crop_die)
    return Part(id=part_id, image_layer=layer, mask=crop_die,
                contour=contour, dieline_path=dieline_path)
```
改为在 return 前追加主体图与主体轮廓计算（主体 = 原 `subject_mask` 膨胀前的形态，裁到主体 bbox）：
```python
    dieline_path = vz.trace_mask(crop_die)

    # 额外产出"纯主体图(透明底)"与"主体轮廓"，供前端参数化白边
    sx, sy, sw, sh = cv2.boundingRect(msk)
    subj_mask_crop = msk[sy:sy + sh, sx:sx + sw]
    subj_img_bgr = img[sy:sy + sh, sx:sx + sw]
    subject_image = np.zeros((sh, sw, 4), np.uint8)
    sb, sg, sr = cv2.split(subj_img_bgr)
    sm = subj_mask_crop > 0
    subject_image[sm, 0] = sr[sm]
    subject_image[sm, 1] = sg[sm]
    subject_image[sm, 2] = sb[sm]
    subject_image[sm, 3] = 255
    subject_outline = vz.trace_mask(subj_mask_crop)

    return Part(id=part_id, image_layer=layer, mask=crop_die,
                contour=contour, dieline_path=dieline_path,
                subject_image=subject_image, subject_outline=subject_outline)
```
（`msk` 是 build_part 内已 padding 的主体掩膜；`img` 是已 padding 的原图。主体 bbox 与白边/刀模的局部坐标系同源：都基于 `crop_die` 的裁剪原点 `(x,y)`。注意 `subject_image` 的局部原点是主体 bbox 的 `(sx,sy)`，与 `image_layer` 的原点 `(x,y)` 不同——二者偏移 = `(sx-x, sy-y)`，前端/导出按各自坐标处理，见 Task 3/5。）

- [ ] **Step 5: 运行全部 part_builder 测试确认通过**

Run: `.conda\python.exe -m pytest tests/test_part_builder.py -v`
Expected: PASS（既有用例 + 新用例）。

- [ ] **Step 6: 运行全套确认无回归**

Run: `.conda\python.exe -m pytest tests/ -v`（timeout 300000）
Expected: 全 PASS。

- [ ] **Step 7: 提交**

```bash
git add app/models.py app/part_builder.py tests/test_part_builder.py
git commit -m "feat: build_part 额外产出纯主体图与主体矢量轮廓(白边参数化基础)"
```

---

### Task 3: exporter 按全局白边参数化渲染参数化零件

**Files:**
- Modify: `app/exporter.py`
- Test: `tests/test_exporter.py`（追加）

**Interfaces:**
- Consumes: `app.border.dieline_polygon`、`app.geometry`、`Part.subject_image`/`subject_outline`
- Produces:
  - `render_png(parts, offset_mm: float | None = None) -> PIL.Image`：对**有 `subject_outline` 的零件**，按 `offset_mm`(默认 `g.OFFSET_MM`)用 border 缓冲出刀模多边形→填白底→贴主体图→描洋红刀模；对**无 `subject_outline` 的零件**(切割碎块/手工构造)，沿用既有 `image_layer`+`dieline_path` 路径。
  - `save_png(parts, out_path, offset_mm=None)`

- [ ] **Step 1: 追加失败测试到 `tests/test_exporter.py`**

```python
import numpy as np
import cv2
from app import part_builder as pb


def _para_part(x=100, y=100):
    img = np.full((300, 300, 3), 255, np.uint8)
    cv2.circle(img, (150, 150), 90, (0, 140, 200), -1)
    mask = np.zeros((300, 300), np.uint8)
    cv2.circle(mask, (150, 150), 90, 255, -1)
    p = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    p.x, p.y = x, y
    return p


def test_render_offset_grows_white_and_magenta_extent():
    p = _para_part()
    a = np.array(exporter.render_png([p], offset_mm=2.0).convert("RGB"))
    b = np.array(exporter.render_png([p], offset_mm=6.0).convert("RGB"))

    def magenta_extent(arr):
        m = (arr[:, :, 0] > 200) & (arr[:, :, 1] < 60) & (arr[:, :, 2] > 200)
        ys, xs = np.where(m)
        return (xs.max() - xs.min()) if len(xs) else 0

    ea, eb = magenta_extent(a), magenta_extent(b)
    assert ea > 0 and eb > ea          # 白边越大，刀模外延越大
```

- [ ] **Step 2: 运行确认失败**

Run: `.conda\python.exe -m pytest tests/test_exporter.py::test_render_offset_grows_white_and_magenta_extent -v`
Expected: FAIL（当前 `render_png` 不接受 `offset_mm`，TypeError）。

- [ ] **Step 3: 改写 `app/exporter.py`**

```python
"""把排好版的零件渲染为单张 A4 PNG：白底 + 主体 + 洋红刀模线。"""
from PIL import Image, ImageDraw

from app import geometry as g
from app import vectorize as vz
from app import border


def _draw_polyline(draw, pts, fill, width=2):
    if len(pts) >= 2:
        draw.line(pts + [pts[0]], fill=fill, width=width)


def render_png(parts, offset_mm=None):
    """A4 RGBA：参数化零件按 offset_mm 缓冲渲染白边+主体+刀模；固定零件用既有图层。"""
    if offset_mm is None:
        offset_mm = g.OFFSET_MM
    offset_px = g.mm_to_px(offset_mm)
    canvas = Image.new("RGBA", (g.A4_WIDTH_PX, g.A4_HEIGHT_PX), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    for part in parts:
        if part.x < 0 or part.y < 0:
            continue
        s = part.scale

        if part.subject_outline:
            # —— 参数化零件 ——
            poly = border.dieline_polygon(part.subject_outline, offset_px)
            if poly.is_empty:
                continue
            minx, miny, _, _ = poly.bounds
            ring = list(poly.exterior.coords)
            # 白底多边形(填白) + 刀模(描洋红)，以 poly.min 为局部原点对齐主体图
            white_pts = [(part.x + (px - minx) * s, part.y + (py - miny) * s)
                         for (px, py) in ring]
            if len(white_pts) >= 3:
                draw.polygon(white_pts, fill=(255, 255, 255, 255))
            # 贴主体图：主体局部原点(0,0)对应 poly 内主体位置 = (-minx,-miny)
            subj = Image.fromarray(part.subject_image, mode="RGBA")
            if s != 1.0:
                subj = subj.resize((max(1, int(subj.width * s)),
                                    max(1, int(subj.height * s))), Image.LANCZOS)
            sxoff = part.x + (0 - minx) * s
            syoff = part.y + (0 - miny) * s
            canvas.alpha_composite(subj, (int(sxoff), int(syoff)))
            _draw_polyline(draw, white_pts, g.DIECUT_RGB + (255,))
        else:
            # —— 固定零件(切割碎块/旧)：沿用 image_layer + dieline_path ——
            layer = Image.fromarray(part.image_layer, mode="RGBA")
            if s != 1.0:
                layer = layer.resize((max(1, int(part.w * s)),
                                      max(1, int(part.h * s))), Image.LANCZOS)
            canvas.alpha_composite(layer, (int(part.x), int(part.y)))
            src = part.dieline_path
            if src:
                for poly in vz.path_to_polylines(src):
                    pts = [(part.x + px * s, part.y + py * s) for (px, py) in poly]
                    _draw_polyline(draw, pts, g.DIECUT_RGB + (255,))
            else:
                pts = [(part.x + px * s, part.y + py * s) for (px, py) in part.contour]
                _draw_polyline(draw, pts, g.DIECUT_RGB + (255,))

    return canvas


def save_png(parts, out_path, offset_mm=None):
    render_png(parts, offset_mm=offset_mm).save(out_path)
```

- [ ] **Step 4: 运行全套确认通过**

Run: `.conda\python.exe -m pytest tests/ -v`（timeout 300000）
Expected: 全 PASS（含新 offset 用例；既有 exporter 用例——基于 build_part 的零件现走参数化路径仍出洋红，基于手工 Part(无 subject_outline)的走固定路径）。
若既有 `test_render_uses_vector_dieline_smooth` 因走参数化路径而断言不符，按其语义(洋红存在 + 跨度>150)应仍通过；如不过，检查该用例的 part 是否由 build_part 构造(有 subject_outline)并相应保留断言。

- [ ] **Step 5: 人工眼检**

Run:
```
.conda\python.exe -c "import cv2; from app import segmentation as s,part_builder as pb,nesting,exporter; img=cv2.imread('tests/fixtures/cats_11.png'); parts=[pb.build_part(img,x['mask']) for x in s.segment_subjects(img)]; nesting.nest(parts); exporter.save_png(parts,'tests/debug/para_2mm.png',offset_mm=2.0); exporter.save_png(parts,'tests/debug/para_6mm.png',offset_mm=6.0); print('ok')"
```
打开 `tests/debug/para_2mm.png` 与 `para_6mm.png`，确认 6mm 的白边明显更宽、刀模线更外、主体不变形。

- [ ] **Step 6: 提交**

```bash
git add app/exporter.py tests/test_exporter.py
git commit -m "feat: exporter 按全局白边参数化渲染(白底+主体+刀模)"
```

---

### Task 4: server 全局白边会话 + 主体字段下发

**Files:**
- Modify: `app/server.py`
- Test: `tests/test_server.py`（追加）

**Interfaces:**
- Consumes: `Part.subject_image`/`subject_outline`、`exporter.render_png(parts, offset_mm)`
- Produces:
  - 模块级会话 `OFFSET_MM`（默认 `geometry.OFFSET_MM`）。
  - `POST /api/set_border {offset_mm:float}` → `{ok:true, offset_mm}`，更新会话值。
  - `part_to_dict` 对有 `subject_outline` 的零件额外返回 `subject_image`(base64 PNG) + `subject_outline`(d) + `kind:"parametric"`；否则 `kind:"fixed"`。
  - `POST /api/export` 用会话 `OFFSET_MM` 渲染。

- [ ] **Step 1: 追加失败测试到 `tests/test_server.py`**

```python
def test_set_border_updates_session():
    client = server.app.test_client()
    r = client.post("/api/set_border", json={"offset_mm": 5.5})
    assert r.status_code == 200
    assert r.get_json()["offset_mm"] == 5.5
    assert server.OFFSET_MM == 5.5


def test_segment_returns_subject_fields():
    import numpy as np, cv2, base64
    img = np.full((300, 300, 3), 255, np.uint8)
    cv2.circle(img, (150, 150), 80, (0, 140, 200), -1)
    ok, buf = cv2.imencode(".png", img)
    b64 = "data:image/png;base64," + base64.b64encode(buf).decode()
    server.PARTS.clear()
    client = server.app.test_client()
    r = client.post("/api/segment", json={"image_base64": b64})
    assert r.status_code == 200
    parts = r.get_json()["parts"]
    assert parts and parts[0]["kind"] == "parametric"
    assert parts[0]["subject_outline"] and parts[0]["subject_image"].startswith("data:image/png")
```

- [ ] **Step 2: 运行确认失败**

Run: `.conda\python.exe -m pytest tests/test_server.py::test_set_border_updates_session -v`
Expected: FAIL（无 `/api/set_border`、无 `server.OFFSET_MM`）。

- [ ] **Step 3: 改 `app/server.py`**

在 `from app import segmentation, part_builder, nesting, exporter` 行后补 `from app import geometry as g`（若未导入）。模块级 `PARTS = {}` 附近新增：
```python
OFFSET_MM = g.OFFSET_MM  # 全局白边(会话级)，前端 /api/set_border 同步
```
`part_to_dict` 改为按零件类型下发（在原函数内分支）：
```python
def part_to_dict(part: Part) -> dict:
    """零件序列化给前端：参数化零件下发主体图+轮廓；固定零件下发合成图+刀模。"""
    if part.subject_outline:
        ok, buf = cv2.imencode(".png", cv2.cvtColor(part.subject_image, cv2.COLOR_RGBA2BGRA))
        if not ok:
            raise RuntimeError("主体图 PNG 编码失败")
        return {
            "id": part.id, "kind": "parametric",
            "subject_image": "data:image/png;base64," + base64.b64encode(buf).decode(),
            "subject_outline": part.subject_outline,
            "w": part.subject_image.shape[1], "h": part.subject_image.shape[0],
        }
    rgba = part.image_layer
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    if not ok:
        raise RuntimeError("零件图片层 PNG 编码失败")
    return {
        "id": part.id, "kind": "fixed",
        "image_base64": "data:image/png;base64," + base64.b64encode(buf).decode(),
        "w": part.w, "h": part.h, "dieline_path": part.dieline_path,
    }
```
新增路由（放在 `/api/export` 之前）：
```python
@app.route("/api/set_border", methods=["POST"])
def api_set_border():
    global OFFSET_MM
    d = _require_json("offset_mm")
    OFFSET_MM = float(d["offset_mm"])
    return jsonify({"ok": True, "offset_mm": OFFSET_MM})
```
`api_export` 渲染改为带全局 offset：
```python
    img = exporter.render_png(parts, offset_mm=OFFSET_MM)
```

- [ ] **Step 4: 运行确认通过**

Run: `.conda\python.exe -m pytest tests/test_server.py -v`（timeout 300000）
Expected: PASS（新 2 用例 + 既有；首次 segment 触发 rembg 已缓存）。

- [ ] **Step 5: 运行全套确认无回归**

Run: `.conda\python.exe -m pytest tests/ -v`（timeout 300000）
Expected: 全 PASS。

- [ ] **Step 6: 提交**

```bash
git add app/server.py tests/test_server.py
git commit -m "feat: server 全局白边会话 + 主体图/轮廓下发 + /api/set_border"
```

---

### Task 5: 前端参数化渲染 + 白边滑块 + 刀模显示 + 进度

**Files:**
- Create: `web/lib/clipper.js`（vendored clipper-lib 6.4.2，单文件）
- Modify: `web/index.html`（引入 clipper、白边滑块、进度条）
- Modify: `web/app.js`（参数化渲染、滑块、进度、固定零件兼容）
- Modify: `web/style.css`（滑块/进度样式）

**Interfaces:**
- Consumes: 后端 `/api/segment`(返回 kind/subject_image/subject_outline 或 image_base64/dieline_path)、`/api/set_border`、`/api/export`
- Produces: 画布上每个零件显示「白底 + 主体 + 洋红刀模线」；白边滑块逐帧实时；耗时操作有进度。无自动化测试，用末尾人工验收清单。

- [ ] **Step 1: 取得 clipper.js**

下载 clipper-lib 单文件到 `web/lib/clipper.js`：
Run:
```
mkdir -p web/lib
.conda\python.exe -c "import urllib.request as u; u.urlretrieve('https://cdn.jsdelivr.net/npm/clipper-lib@6.4.2/clipper.js','web/lib/clipper.js'); import os; print('size', os.path.getsize('web/lib/clipper.js'))"
```
Expected: 文件下载成功(数十~上百 KB)。若该 URL 失效，改用 `https://unpkg.com/clipper-lib@6.4.2/clipper.js`。提交时纳入 `web/lib/clipper.js`（前端库随仓库分发）。

- [ ] **Step 2: 改 `web/index.html`**

在 fabric.js 的 `<script>` 之后、`/app.js` 之前加：
```html
  <script src="/lib/clipper.js"></script>
```
在 header 的按钮区(导入图片 之后)插入白边滑块：
```html
    <label style="display:flex;align-items:center;gap:6px;font-size:13px">白边
      <input type="range" id="border-range" min="0" max="100" step="1" value="20">
      <input type="number" id="border-num" min="0" step="0.1" value="2" style="width:56px">
      <select id="border-unit"><option value="mm">mm</option><option value="px">px</option></select>
    </label>
```
在 `</header>` 之后、`#wrap` 之前插入进度条：
```html
  <div id="progress" style="display:none;height:3px;background:#e2e8f0">
    <div id="progress-bar" style="height:100%;width:30%;background:#ec4899;transition:width .2s"></div>
  </div>
```

- [ ] **Step 3: 改 `web/style.css`（追加）**

```css
#progress { width: 100%; }
#border-range { accent-color: #ec4899; }
```

- [ ] **Step 4: 改写 `web/app.js`**

核心改动（在现有文件基础上）：用 clipper 把 `subject_outline` 缓冲成白边多边形，合成 fabric.Group(白底多边形 + 主体图 + 洋红刀模线)；白边滑块改 offset 即重建所有参数化零件的 Group；固定零件用 image_base64+dieline_path。完整文件：

```javascript
// 视图缩放：画布显示 630x891，对应物理 2100x2970 px
const VIEW_SCALE = 0.3;
const PIXEL_RATIO = 10;                 // 1mm=10px（与后端 geometry 一致）
const canvas = new fabric.Canvas('c', { selection: true, backgroundColor: '#fff' });
const statusEl = document.getElementById('status');
const setStatus = (t) => statusEl.textContent = t;

let cutMode = false;
let borderPx = 20;                       // 当前白边(px，物理像素)，默认 2mm
const objById = new Map();
const partData = new Map();              // id -> 后端返回的零件数据(含 subject_outline 等)

// —— 进度 ——
const prog = document.getElementById('progress');
const progBar = document.getElementById('progress-bar');
function showProgress(p) { prog.style.display = 'block'; progBar.style.width = Math.round(p * 100) + '%'; }
function hideProgress() { prog.style.display = 'none'; }

async function api(path, body) {
  const r = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error(await r.text());
  return r;
}

// —— SVG path d → 点集（简单解析 M/L/C，C 取端点折线，够碰撞/显示用）——
function parseDToPolyline(d) {
  const pts = [];
  const re = /([MLC])([^MLCZ]*)/gi;
  let m;
  while ((m = re.exec(d))) {
    const nums = (m[2].match(/-?\d*\.?\d+/g) || []).map(Number);
    const cmd = m[1].toUpperCase();
    if (cmd === 'M' || cmd === 'L') {
      for (let i = 0; i + 1 < nums.length; i += 2) pts.push([nums[i], nums[i + 1]]);
    } else if (cmd === 'C') {
      for (let i = 0; i + 5 < nums.length; i += 6) pts.push([nums[i + 4], nums[i + 5]]);
    }
  }
  return pts;
}

// —— clipper 缓冲：主体轮廓点集 → 向外 offset 的白边/刀模多边形点集 ——
function bufferOutline(polyline, offsetPx) {
  const SCALE = 100;
  const path = polyline.map(([x, y]) => ({ X: Math.round(x * SCALE), Y: Math.round(y * SCALE) }));
  const co = new ClipperLib.ClipperOffset(2, 0.25);
  co.AddPath(path, ClipperLib.JoinType.jtRound, ClipperLib.EndType.etClosedPolygon);
  const solution = new ClipperLib.Paths();
  co.Execute(solution, offsetPx * SCALE);
  if (!solution.length) return [];
  // 取最大环
  let best = solution[0], bestA = 0;
  for (const p of solution) { const a = Math.abs(ClipperLib.Clipper.Area(p)); if (a > bestA) { bestA = a; best = p; } }
  return best.map(pt => [pt.X / SCALE, pt.Y / SCALE]);
}

// —— 由零件数据 + 当前 borderPx 构建一个 fabric.Group（画布像素，未定位）——
function buildGroup(p) {
  return new Promise((resolve) => {
    if (p.kind === 'parametric') {
      const outline = parseDToPolyline(p.subject_outline);
      const die = bufferOutline(outline, borderPx);   // 物理像素
      const minx = Math.min(...die.map(q => q[0])), miny = Math.min(...die.map(q => q[1]));
      const ringView = die.map(([x, y]) => ({ x: (x - minx) * VIEW_SCALE, y: (y - miny) * VIEW_SCALE }));
      const white = new fabric.Polygon(ringView, { fill: '#fff', stroke: '', selectable: false, evented: false, objectCaching: false });
      const dieLine = new fabric.Polygon(ringView, { fill: '', stroke: '#FF00FF', strokeWidth: 1, selectable: false, evented: false, objectCaching: false });
      fabric.Image.fromURL(p.subject_image, (img) => {
        img.set({ left: (0 - minx) * VIEW_SCALE, top: (0 - miny) * VIEW_SCALE, scaleX: VIEW_SCALE, scaleY: VIEW_SCALE, selectable: false, evented: false });
        const grp = new fabric.Group([white, img, dieLine], { partId: p.id, cornerSize: 8, transparentCorners: false });
        resolve(grp);
      }, { crossOrigin: null });
    } else {
      fabric.Image.fromURL(p.image_base64, (img) => {
        img.set({ scaleX: VIEW_SCALE, scaleY: VIEW_SCALE, selectable: false, evented: false });
        const children = [img];
        if (p.dieline_path) {
          const ring = parseDToPolyline(p.dieline_path).map(([x, y]) => ({ x: x * VIEW_SCALE, y: y * VIEW_SCALE }));
          if (ring.length >= 2) children.push(new fabric.Polygon(ring, { fill: '', stroke: '#FF00FF', strokeWidth: 1, selectable: false, evented: false, objectCaching: false }));
        }
        resolve(new fabric.Group(children, { partId: p.id, cornerSize: 8, transparentCorners: false }));
      }, { crossOrigin: null });
    }
  });
}

async function addPart(p, x, y) {
  partData.set(p.id, p);
  const grp = await buildGroup(p);
  grp.set({ left: x, top: y });
  objById.set(p.id, grp);
  canvas.add(grp);
  canvas.requestRenderAll();
}

// —— 重建某零件 Group（白边变化时，保留位置/缩放）——
async function rebuildPart(id) {
  const old = objById.get(id);
  if (!old) return;
  const { left, top, scaleX, angle } = old;
  const grp = await buildGroup(partData.get(id));
  grp.set({ left, top, scaleX, scaleY: scaleX, angle });
  canvas.remove(old);
  objById.set(id, grp);
  canvas.add(grp);
}

// 导入图片 -> /api/segment
document.getElementById('btn-import').onclick = () => document.getElementById('file').click();
document.getElementById('file').onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  setStatus('抠图中…'); showProgress(0.3);
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const r = await api('/api/segment', { image_base64: reader.result });
      const { parts } = await r.json();
      showProgress(0.7);
      let i = 0;
      for (const p of parts) { await addPart(p, 20 + (i % 5) * 110, 20 + Math.floor(i / 5) * 110); i++; }
      setStatus(`分离出 ${parts.length} 个零件`);
    } catch (err) { setStatus('抠图失败: ' + err.message); }
    finally { hideProgress(); }
  };
  reader.readAsDataURL(f);
  e.target.value = '';
};

// —— 白边滑块（mm/px，全局，实时）——
const rng = document.getElementById('border-range');
const num = document.getElementById('border-num');
const unit = document.getElementById('border-unit');
function setBorderFromMm(mm) {
  borderPx = mm * PIXEL_RATIO;
  for (const id of objById.keys()) { if (partData.get(id).kind === 'parametric') rebuildPart(id); }
  canvas.requestRenderAll();
}
function syncFromControls() {
  let mm = parseFloat(num.value) || 0;
  if (unit.value === 'px') mm = mm / PIXEL_RATIO;
  rng.value = Math.min(100, Math.round(mm * PIXEL_RATIO));
  setBorderFromMm(mm);
}
rng.oninput = () => {
  const mm = parseFloat(rng.value) / PIXEL_RATIO;
  num.value = (unit.value === 'px') ? (mm * PIXEL_RATIO).toFixed(0) : mm.toFixed(1);
  setBorderFromMm(mm);
};
num.oninput = syncFromControls;
unit.onchange = syncFromControls;
// 松手把最终值同步给后端（导出用）
function commitBorder() {
  const mm = parseFloat(rng.value) / PIXEL_RATIO;
  api('/api/set_border', { offset_mm: mm }).catch(() => {});
}
rng.onchange = commitBorder;
num.onchange = commitBorder;

// 导出 PNG -> /api/export
document.getElementById('btn-export').onclick = async () => {
  const items = [...objById.values()].map(o => ({
    id: o.partId, x: Math.round(o.left / VIEW_SCALE), y: Math.round(o.top / VIEW_SCALE),
    scale: (o.scaleX || VIEW_SCALE) / VIEW_SCALE
  }));
  if (!items.length) { setStatus('画布为空'); return; }
  setStatus('导出中…'); showProgress(0.5);
  try {
    const r = await api('/api/export', { items });
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'diecut_layout.png'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setStatus('已导出');
  } catch (err) { setStatus('导出失败: ' + err.message); }
  finally { hideProgress(); }
};

// 删除选中
document.getElementById('btn-delete').onclick = () => {
  const t = canvas.getActiveObject();
  if (t && t.partId) { objById.delete(t.partId); partData.delete(t.partId); canvas.remove(t); canvas.discardActiveObject(); canvas.requestRenderAll(); }
};

// 整理排版 -> /api/nest（沿用：位置回填）
document.getElementById('btn-tidy').onclick = async () => {
  const items = [...objById.values()].map(o => ({ id: o.partId, scale: (o.scaleX || VIEW_SCALE) / VIEW_SCALE }));
  if (!items.length) return;
  setStatus('排版中…'); showProgress(0.5);
  try {
    const r = await api('/api/nest', { items });
    const { positions } = await r.json();
    for (const pos of positions) {
      const o = objById.get(pos.id);
      if (!o || pos.x < 0) continue;
      o.set({ left: pos.x * VIEW_SCALE, top: pos.y * VIEW_SCALE }); o.setCoords();
    }
    canvas.requestRenderAll(); setStatus('排版完成');
  } catch (err) { setStatus('排版失败: ' + err.message); }
  finally { hideProgress(); }
};

// 切割按钮：本阶段保持占位（切割流程 Phase 5 重做）
document.getElementById('btn-cut').onclick = () => setStatus('切割将在后续版本重做');
```
（注：本阶段切割交互留待 Phase 5；按钮先给提示，不接旧切割逻辑，避免与新分组渲染冲突。导出/排版仍用 part id + 变换，后端据 id 取零件。）

- [ ] **Step 5: 启动并人工验收**

Run（或双击 start.bat）: `.conda\python.exe -m app.server`
逐项验收：
1. 导入 `tests/fixtures/cats_11.png` → 画布每个零件显示「白底 + 猫 + 洋红刀模线」，刀模平滑。
2. 拖「白边」滑块 → 所有零件白底与洋红刀模线**一起、逐帧、平滑**变粗/变细，不卡。
3. 切换 mm/px、改数字框 → 与滑块联动正确。
4. 「整理排版」零件紧凑；「导出 PNG」下载的图与画布所见一致（白边宽度=当前滑块值）。
5. 导入/导出时顶部出现进度条。

- [ ] **Step 6: 提交**

```bash
git add web/lib/clipper.js web/index.html web/app.js web/style.css
git commit -m "feat: 前端参数化白边(clipper实时缓冲)+画布刀模线+白边滑块+进度"
```

---

## Self-Review

**1. Spec 覆盖：**
- 参数化零件(主体图+轮廓) → Task 2 ✅；border 缓冲 → Task 1 ✅。
- 白边全局参数、实时前端 → Task 5(clipper 滑块) ✅。
- 画布显示刀模线 → Task 5 ✅。
- 后端 shapely 缓冲导出 → Task 3 ✅；全局 offset 会话 + set_border → Task 4 ✅。
- 进度(抠图/导出) → Task 5 ✅。
- 固定零件(切割碎块)兼容 → Task 3/5 走 image_layer/dieline_path 分支 ✅。
- cut 不破：本阶段切割按钮改占位提示(Phase 5 重做)，不调用旧 cut 渲染——避免与分组渲染冲突；旧 `cut_part`/`api_cut` 代码保留不删，后端测试仍覆盖。⚠️ 与 spec「cut 保持可用」有出入：spec 要求 cut 仍能产出固定碎块，本计划为降风险改为前端占位。**这是需要人类裁决的偏差**(见下)。

**2. Placeholder 扫描：** 无 TODO/TBD；frontend 代码完整给出。

**3. 类型一致性：** `dieline_polygon/dieline_path_at`(border)、`subject_image/subject_outline`(models)、`render_png(parts, offset_mm)`(exporter)、`OFFSET_MM`/`/api/set_border`/part_to_dict kind(server) 跨任务一致；前端按 `kind` 分支消费后端字段一致。

**⚠️ 计划偏差(需裁决)：** spec 第「后端」节要求 `cut_part` 在 Phase 2 保持可用(产出固定碎块)；本计划 Task 5 为降低与新分组渲染的冲突风险，改为**前端切割按钮占位、Phase 5 再接**。后端 `cut_part`/`/api/cut` 不动、测试照常。需用户确认：Phase 2 前端切割「占位」可接受，还是必须保持端到端可切。
