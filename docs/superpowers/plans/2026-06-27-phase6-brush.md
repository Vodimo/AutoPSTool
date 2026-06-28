# Phase 6 · 手动修补画笔 Implementation Plan

> 执行：subagent-driven。范围:抠图手动修补(加/擦 mask)+ 擦断分裂。不碰 undo(Phase7)、nesting(Phase8)。

**Goal:** 选中一个零件,用**加/擦画笔**在它上面涂抹修正抠图(少扣→加回、多扣→擦掉);松手后重算白边/刀模;若擦断使 mask 分成多块,**分裂成多个零件**。画笔大小可调。

## 锁定决策
- **统一坐标帧**:`subject_image`、`source_bgr`、`edit_mask` 三者同帧 = 「主体 bbox + 边距 M(=60px)」,使前端能在 `subject_image` 像素系作画、后端用 server 端 `source_bgr` 取色「加」。
  - `build_part` 改:`subject_image` 由"紧贴主体 bbox"改为"主体 bbox 外扩 M 的 padded 帧"(alpha=mask);新增 `Part.source_bgr`(同帧 BGR 原色)、`Part.edit_mask`(同帧 0/255)。`subject_outline` 仍 = `vz.trace_mask(edit_mask)`(同帧坐标)。
- **画笔后端**:`POST /api/brush {id, stroke_b64, mode}` —— `stroke_b64`=与 `subject_image` 同尺寸的笔迹掩膜 PNG(白=涂抹处);`mode`∈{add,erase}。应用:`add`→`edit_mask|=stroke`;`erase`→`edit_mask&=~stroke`。重算:`clean_edges`→`separate_components`(min_area 过滤碎屑);**每个连通分量产出一个零件**(source_bgr+该分量 mask → 新 subject_image/outline/poly,新 id),替换 PARTS 中原件,返回 `{parts:[...]}`(可能 1 或多块,实现分裂)。
- **前端画笔**:`B` 键 / 「修补」按钮 进/出画笔模式;子模式 加(默认)/擦 切换;画笔大小滑块。画笔模式下禁止拖动/选区;在选中零件的 `subject_image` 区域涂抹(屏幕→subject_image 像素换算),松手把笔迹栅格化成同尺寸掩膜发后端,用返回的零件替换。
- **重算白边/刀模**:返回的零件是参数化(有 subject_outline)→ 前端按当前 borderPx 重建 group。

## Global Constraints
- Python 3.11;`.conda\python.exe -m pytest tests/ -v`;注释中文;提交体末尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- `cv_helpers` 有 clean_edges/separate_components/fill_holes/dilate_mask。

---

### Task 1: 后端画笔(统一帧 + apply + 重算 + 分裂)

**Files:** `app/models.py`(Part 加 source_bgr/edit_mask)、`app/part_builder.py`(build_part 改 padded 主体帧 + 新增 `apply_brush`)、`app/server.py`(/api/brush)、`tests/test_part_builder.py`、`tests/test_server.py`。

**要求:**
- `Part` 加 `source_bgr: "np.ndarray | None" = None`、`edit_mask: "np.ndarray | None" = None`。
- `build_part`:`SUBJECT_MARGIN = 60`。把"紧贴主体 bbox 的 subject_image"改为外扩 M 的 padded 帧:取 `sx,sy,sw,sh=boundingRect(msk)`;padded 帧 = `[sy-M:sy+sh+M, sx-M:sx+sw+M]`(在已 pad 的 img/msk 上,注意 build_part 顶部已 `copyMakeBorder(pad)`,M 应 ≤ pad 或额外再 pad;简单做法:把顶部 `pad` 增到 `max(offset_px+4, M)`,再用 M 外扩裁剪并对越界 clamp)。`source_bgr` = 该帧 BGR(全色,未掩膜);`edit_mask` = 该帧 0/255 mask;`subject_image` = 该帧 RGBA(alpha=edit_mask);`subject_outline = vz.trace_mask(edit_mask)`。其余(image_layer/mask/dieline_path/contour)不变。
- `part_builder.apply_brush(part, stroke_mask, mode) -> list[Part]`:`stroke_mask` 同 `edit_mask` 尺寸 0/255;`em = part.edit_mask.copy()`;`add`→`em=cv2.bitwise_or(em,stroke)`;`erase`→`em=cv2.bitwise_and(em, cv2.bitwise_not(stroke))`;`em=ch.clean_edges(em)`;`comps=ch.separate_components(em, min_area=800)`;对每个分量 `c`:由 `part.source_bgr` + `c` 产出一个参数化零件(复用一个内部 helper `_part_from_source(source_bgr, comp_mask, part_id)`:subject_image=source masked、source_bgr=source、edit_mask=comp、subject_outline=trace(comp)、并按默认 offset 生成 image_layer/mask/dieline_path——可直接 `build_part(source_bgr, comp_mask)` 复用!但 build_part 会再外扩 M 帧,坐标会变,无妨,前端用返回值重建)。**实现优先用 `build_part(part.source_bgr, comp_mask)` 复用**(comp_mask 在 source 帧)。返回所有分量零件(≥1)。若无分量(全擦没)返回 []。

**TDD:**
- [ ] `test_part_builder.py`::`test_build_part_has_source_and_editmask`:build_part 后 `part.source_bgr is not None and part.edit_mask is not None and part.edit_mask.shape[:2]==part.subject_image.shape[:2]`。
- [ ] `test_apply_brush_erase_split`:造一个"哑铃"mask(两圆 + 细桥)build_part;构造 stroke 覆盖桥;`apply_brush(part, stroke, 'erase')` 返回 **2** 个零件。`test_apply_brush_add`:erase 一块后再 add 回,零件面积增大。RED→GREEN。
- [ ] `test_server.py`::`test_brush_endpoint`:segment 得 part;POST `/api/brush {id, stroke_b64, mode:'erase'}`(stroke 为同尺寸全黑/含一笔的 PNG base64)→200 返回 parts、PARTS 更新。
- [ ] 全套 pytest 绿。
- [ ] 提交 `feat: 后端手动修补画笔(统一帧+apply_brush加擦+连通分裂)+/api/brush`。

---

### Task 2: 前端画笔交互

**Files:** `web/index.html`(修补按钮+大小滑块+加/擦)、`web/app.js`。

**要求:**
- `B` 键 / 「修补」按钮 切换 brushMode;子控件:加/擦(默认加)、画笔大小(px)滑块。
- brushMode 下:禁止拖动/选区(像 cutMode);需先选中一个零件。
- 在选中零件的 `subject_image` 区域涂抹:`mouse:down/move` 在一个**离屏 canvas**(尺寸=该零件 subject_image 像素尺寸)上按画笔大小画白色圆点轨迹(屏幕坐标→subject_image 像素:减 group 左上、按 group.scaleX 与 subject_image 在 group 内偏移换算);同时在主画布上叠加半透明绿(加)/红(擦)预览笔迹。
- `mouse:up`:把离屏 canvas 导出为 PNG base64 作 stroke,POST `/api/brush {id, stroke_b64, mode}`;用返回的零件**替换**原零件(删原 group/数据,addPart 每个返回零件到原位置附近),清预览。
- subject_image 像素尺寸:前端需知道——后端 part_to_dict 已发 `w,h`(=subject_image 尺寸),用它建离屏 canvas。group 内 subject_image 的偏移:参数化 group 里 image 的 left/top = `-minx,-miny`(白边偏移);换算时考虑。**简化**:可直接让画笔在 group-local 坐标涂抹,再平移到 subject_image 帧(两者差一个 (minx,miny) 偏移,可由 borderPx 缓冲推算;若复杂,退而用 subject_image 的 group 内 bounding 求偏移)。

- [ ] 实现;preview_eval 核验:选中零件→构造一个 stroke base64(全尺寸含一块白)→fetch `/api/brush` 得 parts→canvas 替换。
- [ ] 提交 `feat: 前端修补画笔(加/擦/大小, 涂抹→/api/brush→替换零件)`。

---

## 验收
- 选中零件涂「擦」掉多余/擦断桥→零件更新或分裂成多块;「加」涂回缺失区域(用原图色)。
- 画笔大小可调;加/擦切换。
- 修补后白边/刀模按当前白边重算正确。
- 全套 pytest 绿;既有功能不回归。
