# Phase 2 · 白边参数化 + 画布刀模线显示 — 设计文档

- 日期：2026-06-26
- 状态：已通过用户确认，待写实施计划
- 性质：**增量改造**；本文档细化主 spec(`2026-06-26-interaction-nesting-refinements-design.md` 第 2 站)的「白边可调 + 画布显示刀模线」部分，落到具体架构。
- 依赖：Phase 1（potrace 矢量化、`app/vectorize.py`、`Part.dieline_path`）已完成并合入 master。

## 目标

让白边宽度成为**全局、实时、所见即所得**的参数，并在画布上实时显示洋红刀模线。核心手段：把白边从「烤进位图」改为「由主体矢量轮廓向外缓冲(offset)实时生成」。

## 核心概念：参数化零件 vs 固定零件

零件分两类：

- **参数化零件(parametric)**：导入抠图得到的默认形态。存「纯主体图(透明底，不含白边)」+「主体矢量轮廓」。其白边与刀模线 = 对主体轮廓向外缓冲 `offset_px`（圆角 join）实时得到。全局白边变化只影响这类零件。
- **固定零件(fixed)**：切割产生的碎块。切口那一侧白边为 0（平直无法用统一 offset 表达），故保留冻结的刀模线与已合成图层（Phase 1 的现有形态）。全局白边变化**不影响**固定零件（符合直觉：切好的块不应因改全局白边而变形）。

## 数据模型（`app/models.py`）

`Part` 增加/调整字段（增量）：

- `kind: str`（`"parametric"` | `"fixed"`），默认 `"parametric"`。
- 参数化零件用：
  - `subject_image: np.ndarray`（HxWx4 RGBA，主体像素 + 透明背景，裁到主体包围盒，**不含白边**）。
  - `subject_outline: str`（主体掩膜的 potrace 矢量轮廓，局部坐标 SVG `d`）。
- 固定零件沿用 Phase 1 字段：`image_layer`、`dieline_path`、`mask`。
- 既有 `contour`/`mask` 对参数化零件可保留为空或主体掩膜信息（实现时择一，保证下游不崩）。

全局会话状态新增：`offset_mm: float`（白边宽度，默认 `geometry.OFFSET_MM=2.0`）。

## 几何：缓冲生成白边/刀模

新增 `app/border.py`（或并入 vectorize）：

- `dieline_polygon(subject_outline_d: str, offset_px: float) -> shapely.Polygon`：把主体矢量轮廓离散为多边形，向外 `buffer(offset_px, join_style=round)`，得到白边外缘=刀模线多边形。
- `dieline_path_at(subject_outline_d, offset_px) -> str`：上面多边形转回 SVG `d`（供导出/前端一致）。
- 数学一致性：圆盘膨胀 = 与圆盘的 Minkowski 和 = 圆角缓冲，故与 Phase 1 的栅格膨胀同形。

## 后端（`app/part_builder.py` / `app/server.py` / `app/exporter.py`）

- `build_part(image_bgr, subject_mask, part_id=None) -> Part`：**不再接受 offset**；产出参数化零件——`subject_image`(裁到主体 bbox 的 RGBA，透明底) + `subject_outline`(potrace 主体掩膜)。
- `cut_part(...)`：保持可用。实现为「按当前全局 offset 实体化该零件的刀模掩膜 → 现有 SDF 半平面切割 → 产出两个 **固定零件**(冻结刀模)」。切割交互整体留待 Phase 5 重做，本阶段只保证不破。
- `server.py`：
  - 全局会话保存 `offset_mm`，新增 `POST /api/set_border {offset_mm}`（仅存值，供导出使用；返回 ok）。
  - `part_to_dict` 对参数化零件返回 `kind` + `subject_image`(base64 PNG) + `subject_outline`(d) + 主体 w/h；对固定零件返回 `kind` + `image_base64` + `dieline_path`。
- `exporter.render_png(parts, offset_px)`：对参数化零件用 shapely 缓冲出白边多边形→填白底→贴主体图→描洋红刀模；对固定零件沿用 Phase 1 路径（贴 image_layer + 画 dieline_path）。导出用当前全局 `offset_mm`。

## 前端（`web/app.js` / `web/index.html` / `web/style.css`）

- 引入 **clipper.js**（前端多边形缓冲；SVGnest 后续也用）。
- 渲染每个参数化零件：用 clipper 对 `subject_outline` 缓冲 `offset_px` → 得到白边/刀模多边形 → 在画布上合成「白底多边形 + 主体图 + 洋红刀模描边」。固定零件直接用其 `dieline_path` 与 `image_base64`。
- **白边全局滑块**（mm/px，默认 2mm）：改动时**纯前端**重新缓冲并重绘所有参数化零件，**逐帧实时、零往返**；同时调 `POST /api/set_border` 把值同步给后端（供导出）。
- 画布上实时显示洋红刀模线（随拖动/缩放/改白边更新）。

## 进度反馈

- 白边调整因纯前端实时，无需进度。
- 需进度提示的是：**抠图/导入**（尤其多图，逐张进度）与**导出**。本阶段为这两类加进度条/状态文字（异步、不卡界面）。

## 非目标（本阶段不做）

- 工作区缩放/平移、纸框（Phase 3）。
- 旋转打通（Phase 4）。
- 切割流程重做（Phase 5）——本阶段仅保证 cut 不破（产出固定碎块）。
- 多选/追加导入的完整化（Phase 7）——本阶段进度针对当前导入即可。

## 验收标准

- 导入后画布上每个零件显示「白底 + 主体 + 洋红刀模线」，刀模线平滑。
- 拖白边滑块：所有参数化零件的白边与刀模线一起逐帧平滑变粗/变细，无卡顿、无延迟、所见即所得。
- 切割仍可用，产出的碎块带冻结刀模，改全局白边不影响碎块。
- 导出 PNG 与画布所见一致（参数化零件按当前全局白边渲染）。
- 抠图/导出有进度提示。
- 既有后端测试（vectorize/exporter 等）适配后全绿。

## 测试要点

- `border.dieline_polygon`：圆/矩形主体轮廓缓冲后包围盒 ≈ 主体 bbox 外扩 offset；offset=0 时 ≈ 主体轮廓。
- `build_part`：返回参数化零件，`subject_image` 透明底、`subject_outline` 非空含曲线。
- `exporter.render_png`：参数化零件在给定 offset 下产出洋红刀模，白底范围随 offset 增大而变大。
- 前端缓冲与后端缓冲视觉一致性（同一 offset 下刀模 bbox 接近）——可用一个对照脚本人工核验。
