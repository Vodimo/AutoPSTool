# AutoPSTool — 贴纸刀模自动生成与排版

把**白底卡通图**一键做成可印刷、可切割的贴纸版面:AI 抠图分离每个主体 → 沿轮廓外扩生成白边与刀模线 → 在固定画布上交互式拖动/缩放/切割 → 紧凑排版 → 导出含洋红刀模线的印刷图。

> 面向「找一张白底卡通图(一个或多个主体),想做成贴纸」的场景,免去手工抠图、描刀模、排版的繁琐流程。

---

## 功能特性

- **稳定抠图**:用 AI 模型(rembg / u2netp)抠图,对「白底 + 主体内部白色 + 低色差边缘」鲁棒,几乎零参数,告别反复调参。
- **多主体自动分离**:一张图里有多个主体时,自动拆成多个独立**零件**(连通域分离 + 去毛刺 + 内部填洞,白猫不会被当背景、内部白区不会变透明洞)。
- **自动白边 + 刀模轮廓**:沿主体轮廓向外膨胀生成白边,白边外缘即刀模切割线。
- **交互式画布**:抠好的零件直接散落在 A4 画布,可拖动、缩放(调整相对大小)。
- **分件切割**:把过大/形状别扭的单个主体切成几块,切口两侧带**重叠出血**,贴的时候沿切割线拼回去。
- **一键紧凑排版**:Bottom-Left-Fill 启发式把所有零件紧凑重排,互不重叠、不超出画布。
- **导出**:单张 A4 PNG,含图片 + 白边底 + 洋红(`#FF00FF`)刀模线。

---

## 快速开始

### 环境准备

项目使用项目内置的 conda 环境 `.conda`(Python 3.11)。首次准备:

```bash
conda create -p .\.conda python=3.11 -y
.conda\python.exe -m pip install -r requirements.txt
```

> 首次运行抠图时会自动下载约 170MB 的 rembg 模型(u2netp),需联网,之后离线可用。

### 运行

双击 **`start.bat`**,或:

```bash
.conda\python.exe -m app.server
```

Flask 启动后会自动打开浏览器到 `http://127.0.0.1:5000`,前端由后端同源托管,无需单独打开 HTML。

### 使用流程

1. **导入图片**:选择一张白底卡通图(PNG/JPG)。稍候片刻,主体会被抠出并散落在画布上。
2. **调整**:拖动零件移动位置;拖角缩放改变相对大小。
3. **切割(可选)**:点「切割模式」,选中某个零件后在它上面拖一条线,把它切成带出血的两块。
4. **整理排版**:点「整理排版」,所有零件紧凑重排。
5. **导出 PNG**:点「导出 PNG」,下载最终版面。

---

## 工作原理

整个工具围绕统一的 `Part`(零件)数据模型,后端流水线分五个独立、可单测的阶段:

```
导入图 ──▶ segmentation ──▶ part_builder ──▶ (交互: 拖/缩/切) ──▶ nesting ──▶ exporter
          引擎C抠图分离      白边+刀模轮廓      前端 fabric.js 画布     紧凑排版    单张PNG
```

| 模块 | 职责 |
|---|---|
| `app/geometry.py` | 物理常量单一来源:`PIXEL_RATIO=10`(1mm=10px)、A4=2100×2970px、白边/出血/间距、刀模色 |
| `app/cv_helpers.py` | CV 工具:填洞 / 连通域分离 / 去毛刺 / 膨胀 |
| `app/segmentation.py` | 引擎C:rembg 抠图 → 去毛刺 → 连通域分离 → 内部填洞,返回多主体掩膜 |
| `app/models.py` | `Part` 数据模型(图片层 / 刀模掩膜 / 轮廓 / 位置 / 缩放) |
| `app/part_builder.py` | 单主体→零件(白边膨胀 + 刀模轮廓);SDF 半平面出血切割 |
| `app/nesting.py` | Bottom-Left-Fill 紧凑排版(轮廓先简化加速碰撞检测) |
| `app/exporter.py` | 渲染单张 A4 PNG:图片层 + 洋红刀模线 |
| `app/server.py` | Flask:托管前端 + 内存零件会话 + API(`/api/segment\|cut\|nest\|export`)+ 浏览器自启 |

前端:`web/index.html` + `web/app.js` + `web/style.css`,基于 fabric.js 的交互画布。

---

## 测试

```bash
.conda\python.exe -m pytest tests/ -v
```

抠图调试视图(把每个主体掩膜叠色输出,供肉眼验收):

```bash
.conda\python.exe scripts\debug_segmentation.py tests\fixtures\cats_11.png
```

---

## 技术栈

Python 3.11 · Flask · OpenCV · NumPy · Shapely · Pillow · rembg + onnxruntime;前端 fabric.js。

---

## 约定与范围

- 代码注释与日志使用中文。
- 物理常量只在 `app/geometry.py` 定义一处,其他模块从此导入。
- 刀模线颜色统一为洋红 `#FF00FF`。
- 当前版本(v1)聚焦「导入 → 抠图分离 → 白边/刀模 → 拖/缩/切 → 整理 → 导出单张 PNG」。SVG/PDF 导出、专色分版、旋转排版、撤销历史等留作后续迭代(内部已按「图片层 / 矢量刀模层分离」设计,便于扩展导出格式)。
