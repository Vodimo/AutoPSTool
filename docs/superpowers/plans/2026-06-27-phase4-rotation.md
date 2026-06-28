# Phase 4 · 旋转锁角 + 导出旋转 Implementation Plan

> 执行：subagent-driven。严格守范围:只做「手动旋转的锁角模型 + 导出按角度正确渲染」。**不碰 nesting 的自动旋转(Phase 8)**、不碰切割(Phase 5)。

**Goal:** 手动旋转零件能被正确导出(现在 fabric 能转但导出忽略角度→导出错位);手动旋转即「锁角」(视觉标记 📌+洋红框),`L` 键或点击可解锁(归零角度、交还 Phase 8 自动旋转)。

## 锁定决策
- **导出契约改为中心+角度**:前端每个零件发 `{id, cx, cy, angle, scale}` —— `cx,cy`=零件视觉中心(物理 px,`group.getCenterPoint()`,与视口无关);`angle`=度(fabric 顺时针);`scale`。后端按中心放置、按角度旋转,**与画布所见一致**。
- **后端导出改为「逐零件 tile → 旋转 → 居中粘贴」**:每个零件先渲染未旋转 tile(白底+主体+洋红刀模,按 scale),再 PIL `rotate(expand)` 按角度旋,粘到以 (cx,cy) 为中心处。
- **锁角模型(前端)**:手动旋转(改 angle)即把该 group 置 `locked=true`;锁角=洋红选中框+角上 📌;`L` 键或点击 📌 切换;**解锁=angle 归 0 + locked=false**。`locked` 仅前端状态(Phase 8 排版会读它决定是否自动转);本阶段导出只认 angle。
- **nesting 不动**:interim BLF 仍忽略旋转;手动旋转后整理排版的占位精度问题留待 Phase 8。

## Global Constraints
- Python 3.11;`.conda\python.exe -m pytest tests/ -v`;物理常量只在 geometry.py;洋红 #FF00FF;注释中文;提交体末尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

---

### Task 1: 后端导出支持旋转(逐零件 tile + 中心放置)

**Files:** `app/models.py`(Part 加 `cx`/`cy`)、`app/exporter.py`(重构为 tile+rotate)、`app/server.py`(api_export 读 cx/cy/angle)、`tests/test_exporter.py`。

**要求:**
- `Part` 加 `cx: float | None = None`、`cy: float | None = None`(放在 defaulted 区)。
- `exporter.render_png(parts, offset_mm=None, page_px=None)`:对每个 part(跳过 x<0&无cx 的未放置项):
  1. 构建未旋转 tile(RGBA):
     - 参数化(有 subject_outline):`poly=border.dieline_polygon(subject_outline, offset_px)`;`minx,miny,maxx,maxy=poly.bounds`;tile 尺寸 `(ceil((maxx-minx)*scale), ceil((maxy-miny)*scale))`;在 tile 上画白多边形(点 `(px-minx)*scale,(py-miny)*scale`)、贴主体图(缩放后,位置 `(0-minx)*scale,(0-miny)*scale`)、描洋红刀模。
     - 固定(无 subject_outline):tile=image_layer(按 scale resize)+ 在其上按 dieline_path/contour 画洋红。
  2. 若 `part.rotation` 非 0:`tile = tile.rotate(-part.rotation, resample=BICUBIC, expand=True)`(PIL 逆时针为正,fabric 顺时针为正,故取负)。
  3. 居中粘贴:`center = (part.cx, part.cy) if part.cx is not None else (part.x + tile_w0/2, part.y + tile_h0/2)`(tile_w0=未旋转 tile 宽);粘贴左上 = `(round(cx - tile.width/2), round(cy - tile.height/2))`,用 `alpha_composite`。
- `save_png` 透传。
- `server.api_export`:item 读 `cx,cy,angle,scale`(兼容旧 x,y:若无 cx 则用 x,y 作 topleft);设 `p.cx,p.cy,p.rotation,p.scale`。

**TDD(test_exporter.py 追加):**
- [ ] `test_render_rotation_swaps_bbox`:用 build_part 造一个**明显非方形**零件(如宽扁的椭圆图),设 `p.cx,p.cy=纸面中心, p.rotation=0` 渲染量洋红 bbox 宽高(w0,h0);再设 `p.rotation=90` 渲染量(w1,h1);断言 `abs(w1-h0)/h0 < 0.2 and abs(h1-w0)/w0 < 0.2`(旋转 90° 后宽高互换)。先 RED 后 GREEN。
- [ ] 既有 exporter 测试仍绿(未设 cx 走 topleft 回退;size/magenta 不变)。
- [ ] 全套 `pytest tests/ -v` 绿。
- [ ] 提交 `feat: 导出支持旋转(逐零件tile+中心放置+按角度旋转)`。

---

### Task 2: 前端锁角模型 + 旋转交互 + 导出发中心/角度

**Files:** `web/app.js`(可能 `web/style.css`)。

**要求:**
- **启用旋转**:fabric group 默认带旋转手柄(确认 `lockRotation` 未设 true)。
- **手动旋转=自动锁角**:监听 `canvas.on('object:rotating'... )` 或 `object:modified`,当 group.angle≠0 或发生旋转时设 `grp.locked=true`。
- **视觉标记**:锁角 group 选中框/手柄用洋红(`borderColor:'#FF00FF', cornerColor:'#FF00FF'`),自由的用默认蓝;并在角上显示 📌(可用一个小 fabric.Text/Group 角标,或简单地用洋红边框+控制台状态文字提示「已锁角」即可——优先洋红边框区分,📌 角标尽力而为)。
- **解锁**:选中锁角零件时按 `L` 键 或 点击它 → `grp.set({angle:0}); grp.locked=false; 恢复蓝色框; setCoords; render`。给个状态提示。
- **导出**:`btn-export` 的 items 改为 `{id, cx:中心x, cy:中心y, angle:grp.angle||0, scale:grp.scaleX||1}`,其中中心 `const c=o.getCenterPoint(); cx=Math.round(c.x); cy=Math.round(c.y)`(物理坐标)。框外过滤仍按未旋转 bbox 近似(沿用现有 getBoundingRect 判断)。
- **整理排版**:nest 回填后这些零件 angle 不变(interim);锁角零件保持其角度(只挪 left/top)。不改 nest 后端。
- 白边重建 `rebuildPart` 要**保留 angle 与 locked**(已保留 angle;补 `grp.locked=old.locked` 与洋红框)。

- [ ] 实现上述;preview_eval 核验:手动 set 一个 group `.angle=30` 触发后 `grp.locked` 真值/洋红框;导出 items 含 cx,cy,angle;`L` 解锁归零。
- [ ] 提交 `feat: 前端旋转锁角模型(自动锁/洋红标记/L解锁)+导出发中心角度`。

---

## 验收
- 手动旋转零件 → 导出 PNG 中该零件按相同角度、相同中心位置呈现(不再错位)。
- 锁角有洋红标记;`L`/点击解锁归零。
- 既有功能(白边/导入/整理/导出框外过滤)不回归;全套 pytest 绿。
