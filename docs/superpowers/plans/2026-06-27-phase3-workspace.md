# Phase 3 · 工作区重构 Implementation Plan

> 执行：subagent-driven。本计划含锁定的设计决策 + 任务。严格守范围(只做工作区/纸框/尺寸/视图)，不碰排版算法(Phase 8)、不碰旋转(Phase 4)、不碰切割(Phase 5)。

**Goal:** 把画布从「固定 0.3 缩放显示整张 A4」改造为「可缩放/平移的大工作区 + 其中一个可调尺寸的纸框(可印刷区)」，零件可放到纸框外且始终可见；导出按当前纸张尺寸、仅含框内零件。

**坐标模型(核心)：** 内部一律用**物理像素**(1mm=10px)。显示靠 fabric 视图变换(`canvas.setViewportTransform`/`zoomToPoint`)，**弃用固定 VIEW_SCALE=0.3**。零件 group 以物理尺寸构建(subject 图 scaleX=1)，位置为物理 px；nest 返回/导出 items 直接用物理 px(不再 ×/÷0.3)。

## Global Constraints
- Python 3.11；测试 `.conda\python.exe -m pytest tests/ -v`。
- 物理常量只在 `app/geometry.py`(`PIXEL_RATIO=10`、A4=2100×2970)。
- 代码注释中文；提交体末尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- 不改：nesting 算法、cut、旋转、白边参数化(沿用 Phase 2)。

## 锁定的设计决策
- **视图**：滚轮以光标为中心缩放(`zoomToPoint`)；**空格+拖动** 与 **鼠标中键拖动** 都可平移；缩放区间 **0.1–8(10%–800%)**；打开/导入后 **fit-to-view**(纸框+所有零件刚好可见)；新增 **「适应视图」按钮** 一键重置。
- **纸框**：一个不可选中、不可拖动的 `fabric.Rect`(白色填充、浅灰描边)置于所有零件之下，位于工作区原点 (0,0)，尺寸=当前纸张物理像素。零件可在框内框外，始终可见。
- **纸张尺寸**：预设 **A4(210×297)/A3(297×420)/A5(148×210)/Letter(216×279)**(mm) + **自定义 宽/高**；单位 **mm/px** 切换；**随时可改**；改后纸框左上角仍锚定 (0,0)，零件**保持物理坐标不动**(可能露到框外，照常显示)。
- **导出**：按**当前纸张尺寸**渲染；**只导出刀模完全/主要落在框内的零件**；导出前若有框外零件，**弹确认提示**(「有 N 个零件在纸框外，不会被导出，是否继续？」)。
- **画布 DOM**：`<canvas id="c">` 改为填充 `#wrap` 可用区域(响应式宽高)，不再写死 630×891。

## File Structure
- `app/geometry.py`：新增纸张预设表 `PAGE_PRESETS`(mm) 与换算辅助(若需要)。
- `app/exporter.py`：`render_png(parts, offset_mm=None, page_px=None)` 支持可变页尺寸。
- `app/server.py`：会话 `PAGE_W_MM`/`PAGE_H_MM`(默认 A4)；`POST /api/set_page {w_mm,h_mm}`；export 用当前页尺寸。
- `web/index.html`：纸张尺寸控件(预设下拉+宽高输入+单位)、「适应视图」按钮。
- `web/app.js`：坐标模型改物理 px、fabric 缩放/平移、纸框、尺寸控件、fit-view、导出框外过滤+提示。
- `web/style.css`：画布填充、控件样式。
- tests：`test_exporter.py`(可变页尺寸)、`test_server.py`(set_page)。

---

### Task 1: 后端可变页尺寸(exporter + server)

**Files:** `app/geometry.py`, `app/exporter.py`, `app/server.py`, `tests/test_exporter.py`, `tests/test_server.py`

**Interfaces / 要求:**
- `geometry.PAGE_PRESETS = {"A4":(210,297),"A3":(297,420),"A5":(148,210),"Letter":(216,279)}`(mm)。
- `exporter.render_png(parts, offset_mm=None, page_px=None)`：`page_px=(w,h)` 默认 `(A4_WIDTH_PX, A4_HEIGHT_PX)`；画布按 page_px 大小；其余渲染逻辑不变。`save_png` 同步加 `page_px`。
- `server`：模块级 `PAGE_W_MM=210`、`PAGE_H_MM=297`；`POST /api/set_page {w_mm,h_mm}` → 校验为正数、更新会话、返回 `{ok,w_mm,h_mm}`；`api_export` 用 `page_px=(mm_to_px(PAGE_W_MM), mm_to_px(PAGE_H_MM))`。

**TDD：**
- [ ] **Step 1**：`tests/test_exporter.py` 加 `test_render_custom_page_size`：构造一个 build_part 零件，`render_png([p], page_px=(800,600))` 返回 PIL 图 `.size==(800,600)`；默认仍 `(2100,2970)`。先跑 RED。
- [ ] **Step 2**：实现 exporter 的 `page_px` 参数(默认 A4)。跑 GREEN。
- [ ] **Step 3**：`tests/test_server.py` 加 `test_set_page_updates_session`：POST `/api/set_page {w_mm:148,h_mm:210}` → 200 且 `server.PAGE_W_MM==148`；非法(缺字段/非正)→400。先 RED。
- [ ] **Step 4**：实现 `geometry.PAGE_PRESETS`、server 会话 + `/api/set_page` + export 用页尺寸。跑 GREEN。
- [ ] **Step 5**：全套 `pytest tests/ -v` 全绿。
- [ ] **Step 6**：提交 `feat: 后端可变纸张尺寸(exporter page_px + /api/set_page)`。

---

### Task 2: 前端工作区(物理坐标 + 缩放/平移 + 纸框 + fit-view)

**Files:** `web/index.html`, `web/app.js`, `web/style.css`

**要求(无自动化测试，控制器用 preview_eval 数值核验 + 截图)：**
- 画布填充 `#wrap`：`canvas` CSS 宽高 100%，JS 里 `canvas.setWidth/ setHeight` 跟随容器尺寸(并在窗口 resize 时更新)。
- **坐标模型改物理 px**：移除 `VIEW_SCALE` 乘除；`buildGroupSync` 的 subject 图 `scaleX/scaleY=1`(物理)，多边形点用物理 px；`addPart`/`rebuildPart`/`tidy`/`export` 的位置都用物理 px(group.left/top 即物理坐标)。
- **纸框**：创建一个 `fabric.Rect`(left=0,top=0,width=page_w_px,height=page_h_px,fill=#fff,stroke=#cbd5e1,strokeWidth=1/zoom 或固定细线,selectable:false,evented:false,excludeFromExport 概念)，置于最底层(`canvas.sendToBack`)。所有零件在其上。
- **缩放**：`mouse:wheel` → `zoomToPoint(pointer, newZoom)`，clamp [0.1,8]，阻止默认滚动。
- **平移**：按住空格(keydown/keyup 切换 flag)或鼠标中键(button===1)时，`mouse:down→move` 修改 `viewportTransform[4/5]`，禁用对象选择/拖动。
- **fit-view**：函数 `fitView()` 计算包含纸框 + 所有零件的总 bbox(物理)，设 zoom 与 pan 使其居中可见(留边距)；导入完成后调用一次；「适应视图」按钮调用。
- **导入定位**：零件初始散落在**纸框右侧空白工作区**(或框内排开)，物理坐标。
- 顶部加「适应视图」按钮(`btn-fit`)。
- 进度/白边/导出/删除/整理沿用，但坐标改物理 px。
- 切割按钮仍占位。

- [ ] **Step 1**：`index.html` 加 `btn-fit`、纸张尺寸控件(见 Task 3 也会用)。`style.css` 画布填充。
- [ ] **Step 2**：`app.js` 重写坐标模型为物理 px + fabric 缩放/平移 + 纸框 + fitView。
- [ ] **Step 3(控制器验证)**：preview_eval 确认:导入后 `canvas.getObjects()` 含纸框+N 零件；零件 group.left/top 为物理量级(数百~数千);滚轮改 `canvas.getZoom()` 在 [0.1,8];fitView 后纸框可见。截图(若工具可用)。
- [ ] **Step 4**：提交 `feat: 前端工作区(物理坐标+缩放平移+纸框+适应视图)`。

---

### Task 3: 纸张尺寸控件 + 导出框外过滤/提示

**Files:** `web/index.html`, `web/app.js`

**要求：**
- 顶部纸张控件:预设下拉(A4/A3/A5/Letter/自定义) + 宽/高数字输入 + mm/px 单位。改动→更新纸框 `width/height`(物理 px)、调 `POST /api/set_page {w_mm,h_mm}`、零件保持物理坐标不动。选「自定义」时宽高可编辑;选预设时填入预设值。
- **导出**：导出前计算哪些零件**刀模 bbox 不在纸框内**(物理坐标比较);若有,`confirm("有 N 个零件在纸框外，不会被导出，是否继续？")`,取消则中止;继续则**只发送框内零件**给 `/api/export`。
- 导出 PNG 尺寸=当前纸框尺寸(后端已支持)。

- [ ] **Step 1**：`app.js` 纸张控件逻辑(预设/自定义/单位 → 更新纸框 + set_page)。
- [ ] **Step 2**：导出框外过滤 + confirm 提示。
- [ ] **Step 3(控制器验证)**：preview_eval:切换 A4→A5 纸框尺寸变化、零件不动;把一个零件移到框外,导出时触发提示且导出图只含框内。
- [ ] **Step 4**：提交 `feat: 纸张尺寸控件(预设/自定义/mm-px)+导出框外过滤提示`。

---

## 验收
- 滚轮以光标缩放、空格/中键平移、缩放限 10–800%、「适应视图」可用。
- 纸框显示;切换预设/自定义尺寸纸框随变、零件保持位置、超框仍显示。
- 导出 PNG 尺寸=当前纸张;框外零件不导出且有确认提示。
- 全套 pytest 绿。
