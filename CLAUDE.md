# CLAUDE.md

本文件为 Claude Code（claude.ai/code）提供仓库说明。

## 概述

AutoPSTool 自动化贴纸刀模生成与印刷排版。给定贴纸图像（可附用户画线做切割），AI 抠图提取主体，生成向外白边，得到矢量刀模轮廓，将多件紧凑排版到 A4 画板，导出含洋红刀模线的印刷图 PNG。

架构：`app/`（后端 Python 模块）+ `web/`（前端静态文件）。

`tools/msys64/` 为供货的 MSYS2 工具链，**忽略**，不是项目源码。`docs/` 为空目录。

## 运行

双击 `start.bat`（或 `.conda\python.exe -m app.server`）。  
Flask 启动后自动打开 `http://127.0.0.1:5000`。前端由 Flask 同源托管，无需单独打开 HTML 文件。

## 测试

```bash
.conda\python.exe -m pytest tests/ -v      # 23 个单元/集成测试，全部应 PASS
```

抠图调试视图（输出分割结果图）：

```bash
.conda\python.exe scripts\debug_segmentation.py tests\fixtures\cats_11.png
```

## 架构（`app/`）

五个独立可单测模块 + Flask 服务，围绕 `app/models.py:Part` 数据模型流转：

| 模块 | 职责 |
|---|---|
| `geometry.py` | 物理常量单一来源：`PIXEL_RATIO=10`（1mm=10px）、A4=2100×2970px、`OFFSET_MM`/`PADDING_MM`/`DIECUT_RGB` |
| `cv_helpers.py` | CV 工具函数：`fill_holes` / `separate_components` / `clean_edges` / `dilate_mask` |
| `segmentation.py` | 引擎 C：rembg（模型 **u2netp**）→ `clean_edges` → `separate_components` → `fill_holes`；`segment_subjects(image_bgr)` 返回多主体 mask 列表 |
| `models.py` | `Part` dataclass：`id`, `image_layer`（RGBA ndarray）, `mask`, `contour`, `x`, `y`, `scale`, `rotation`；计算属性 `w`/`h` |
| `part_builder.py` | `build_part(image_bgr, subject_mask, offset_mm, part_id)` 白边膨胀+刀模轮廓；`cut_part_parametric(part, p1, p2)` 沿切线截断主体并记录 `cut_planes`（渲染时刀模与半平面求交 → 刀模线正好落在切割线上，白边仍实时可调）；`apply_brush` 画笔加/擦 |
| `nesting.py` | Bottom-Left-Fill 紧凑排版；轮廓先 Shapely 简化（`SIMPLIFY_TOLERANCE_PX`）加速碰撞检测 |
| `exporter.py` | `render_png(parts)` → 单张 A4 PNG：图像层 + 洋红（`#FF00FF`）刀模线 |
| `server.py` | Flask 托管前端（`/`）+ 静态文件 + 内存 Part 会话 + API：`/api/segment|cut|nest|export`；`main()` 自动打开浏览器；监听 `127.0.0.1:5000` |

前端：`web/index.html` + `web/app.js` + `web/style.css`，fabric.js 交互画布（导入/拖拽/缩放/画线切割/整理/导出）。

## 环境与依赖

项目内 conda 环境 `.conda`（Python 3.11）。依赖见 `requirements.txt`。  
关键依赖：`rembg` + `onnxruntime`（AI 抠图，首次运行自动下载约 170MB 模型 **u2netp**）、`opencv-python`、`numpy`、`shapely`、`Pillow`、`flask`、`flask-cors`。

## 约定

- 代码注释与日志消息使用中文，编辑已有文件时保持风格一致。
- 刀模线颜色：PNG/SVG 输出中为洋红 `#FF00FF`。
- 物理常量仅在 `app/geometry.py` 中定义，其他模块从此处导入，**不要**在其他模块重复定义。
