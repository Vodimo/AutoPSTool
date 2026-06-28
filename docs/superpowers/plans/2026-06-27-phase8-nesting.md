# Phase 8 · 排版增强(旋转感知 BLF) Implementation Plan

> 执行：subagent-driven。最终阶段。

**Goal:** 紧凑排版升级:锁角零件保持角度只摆位;自由角零件按「精度」试多个角度旋转塞紧;「间距」滑块控制零件间隙;「统一缩放」开关时整体缩放所有零件最大化纸张利用率;排版异步+进度。

## 偏差声明(需用户复核)
spec 原定引擎为 **SVGnest**。因 SVGnest 是与其 demo 强耦合的代码、在本工程内干净集成风险高,本阶段改用**增强版旋转感知 Bottom-Left-Fill**(基于现有 shapely,服务端),达成 Phase 8 的全部功能目标。`nesting` 模块边界不变,未来可把内部换成 SVGnest 而不动调用方/前端。

## 锁定决策
- **坐标契约改中心+角度**:`nest` 返回 `[{id, cx, cy, angle}]`(cx,cy=零件视觉中心物理 px);前端按中心+角度摆放(与导出一致)。
- **碰撞几何**:每个零件的「刀模多边形」按**当前全局白边** offset 由 `border.dieline_polygon(subject_outline, offset_px)` 得到(参数化);固定零件用其 contour。按零件 scale 缩放、按候选角度绕**自身质心**旋转,平移到候选中心。
- **锁角/自由**:前端把每个零件的 `locked` 与当前 `angle` 传给 nest。`locked` 零件只用其当前角度;自由零件试 `angle_steps` 个均匀角度(精度滑块 → 步数,如 1/4/8/12/24)。
- **间距**:`spacing_mm`(间距滑块, mm/px)→ 碰撞用 buffer(spacing_px/2)。
- **统一缩放开关**:`uniform_scale=true` 时,先按面积估全局比例 `s0=sqrt(0.72*页面积/Σ零件面积)`,应用到所有零件后 nest;若有放不下的,`s*=0.85` 最多重试 2 次,取全部放下的最大 s;返回里附 `scale`。`false` 时按各自当前 scale,放不下的 `cx=cy=-1`。
- **异步+进度**:前端排版调用期间 showProgress;后端同步计算(零件数量级小,可接受)。

## Global Constraints
- Python 3.11;`.conda\python.exe -m pytest tests/ -v`;注释中文;提交体末尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

---

### Task 1: 后端旋转感知 BLF(中心+角度, 间距, 统一缩放)

**Files:** `app/nesting.py`(重写)、`app/server.py`(/api/nest 入参/返回)、`tests/test_nesting.py`(重写/补)。

**接口:**
- `nesting.nest(parts, offset_mm=None, spacing_mm=None, angle_steps=8, uniform_scale=False, grid_step=20) -> list[Part]`:
  - 每个 part 读 `part.scale`、`part.rotation`(度)、`part.locked`(bool, 新增到 Part,默认 False)。
  - `_part_poly(part, offset_px) -> shapely.Polygon`:参数化(subject_outline)→`border.dieline_polygon(subject_outline, offset_px)`;否则 `Polygon(part.contour)`。再 `simplify(SIMPLIFY_TOLERANCE_PX)`。此为**未缩放未旋转、原局部坐标**多边形。
  - 候选角度:locked → `[part.rotation]`;自由 → `[k*360/angle_steps for k in range(angle_steps)]`(angle_steps>=1)。
  - 对每个零件(按缩放后面积降序):对每个候选角度,取 `_part_poly`→`scale(s)`→`rotate(angle, origin='centroid')`→得到 footprint;在 A4/页面网格上做 BLF,找使其 `buffer(spacing_px/2)` 不出界、不与已放置相交的**最靠左上**中心位;在所有候选角度里取「最低 y、其次最小 x」者。设 `part.cx,part.cy=中心`、`part.rotation=该角度`(自由件被赋角度)、`part.x,part.y` 也更新(left/top = 中心 - 旋转后 bbox 半宽高,便于兼容)。放不下 → `part.cx=part.cy=-1`。
  - **uniform_scale=True**:按决策估 `s0` 并应用到所有 `part.scale`,nest;若有 -1,`s*=0.85` 重试 ≤2 次;最终用成功的 s。
  - 页面尺寸:用 `g` 里没有会话,故 nest 额外接收 `page_px=(w,h)`,默认 A4。server 传当前会话页尺寸。
  - 返回 parts(原地改 cx/cy/rotation/scale/x/y)。
- `models.Part`:加 `locked: bool = False`。
- `server.api_nest`:items 读 `{id, scale, angle, locked}`;设 `p.scale,p.rotation,p.locked`;读会话(OFFSET_MM, page);可选 body `spacing_mm/angle_steps/uniform_scale`(带默认);`nest(parts, offset_mm=OFFSET_MM, spacing_mm=..., angle_steps=..., uniform_scale=..., page_px=会话页)`;返回 `{positions:[{id, cx, cy, angle, scale}]}`。

**TDD(test_nesting.py 重写为新契约):**
- [ ] `test_nest_centers_within_page`:两个 build_part 零件 nest(angle_steps=1) → 每个 `cx,cy>=0` 且其多边形在页内。
- [ ] `test_nest_no_overlap_centers`:两零件 nest 后,按返回 cx/cy/angle 重建多边形不相交。
- [ ] `test_nest_rotation_helps_fit`:构造一个**细长**零件 + 窄页,使 angle_steps=1(只 0°)放不下而 angle_steps=4(可 90°)能放下(断言后者 placed 更多 / cx>=0)。
- [ ] `test_uniform_scale_fits_more`:多个零件在小页,uniform_scale=True 时全部放下(scale<1)。
- [ ] 全套 pytest 绿。
- [ ] 提交 `feat: 排版增强(旋转感知BLF, 中心+角度, 间距, 统一缩放)`。

---

### Task 2: 前端排版控件 + 应用中心/角度 + 进度

**Files:** `web/index.html`、`web/app.js`。

**要求:**
- 顶部加:**排版精度**滑块(映射 angle_steps: 例 1/4/8/12/24,挡位)、**间距**数字+mm/px、**统一缩放**复选框。
- `btn-tidy`:items 发 `{id, scale:g.scaleX||1, angle:g.angle||0, locked:!!g.locked}` + body `{spacing_mm, angle_steps, uniform_scale}`;showProgress 期间;返回 `positions:[{id,cx,cy,angle,scale}]`:对每个 group `g.set({scaleX:scale,scaleY:scale, angle}); g.setPositionByOrigin(new fabric.Point(cx,cy),'center','center'); g.setCoords();`(cx<0 跳过/留原位)。自由件被赋角度后保持 `locked=false`(蓝框);锁角件不变。排版完成 pushSnapshot()。
- 与 undo 兼容(排版是一次操作,push 一次快照)。
- 进度:排版期间 showProgress/hideProgress。

- [ ] 实现;preview_eval 核验:导入→tidy(angle_steps=8,uniform_scale)→positions 含 cx/cy/angle、group 被摆放且无 JS 错误;精度/间距/统一缩放控件存在。
- [ ] 提交 `feat: 前端排版控件(精度/间距/统一缩放)+应用中心角度+进度`。

---

## 验收
- 整理排版把自由件旋转塞得更紧、锁角件保角度;间距滑块生效;统一缩放开能把放不下的整体缩放放下。
- 排版有进度;与导出/撤销兼容。
- 全套 pytest 绿;既有功能不回归。
