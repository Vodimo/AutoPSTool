// 物理像素坐标模型：1mm=10px（与后端 geometry 一致）
// 不再使用 VIEW_SCALE；零件 group.left/top 均为物理像素；
// 显示通过 fabric viewport zoom/pan 控制缩放。
const PIXEL_RATIO = 10;                 // 1mm=10px

// 纸张预设（mm）
const PAGE_PRESETS = {
  A4:     { w: 210, h: 297 },
  A3:     { w: 297, h: 420 },
  A5:     { w: 148, h: 210 },
  Letter: { w: 216, h: 279 },
};

// 当前纸张物理尺寸（px）
let pageWpx = 210 * PIXEL_RATIO;   // 2100
let pageHpx = 297 * PIXEL_RATIO;   // 2970

const canvas = new fabric.Canvas('c', {
  selection: true,
  backgroundColor: '#e2e8f0',   // 中性灰背景，白色纸框更突出
});

const statusEl = document.getElementById('status');
const setStatus = (t) => statusEl.textContent = t;

let borderPx = 20;                       // 当前白边(px，物理像素)，默认 2mm
const objById = new Map();
const partData = new Map();              // id -> 后端返回的零件数据（只增不删，供 undo 重建）
const imgElById = new Map();             // id -> 已加载的 HTMLImageElement（只增不删，供 undo 重建）

// 纸框 Rect（始终置于最底层）
let pageRect = null;

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

// —— 画布尺寸跟随 #wrap 容器 ——
function resizeCanvas() {
  const wrap = document.getElementById('wrap');
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;
  canvas.setWidth(w);
  canvas.setHeight(h);
  canvas.requestRenderAll();
}
window.addEventListener('resize', resizeCanvas);
resizeCanvas();   // 初始化

// —— 纸框：创建/更新 ——
function createPageRect() {
  if (pageRect) {
    canvas.remove(pageRect);
    pageRect = null;
  }
  pageRect = new fabric.Rect({
    left: 0,
    top: 0,
    width: pageWpx,
    height: pageHpx,
    fill: '#ffffff',
    stroke: '#cbd5e1',
    strokeWidth: 1,
    selectable: false,
    evented: false,
    hasControls: false,
    hasBorders: false,
  });
  canvas.add(pageRect);
  canvas.sendToBack(pageRect);
  canvas.requestRenderAll();
}
createPageRect();

// —— fit-view：使纸框+所有零件居中可见（留 5% 边距）——
function fitView() {
  const cw = canvas.getWidth();
  const ch = canvas.getHeight();

  // 计算所有对象在物理坐标下的总包围盒
  let minX = 0, minY = 0, maxX = pageWpx, maxY = pageHpx;
  canvas.getObjects().forEach(obj => {
    if (obj === pageRect) return;
    // absolute=true 返回不含 viewport 的物理坐标包围盒，直接用即可
    const br = obj.getBoundingRect(true);
    minX = Math.min(minX, br.left);
    minY = Math.min(minY, br.top);
    maxX = Math.max(maxX, br.left + br.width);
    maxY = Math.max(maxY, br.top + br.height);
  });

  const bboxW = maxX - minX;
  const bboxH = maxY - minY;
  if (bboxW <= 0 || bboxH <= 0) return;

  const margin = 0.05;   // 5% 边距
  const scaleX = (cw * (1 - 2 * margin)) / bboxW;
  const scaleY = (ch * (1 - 2 * margin)) / bboxH;
  const zoom = Math.max(0.1, Math.min(8, Math.min(scaleX, scaleY)));

  // 使 bbox 中心对准画布中心
  const bboxCx = (minX + maxX) / 2 * zoom;
  const bboxCy = (minY + maxY) / 2 * zoom;
  const panX = cw / 2 - bboxCx;
  const panY = ch / 2 - bboxCy;

  canvas.setZoom(zoom);
  canvas.viewportTransform[4] = panX;
  canvas.viewportTransform[5] = panY;
  canvas.requestRenderAll();
}

// —— 缩放：鼠标滚轮以光标为锚点 ——
canvas.on('mouse:wheel', function (opt) {
  const e = opt.e;
  const delta = e.deltaY;
  let zoom = canvas.getZoom();
  zoom *= Math.pow(0.999, delta);
  zoom = Math.max(0.1, Math.min(8, zoom));
  canvas.zoomToPoint({ x: e.offsetX, y: e.offsetY }, zoom);
  e.preventDefault();
  e.stopPropagation();
});

// —— 平移：空格键 或 中键拖拽 ——
let isPanning = false;
let spaceDown = false;
let panStart = null;

window.addEventListener('keydown', (e) => {
  if (e.code === 'Space' && !e.repeat) {
    spaceDown = true;
    // 阻止空格导致页面滚动
    e.preventDefault();
  }
});
window.addEventListener('keyup', (e) => {
  if (e.code === 'Space') {
    spaceDown = false;
    if (isPanning) {
      isPanning = false;
      canvas.selection = true;
    }
  }
});

canvas.on('mouse:down', function (opt) {
  const e = opt.e;
  // 空格按住 或 中键
  if (spaceDown || e.button === 1) {
    isPanning = true;
    panStart = { x: e.clientX, y: e.clientY };
    canvas.selection = false;
    // 禁止对象被拖拽
    canvas.getObjects().forEach(o => { o.__prevSelectable = o.selectable; o.selectable = false; });
    e.preventDefault();
  }
});

canvas.on('mouse:move', function (opt) {
  if (!isPanning || !panStart) return;
  const e = opt.e;
  const dx = e.clientX - panStart.x;
  const dy = e.clientY - panStart.y;
  panStart = { x: e.clientX, y: e.clientY };
  const vpt = canvas.viewportTransform;
  vpt[4] += dx;
  vpt[5] += dy;
  canvas.requestRenderAll();
  opt.e.preventDefault();
});

canvas.on('mouse:up', function (opt) {
  if (isPanning) {
    isPanning = false;
    if (!spaceDown) canvas.selection = true;
    // 恢复对象可选状态
    canvas.getObjects().forEach(o => {
      if (typeof o.__prevSelectable !== 'undefined') {
        o.selectable = o.__prevSelectable;
        delete o.__prevSelectable;
      }
    });
  }
  panStart = null;
});

// —— SVG path d → 点集（解析 M/L/C，C 取端点折线）——
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

// —— clipper 缓冲：主体轮廓点集 → 向外 offset 的白边/刀模多边形点集（物理 px）——
function bufferOutline(polyline, offsetPx) {
  const SCALE = 100;
  const path = polyline.map(([x, y]) => ({ X: Math.round(x * SCALE), Y: Math.round(y * SCALE) }));
  const co = new ClipperLib.ClipperOffset(2, 0.25 * SCALE);
  co.AddPath(path, ClipperLib.JoinType.jtRound, ClipperLib.EndType.etClosedPolygon);
  const solution = new ClipperLib.Paths();
  co.Execute(solution, offsetPx * SCALE);
  if (!solution.length) return [];
  // 取最大环
  let best = solution[0], bestA = 0;
  for (const p of solution) { const a = Math.abs(ClipperLib.Clipper.Area(p)); if (a > bestA) { bestA = a; best = p; } }
  return best.map(pt => [pt.X / SCALE, pt.Y / SCALE]);
}

// —— 同步由「已缓存图片元素 + 当前 borderPx」构建一个 fabric.Group（物理坐标）——
// 主体图 scaleX/scaleY=1（物理），多边形点用物理 px
function buildGroupSync(p) {
  const el = imgElById.get(p.id);
  if (!el) return null;
  if (p.kind === 'parametric') {
    // 使用后端下发的细采样最外环(subject_poly)
    const outline = p.subject_poly && p.subject_poly.length >= 3
      ? p.subject_poly : parseDToPolyline(p.subject_outline);
    const die = bufferOutline(outline, borderPx);   // 物理像素
    if (die.length < 3) return null;
    const minx = die.reduce((a, q) => Math.min(a, q[0]), Infinity);
    const miny = die.reduce((a, q) => Math.min(a, q[1]), Infinity);
    // 多边形点相对于 group 原点（物理坐标，scaleX/Y=1）
    const ringPts = die.map(([x, y]) => ({ x: x - minx, y: y - miny }));
    const white   = new fabric.Polygon(ringPts, { fill: '#fff', stroke: '', selectable: false, evented: false, objectCaching: false });
    const dieLine = new fabric.Polygon(ringPts, { fill: '', stroke: '#FF00FF', strokeWidth: 1, selectable: false, evented: false, objectCaching: false });
    // 主体图 scaleX/Y=1，left/top 相对 group 原点（物理像素）
    const img = new fabric.Image(el, {
      left: -minx, top: -miny,
      scaleX: 1, scaleY: 1,
      selectable: false, evented: false,
    });
    return new fabric.Group([white, img, dieLine], { partId: p.id, cornerSize: 8, transparentCorners: false });
  }
  // 固定白边模式：image_base64 + dieline_path
  const img = new fabric.Image(el, { scaleX: 1, scaleY: 1, selectable: false, evented: false });
  const children = [img];
  if (p.dieline_path) {
    const ring = parseDToPolyline(p.dieline_path).map(([x, y]) => ({ x, y }));
    if (ring.length >= 2) children.push(new fabric.Polygon(ring, { fill: '', stroke: '#FF00FF', strokeWidth: 1, selectable: false, evented: false, objectCaching: false }));
  }
  return new fabric.Group(children, { partId: p.id, cornerSize: 8, transparentCorners: false });
}

// 加载零件图片元素（每个零件只一次），存入 imgElById
function loadPartImage(p) {
  return new Promise((resolve) => {
    const url = p.kind === 'parametric' ? p.subject_image : p.image_base64;
    fabric.Image.fromURL(url, (img) => { imgElById.set(p.id, img.getElement()); resolve(); }, { crossOrigin: null });
  });
}

// 导入计数器（控制初始散落位置，放在纸框右侧）
let importCounter = 0;

async function addPart(p, x, y) {
  partData.set(p.id, p);
  await loadPartImage(p);
  const grp = buildGroupSync(p);
  if (!grp) return;
  grp.set({ left: x, top: y });
  objById.set(p.id, grp);
  canvas.add(grp);
  canvas.requestRenderAll();
}

// —— 锁角视觉标记：锁角 = 洋红选中框/手柄，自由 = 默认蓝 ——
function markLocked(o) {
  o.locked = true;
  o.set({ borderColor: '#FF00FF', cornerColor: '#FF00FF' });
  canvas.requestRenderAll();
  pushSnapshot();
}
function markFree(o) {
  o.locked = false;
  o.set({ angle: 0, borderColor: 'rgba(102,153,255,0.75)', cornerColor: 'rgba(102,153,255,0.5)' });
  o.setCoords();
  pushSnapshot();
}

// —— 重建某零件 Group（同步：白边变化时重算多边形，保留位置/缩放/角度/锁角）——
function rebuildPart(id) {
  const old = objById.get(id);
  if (!old) return;
  const grp = buildGroupSync(partData.get(id));
  if (!grp) return;
  grp.set({ left: old.left, top: old.top, scaleX: old.scaleX, scaleY: old.scaleY, angle: old.angle });
  // 保留锁角状态：如已锁角则继承洋红标记
  grp.locked = old.locked;
  if (grp.locked) {
    // 内联设置锁角标记，不触发 pushSnapshot（rebuildPart 由 commitBorder 调用）
    grp.set({ borderColor: '#FF00FF', cornerColor: '#FF00FF' });
  }
  canvas.remove(old);
  objById.set(id, grp);
  canvas.add(grp);
  // 确保纸框仍在最底层
  if (pageRect) canvas.sendToBack(pageRect);
}

// ============================================================
// 撤销/重做 快照栈
// ============================================================

const undoStack = [];   // 历史快照（栈顶为最近已提交状态）
const redoStack = [];   // redo 暂存
const UNDO_MAX  = 50;   // 最大栈深

// 生成当前场景快照
function snapshot() {
  const activeIds = [...objById.keys()];
  const tf = {};
  for (const [id, g] of objById.entries()) {
    tf[id] = {
      left:   g.left,
      top:    g.top,
      scaleX: g.scaleX,
      angle:  g.angle || 0,
      locked: !!g.locked,
    };
  }
  return {
    activeIds,
    tf,
    g: {
      borderPx,
      pageWmm: pageWpx / PIXEL_RATIO,
      pageHmm: pageHpx / PIXEL_RATIO,
      bleedMm: getBleedMm(),
    },
  };
}

// 推入快照（每次操作完成后调用）
function pushSnapshot() {
  undoStack.push(snapshot());
  if (undoStack.length > UNDO_MAX) undoStack.shift();
  redoStack.length = 0;   // 新操作后清空 redo 栈
}

// 应用快照：重建场景至 s 描述的状态
async function applySnapshot(s) {
  // 1. 全局参数
  borderPx = s.g.borderPx;
  // 纸张尺寸（如有变化）
  if (pageWpx / PIXEL_RATIO !== s.g.pageWmm || pageHpx / PIXEL_RATIO !== s.g.pageHmm) {
    applyPageSize(s.g.pageWmm, s.g.pageHmm);
  }
  // 出血
  const curBleed = getBleedMm();
  if (Math.abs(curBleed - s.g.bleedMm) > 0.001) {
    // 更新 UI 输入框（按当前单位）
    if (bleedUnit.value === 'px') {
      bleedNum.value = (s.g.bleedMm * PIXEL_RATIO).toFixed(0);
    } else {
      bleedNum.value = s.g.bleedMm.toFixed(2);
    }
    api('/api/set_bleed', { bleed_mm: s.g.bleedMm }).catch(() => {});
  }
  // 白边同步到 UI（range 值 = mm*PIXEL_RATIO，num 按当前单位）
  const borderMm = borderPx / PIXEL_RATIO;
  const rng  = document.getElementById('border-range');
  const num  = document.getElementById('border-num');
  const unit = document.getElementById('border-unit');
  rng.value = Math.min(100, Math.round(borderMm * PIXEL_RATIO));
  num.value = unit.value === 'px' ? (borderMm * PIXEL_RATIO).toFixed(0) : borderMm.toFixed(1);
  api('/api/set_border', { offset_mm: borderMm }).catch(() => {});

  // 2. 活动集：移除不在快照 activeIds 中的 group
  const activeSet = new Set(s.activeIds);
  for (const [id, g] of [...objById.entries()]) {
    if (!activeSet.has(id)) {
      canvas.remove(g);
      objById.delete(id);
    }
  }

  // 添加快照中有、但当前没有的 group（从保留数据重建）
  for (const id of s.activeIds) {
    if (!objById.has(id)) {
      const pd = partData.get(id);
      if (!pd) continue;   // 理论上不会发生：partData 只增不删
      const grp = buildGroupSync(pd);
      if (!grp) continue;
      objById.set(id, grp);
      canvas.add(grp);
    }
  }

  // 3. 应用每个零件 transform
  for (const id of s.activeIds) {
    const g  = objById.get(id);
    const tf = s.tf[id];
    if (!g || !tf) continue;
    g.set({
      left:   tf.left,
      top:    tf.top,
      scaleX: tf.scaleX,
      scaleY: tf.scaleX,   // 等比缩放
      angle:  tf.angle,
    });
    g.setCoords();
    // 锁角标记（内联设置，不触发 pushSnapshot）
    if (tf.locked) {
      g.locked = true;
      g.set({ borderColor: '#FF00FF', cornerColor: '#FF00FF' });
    } else {
      g.locked = false;
      g.set({ borderColor: 'rgba(102,153,255,0.75)', cornerColor: 'rgba(102,153,255,0.5)' });
    }
  }

  // 4. 白边变化时重建参数化零件多边形
  for (const id of s.activeIds) {
    const pd = partData.get(id);
    if (pd && pd.kind === 'parametric') rebuildPartInPlace(id, s.tf[id]);
  }

  // 确保纸框在最底层
  if (pageRect) canvas.sendToBack(pageRect);
  canvas.requestRenderAll();
}

// 重建参数化零件多边形并应用 transform（供 applySnapshot 内部使用，不触发快照）
function rebuildPartInPlace(id, tf) {
  const pd  = partData.get(id);
  const old = objById.get(id);
  if (!pd || !old) return;
  const grp = buildGroupSync(pd);
  if (!grp) return;
  if (tf) {
    grp.set({
      left: tf.left, top: tf.top,
      scaleX: tf.scaleX, scaleY: tf.scaleX,
      angle: tf.angle,
    });
    grp.setCoords();
    if (tf.locked) {
      grp.locked = true;
      grp.set({ borderColor: '#FF00FF', cornerColor: '#FF00FF' });
    } else {
      grp.locked = false;
      grp.set({ borderColor: 'rgba(102,153,255,0.75)', cornerColor: 'rgba(102,153,255,0.5)' });
    }
  }
  canvas.remove(old);
  objById.set(id, grp);
  canvas.add(grp);
  if (pageRect) canvas.sendToBack(pageRect);
}

// 撤销
async function undo() {
  if (undoStack.length < 2) return;   // 保留基线快照
  redoStack.push(undoStack[undoStack.length - 1]);
  undoStack.pop();
  await applySnapshot(undoStack[undoStack.length - 1]);
  setStatus('已撤销');
}

// 重做
async function redo() {
  if (!redoStack.length) return;
  const s = redoStack.pop();
  undoStack.push(s);
  await applySnapshot(s);
  setStatus('已重做');
}

// 快捷键 Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z
window.addEventListener('keydown', (e) => {
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  const ctrl = e.ctrlKey || e.metaKey;
  if (!ctrl) return;
  if (e.key === 'z' || e.key === 'Z') {
    if (e.shiftKey) {
      e.preventDefault(); redo();
    } else {
      e.preventDefault(); undo();
    }
    return;
  }
  if (e.key === 'y' || e.key === 'Y') {
    e.preventDefault(); redo();
  }
});

// 导入图片 -> /api/segment（支持多文件）
document.getElementById('btn-import').onclick = () => document.getElementById('file').click();
document.getElementById('file').onchange = async (e) => {
  const files = Array.from(e.target.files);
  if (!files.length) return;
  setStatus('抠图中…');
  const total = files.length;
  try {
    for (let fileIdx = 0; fileIdx < total; fileIdx++) {
      const f = files[fileIdx];
      showProgress(fileIdx / total);
      const dataUrl = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.readAsDataURL(f);
      });
      const r = await api('/api/segment', { image_base64: dataUrl });
      const { parts } = await r.json();
      showProgress((fileIdx + 0.7) / total);
      let i = 0;
      for (const p of parts) {
        const col = (importCounter + i) % 5;
        const row = Math.floor((importCounter + i) / 5);
        const x = 20 + col * 320;
        const y = 20 + row * 320;
        await addPart(p, x, y);
        i++;
      }
      importCounter += parts.length;
      setStatus(`已导入 ${fileIdx + 1}/${total} 张，分离出 ${parts.length} 个零件`);
      showProgress((fileIdx + 1) / total);
    }
    setStatus(`全部导入完成（共 ${total} 张）`);
    fitView();
    pushSnapshot();
  } catch (err) {
    setStatus('抠图失败: ' + err.message);
  } finally {
    hideProgress();
  }
  e.target.value = '';
};

// —— 白边滑块（mm/px，全局，实时）——
const rng  = document.getElementById('border-range');
const num  = document.getElementById('border-num');
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
num.oninput  = syncFromControls;
unit.onchange = syncFromControls;
// 松手把最终值同步给后端（导出用），并推快照
function commitBorder() {
  const mm = parseFloat(rng.value) / PIXEL_RATIO;
  api('/api/set_border', { offset_mm: mm }).catch(() => {});
  pushSnapshot();
}
rng.onchange  = commitBorder;
num.onchange  = commitBorder;

// —— 纸张尺寸控件 ——
const pagePreset = document.getElementById('page-preset');
const pageWInput = document.getElementById('page-w');
const pageHInput = document.getElementById('page-h');
const pageUnitSel = document.getElementById('page-unit');

// 把 mm 值应用到纸框和后端
function applyPageSize(wMm, hMm) {
  pageWpx = Math.round(wMm * PIXEL_RATIO);
  pageHpx = Math.round(hMm * PIXEL_RATIO);
  if (pageRect) {
    pageRect.set({ width: pageWpx, height: pageHpx });
    pageRect.setCoords();
  }
  canvas.requestRenderAll();
  // 通知后端
  api('/api/set_page', { w_mm: wMm, h_mm: hMm }).catch(() => {});
}

// 从输入框读取当前值并应用，并推快照
function applyPageFromInputs() {
  let w = parseFloat(pageWInput.value) || 210;
  let h = parseFloat(pageHInput.value) || 297;
  if (pageUnitSel.value === 'px') {
    w = w / PIXEL_RATIO;
    h = h / PIXEL_RATIO;
  }
  applyPageSize(w, h);
  pushSnapshot();
}

// 预设下拉切换
pagePreset.onchange = () => {
  const val = pagePreset.value;
  if (val === 'custom') {
    // 自定义：输入框可编辑，不自动填值
    pageWInput.disabled = false;
    pageHInput.disabled = false;
    return;
  }
  const preset = PAGE_PRESETS[val];
  if (!preset) return;
  pageWInput.disabled = false;
  pageHInput.disabled = false;
  // 填入预设值（按当前单位）
  if (pageUnitSel.value === 'mm') {
    pageWInput.value = preset.w;
    pageHInput.value = preset.h;
  } else {
    pageWInput.value = preset.w * PIXEL_RATIO;
    pageHInput.value = preset.h * PIXEL_RATIO;
  }
  pageWInput.disabled = true;
  pageHInput.disabled = true;
  applyPageSize(preset.w, preset.h);
  pushSnapshot();
};

// 单位切换：换算输入框数值
pageUnitSel.onchange = () => {
  const w = parseFloat(pageWInput.value) || 0;
  const h = parseFloat(pageHInput.value) || 0;
  if (pageUnitSel.value === 'px') {
    // 从 mm 切换到 px
    pageWInput.value = Math.round(w * PIXEL_RATIO);
    pageHInput.value = Math.round(h * PIXEL_RATIO);
  } else {
    // 从 px 切换到 mm
    pageWInput.value = (w / PIXEL_RATIO).toFixed(0);
    pageHInput.value = (h / PIXEL_RATIO).toFixed(0);
  }
};

// 宽高输入框修改（自定义模式）
pageWInput.onchange = applyPageFromInputs;
pageHInput.onchange = applyPageFromInputs;

// 初始化：A4 预设，输入框禁用
pageWInput.disabled = true;
pageHInput.disabled = true;

// —— 旋转事件：手动旋转即自动锁角 ——
canvas.on('object:rotating', (e) => {
  const o = e.target;
  if (o && o.partId) {
    // 内联标记（不触发 pushSnapshot，由 object:modified 统一推）
    o.locked = true;
    o.set({ borderColor: '#FF00FF', cornerColor: '#FF00FF' });
    setStatus('已锁角（按 L 解锁归零）');
  }
});
// object:modified 兜底：修改后 angle 非 0 则锁定；所有移动/缩放/旋转完成时推快照
canvas.on('object:modified', (e) => {
  const o = e.target;
  if (o && o.partId) {
    if (o.angle !== 0 && !o.locked) {
      o.locked = true;
      o.set({ borderColor: '#FF00FF', cornerColor: '#FF00FF' });
      setStatus('已锁角（按 L 解锁归零）');
    }
    pushSnapshot();
  }
});

// —— L 键解锁：选中锁角零件 → angle 归 0，恢复蓝色框 ——
window.addEventListener('keydown', (e) => {
  if (e.key === 'l' || e.key === 'L') {
    const o = canvas.getActiveObject();
    if (o && o.partId && o.locked) {
      markFree(o);
      canvas.requestRenderAll();
      setStatus('已解除锁角');
      // markFree 内部已调用 pushSnapshot
    }
  }
});

// —— 导出 PNG -> /api/export（含框外过滤）——
document.getElementById('btn-export').onclick = async () => {
  // 计算所有零件中哪些完全在纸框内（物理坐标比较）
  const allParts = [...objById.values()];
  if (!allParts.length) { setStatus('画布为空'); return; }

  const insideParts = [];
  const outsideParts = [];

  for (const o of allParts) {
    // 获取 group 的物理 bbox（不受 viewport 影响）
    const l = o.left;
    const t = o.top;
    const w = o.getScaledWidth();
    const h = o.getScaledHeight();
    const r = l + w;
    const b = t + h;
    // 判断是否完全在纸框内（含边界）
    if (l >= 0 && t >= 0 && r <= pageWpx && b <= pageHpx) {
      insideParts.push(o);
    } else {
      outsideParts.push(o);
    }
  }

  // 若有框外零件，弹出确认
  if (outsideParts.length > 0) {
    const ok = confirm(`有 ${outsideParts.length} 个零件在纸框外，不会被导出，是否继续？`);
    if (!ok) return;
  }

  if (!insideParts.length) { setStatus('所有零件均在纸框外，无法导出'); return; }

  // 导出发送中心坐标 + 角度（后端据此正确渲染旋转）
  const items = insideParts.map(o => {
    const c = o.getCenterPoint();
    return {
      id: o.partId,
      cx: Math.round(c.x),
      cy: Math.round(c.y),
      angle: o.angle || 0,
      scale: o.scaleX || 1,
    };
  });

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

// —— 删除选中（只移出画布和 objById，保留 partData/imgElById 供 undo 重建）——
document.getElementById('btn-delete').onclick = () => {
  const t = canvas.getActiveObject();
  if (t && t.partId) {
    canvas.remove(t);
    canvas.discardActiveObject();
    objById.delete(t.partId);
    // partData/imgElById 保留，不删
    canvas.requestRenderAll();
    pushSnapshot();
  }
};

// —— 整理排版 -> /api/nest（位置回填，物理坐标）——
document.getElementById('btn-tidy').onclick = async () => {
  const items = [...objById.values()].map(o => ({ id: o.partId, scale: o.scaleX || 1 }));
  if (!items.length) return;
  setStatus('排版中…'); showProgress(0.5);
  try {
    const r = await api('/api/nest', { items });
    const { positions } = await r.json();
    for (const pos of positions) {
      const o = objById.get(pos.id);
      if (!o || pos.x < 0) continue;
      // 后端返回的已是物理坐标，直接赋值
      o.set({ left: pos.x, top: pos.y }); o.setCoords();
    }
    canvas.requestRenderAll(); setStatus('排版完成');
    pushSnapshot();
  } catch (err) { setStatus('排版失败: ' + err.message); }
  finally { hideProgress(); }
};

// —— 适应视图按钮 ——
document.getElementById('btn-fit').onclick = fitView;

// ============================================================
// 切割模式（Phase 5 Task 2）
// ============================================================

// 出血控件：mm/px 互换，调用后端 /api/set_bleed
const bleedNum  = document.getElementById('bleed-num');
const bleedUnit = document.getElementById('bleed-unit');

function getBleedMm() {
  const v = parseFloat(bleedNum.value) || 0;
  return bleedUnit.value === 'px' ? v / PIXEL_RATIO : v;
}
function onBleedChange() {
  const mm = getBleedMm();
  api('/api/set_bleed', { bleed_mm: mm }).catch(() => {});
  pushSnapshot();
}
bleedNum.onchange  = onBleedChange;
bleedUnit.onchange = onBleedChange;

// 切割状态变量
let cutMode = false;            // 是否处于切割模式
let cutDragging = false;        // 当前是否在拖线中
let cutDragTarget = null;       // 拖线命中的 group 对象
let cutLine = null;             // 预览线(fabric.Line)
let cutStart = null;            // 拖线起点（画布物理坐标）

// cutPreview: 当前未确认的切割预览状态
// { origId, pieceIds, x1, y1, x2, y2 }
let cutPreview = null;

// 切割模式：进入/退出
function enterCutMode() {
  cutMode = true;
  document.getElementById('btn-cut').classList.add('active');
  // 禁止所有零件拖拽，但保留可选
  canvas.getObjects().forEach(o => {
    if (o.partId) {
      o.lockMovementX = true;
      o.lockMovementY = true;
    }
  });
  setStatus('切割：选中一个零件，在其上拖一条直线');
}

function exitCutMode() {
  cutMode = false;
  document.getElementById('btn-cut').classList.remove('active');
  cancelCutPreview();
  // 恢复所有零件可拖拽
  canvas.getObjects().forEach(o => {
    if (o.partId) {
      o.lockMovementX = false;
      o.lockMovementY = false;
    }
  });
  // 清除拖线
  if (cutLine) { canvas.remove(cutLine); cutLine = null; }
  cutDragging = false;
  cutDragTarget = null;
  cutStart = null;
  canvas.requestRenderAll();
  setStatus('已退出切割模式');
}

// 取消预览：移除预览件，恢复原件显示（预览件只从 objById 移除，partData/imgElById 保留）
function cancelCutPreview() {
  if (!cutPreview) return;
  // 移除预览件（只从画布和 objById 移除，保留 partData/imgElById）
  for (const pid of cutPreview.pieceIds) {
    const o = objById.get(pid);
    if (o) canvas.remove(o);
    objById.delete(pid);
    // partData/imgElById 保留
  }
  // 恢复原件显示
  const orig = objById.get(cutPreview.origId);
  if (orig) { orig.visible = true; }
  cutPreview = null;
  canvas.requestRenderAll();
}

// 按钮切换切割模式
document.getElementById('btn-cut').onclick = () => {
  if (cutMode) exitCutMode();
  else enterCutMode();
};

// C 键切换切割模式（忽略在输入框中按键的情况）
window.addEventListener('keydown', (e) => {
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  if (e.key === 'c' || e.key === 'C') {
    if (cutMode) exitCutMode();
    else enterCutMode();
  }
});

// Enter 确认切割，Esc 取消预览
window.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && cutPreview) {
    confirmCut();
    return;
  }
  if (e.key === 'Escape') {
    if (cutPreview) {
      cancelCutPreview();
      setStatus('已取消切割');
    } else if (cutMode) {
      exitCutMode();
    }
  }
});

// 拖线：mouse:down（只在 cutMode 且非平移时）
canvas.on('mouse:down', function (opt) {
  if (!cutMode || isPanning) return;
  if (cutPreview) return;  // 有未确认预览时不启动新拖线

  // 确定命中的零件 group
  const target = opt.target;
  if (!target || !target.partId) return;

  // 检查是否旋转 / 锁角
  if (target.locked || Math.abs(target.angle || 0) > 0.5) {
    setStatus('请先按 L 解除该零件的锁角再切割');
    return;
  }

  // 启动拖线
  cutDragging = true;
  cutDragTarget = target;
  const ptr = canvas.getPointer(opt.e);
  cutStart = { x: ptr.x, y: ptr.y };

  // 创建预览线（洋红虚线）
  cutLine = new fabric.Line(
    [cutStart.x, cutStart.y, cutStart.x, cutStart.y],
    {
      stroke: '#FF00FF',
      strokeWidth: 2,
      strokeDashArray: [6, 6],
      selectable: false,
      evented: false,
      excludeFromExport: true,
    }
  );
  canvas.add(cutLine);
  canvas.requestRenderAll();
});

// 拖线：mouse:move
canvas.on('mouse:move', function (opt) {
  if (!cutMode || !cutDragging || !cutLine || isPanning) return;
  const ptr = canvas.getPointer(opt.e);
  cutLine.set({ x2: ptr.x, y2: ptr.y });
  canvas.requestRenderAll();
});

// 拖线：mouse:up → 发起预览请求
canvas.on('mouse:up', async function (opt) {
  if (!cutMode || !cutDragging) return;
  cutDragging = false;

  if (!cutLine || !cutDragTarget || !cutStart) {
    if (cutLine) { canvas.remove(cutLine); cutLine = null; }
    return;
  }

  const ptr = canvas.getPointer(opt.e);
  const sceneEnd = { x: ptr.x, y: ptr.y };

  // 移除预览线
  canvas.remove(cutLine);
  cutLine = null;

  // 端点距离太短则放弃
  const dx = sceneEnd.x - cutStart.x;
  const dy = sceneEnd.y - cutStart.y;
  if (Math.sqrt(dx * dx + dy * dy) < 5) {
    cutDragTarget = null;
    cutStart = null;
    canvas.requestRenderAll();
    setStatus('切割线太短，请重试');
    return;
  }

  const group = cutDragTarget;
  cutDragTarget = null;

  // 画布坐标 → 零件局部物理坐标
  const scaleX = group.scaleX || 1;
  const scaleY = group.scaleY || 1;
  const x1 = (cutStart.x   - group.left) / scaleX;
  const y1 = (cutStart.y   - group.top)  / scaleY;
  const x2 = (sceneEnd.x   - group.left) / scaleX;
  const y2 = (sceneEnd.y   - group.top)  / scaleY;

  const partId = group.partId;
  cutStart = null;

  setStatus('计算切割预览…');
  showProgress(0.5);
  try {
    const r = await api('/api/cut', { id: partId, x1, y1, x2, y2, commit: false });
    const { parts: pieces } = await r.json();
    if (!pieces || pieces.length === 0) {
      setStatus('切割未产生有效分块，请调整切割线');
      return;
    }

    // 隐藏原件
    group.visible = false;
    canvas.requestRenderAll();

    // 计算两块的错开位置（一左一右各偏移半个白边+10px）
    const spread = borderPx + 10;
    const offsetsX = [-spread, spread];
    const pieceIds = [];

    for (let i = 0; i < pieces.length; i++) {
      const piece = pieces[i];
      const ox = group.left + (offsetsX[i] || 0);
      const oy = group.top;
      await addPart(piece, ox, oy);
      // 切割预览件锁拖拽
      const po = objById.get(piece.id);
      if (po) { po.lockMovementX = true; po.lockMovementY = true; }
      pieceIds.push(piece.id);
    }

    cutPreview = { origId: partId, pieceIds, x1, y1, x2, y2 };
    setStatus('Enter 确认 / Esc 取消');
  } catch (err) {
    // 恢复原件可见
    group.visible = true;
    canvas.requestRenderAll();
    setStatus('切割预览失败: ' + err.message);
  } finally {
    hideProgress();
  }
});

// 确认切割
async function confirmCut() {
  if (!cutPreview) return;
  const { origId, pieceIds, x1, y1, x2, y2 } = cutPreview;

  // 记录两块在画布上的当前位置（供重新 addPart 时复用）
  const previewPositions = pieceIds.map(pid => {
    const o = objById.get(pid);
    return o ? { left: o.left, top: o.top } : { left: 0, top: 0 };
  });

  // 移除预览件（只从画布和 objById 移除，保留 partData/imgElById）
  for (const pid of pieceIds) {
    const o = objById.get(pid);
    if (o) canvas.remove(o);
    objById.delete(pid);
    // partData/imgElById 保留
  }

  setStatus('提交切割…');
  showProgress(0.5);
  try {
    const r = await api('/api/cut', { id: origId, x1, y1, x2, y2, commit: true });
    const { parts: pieces } = await r.json();

    // 移除原件（只从画布和 objById 移除，保留 partData/imgElById）
    const orig = objById.get(origId);
    if (orig) canvas.remove(orig);
    objById.delete(origId);
    // partData/imgElById 保留

    cutPreview = null;

    // 加入真正的两块零件
    for (let i = 0; i < pieces.length; i++) {
      const piece = pieces[i];
      const pos = previewPositions[i] || { left: 0, top: 0 };
      await addPart(piece, pos.left, pos.top);
    }

    canvas.requestRenderAll();
    setStatus('切割完成');
    pushSnapshot();
  } catch (err) {
    // 恢复原件
    const orig = objById.get(origId);
    if (orig) { orig.visible = true; canvas.requestRenderAll(); }
    cutPreview = null;
    setStatus('切割提交失败: ' + err.message);
  } finally {
    hideProgress();
  }
}

// ============================================================
// 修补画笔模式（Phase 6 Task 2）
// ============================================================

// 笔刷大小标签同步
const brushSizeEl  = document.getElementById('brush-size');
const brushSizeLbl = document.getElementById('brush-size-label');
brushSizeEl.oninput = () => { brushSizeLbl.textContent = brushSizeEl.value; };

// 修补模式状态变量
let brushMode     = false;   // 是否处于修补画笔模式
let brushPainting = false;   // 当前是否正在涂抹（mouse down 中）
let brushTarget   = null;    // 正在涂抹的 group 对象
let brushCanvas   = null;    // 离屏 canvas（subject_image 像素尺寸）
let brushCtx      = null;    // 对应 2D 上下文
let brushOverlays = [];      // 临时叠加的 fabric.Circle 预览对象

// 进入修补画笔模式
function enterBrushMode() {
  // 若处于切割模式，先退出
  if (cutMode) exitCutMode();
  brushMode = true;
  document.getElementById('btn-brush').classList.add('active');
  // 锁住所有零件拖拽（和 cutMode 一样）
  canvas.getObjects().forEach(o => {
    if (o.partId) { o.lockMovementX = true; o.lockMovementY = true; }
  });
  // 禁止框选
  canvas.selection = false;
  setStatus('修补：选中一个零件，在其上涂抹（加/擦）');
}

// 退出修补画笔模式
function exitBrushMode() {
  brushMode = false;
  document.getElementById('btn-brush').classList.remove('active');
  // 恢复零件拖拽
  canvas.getObjects().forEach(o => {
    if (o.partId) { o.lockMovementX = false; o.lockMovementY = false; }
  });
  canvas.selection = true;
  // 清除状态
  brushPainting = false;
  brushTarget   = null;
  brushCanvas   = null;
  brushCtx      = null;
  clearBrushOverlays();
  setStatus('已退出修补模式');
}

// 清除画布上的笔迹预览圆点
function clearBrushOverlays() {
  for (const o of brushOverlays) canvas.remove(o);
  brushOverlays = [];
  canvas.requestRenderAll();
}

// 「修补」按钮切换
document.getElementById('btn-brush').onclick = () => {
  if (brushMode) exitBrushMode();
  else enterBrushMode();
};

// B 键切换（忽略在输入框中按键）
window.addEventListener('keydown', (e) => {
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  if (e.key === 'b' || e.key === 'B') {
    if (brushMode) exitBrushMode();
    else enterBrushMode();
  }
});

// Esc 退出修补模式
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && brushMode && !brushPainting) {
    exitBrushMode();
  }
});

// 计算 subject_image 像素坐标（场景物理坐标 → subject_image px）
// group._objects = [white(0), img(1), dieLine(2)]（参数化）；img.left = -minx（die bbox 左偏移）
function sceneToSubjectPx(group, sceneX, sceneY) {
  const pd  = partData.get(group.partId);
  if (!pd) return null;
  // group 内 img 的 left/top（subject_image 在 group 内位置 = -minx, -miny）
  const objs = group._objects;
  // 参数化 group 的 image 子对象在索引 1
  const imgChild = objs && objs.length >= 2 ? objs[1] : null;
  if (!imgChild) return null;
  // subject_image 左上角在场景（物理）坐标：
  const scaleX = group.scaleX || 1;
  const scaleY = group.scaleY || 1;
  const subjOriginX = group.left + imgChild.left * scaleX;
  const subjOriginY = group.top  + imgChild.top  * scaleY;
  const px = (sceneX - subjOriginX) / scaleX;
  const py = (sceneY - subjOriginY) / scaleY;
  // 边界钳位
  const w  = pd.w || 0;
  const h  = pd.h || 0;
  return {
    x: Math.max(0, Math.min(w, px)),
    y: Math.max(0, Math.min(h, py)),
    w,
    h,
  };
}

// 在离屏 canvas 上画一个白色圆点（笔迹记录）
function paintDot(px, py) {
  if (!brushCtx) return;
  const r = parseInt(brushSizeEl.value, 10) / 2;
  brushCtx.beginPath();
  brushCtx.arc(px, py, r, 0, Math.PI * 2);
  brushCtx.fillStyle = '#ffffff';
  brushCtx.fill();
}

// 在主画布上添加半透明预览圆（green/red）
function addOverlayDot(sceneX, sceneY, group) {
  const mode   = document.getElementById('brush-mode').value;
  const color  = mode === 'add' ? 'rgba(0,200,0,0.4)' : 'rgba(220,0,0,0.4)';
  const radius = (parseInt(brushSizeEl.value, 10) / 2) * (group.scaleX || 1);
  const dot = new fabric.Circle({
    left: sceneX - radius,
    top:  sceneY - radius,
    radius,
    fill: color,
    selectable: false,
    evented: false,
    excludeFromExport: true,
    objectCaching: false,
  });
  canvas.add(dot);
  brushOverlays.push(dot);
}

// mouse:down — 修补画笔
canvas.on('mouse:down', function (opt) {
  if (!brushMode || isPanning) return;

  const target = opt.target;
  // 必须命中一个零件 group（参数化）
  if (!target || !target.partId) {
    setStatus('修补：请先点选一个零件，再涂抹');
    return;
  }
  const pd = partData.get(target.partId);
  if (!pd || pd.kind !== 'parametric') {
    setStatus('修补：仅支持参数化零件');
    return;
  }

  // 初始化离屏 canvas（subject_image 原生像素尺寸）
  brushTarget = target;
  brushCanvas = document.createElement('canvas');
  brushCanvas.width  = pd.w;
  brushCanvas.height = pd.h;
  brushCtx = brushCanvas.getContext('2d');
  brushPainting = true;

  const ptr = canvas.getPointer(opt.e);
  const sp  = sceneToSubjectPx(target, ptr.x, ptr.y);
  if (sp) {
    paintDot(sp.x, sp.y);
    addOverlayDot(ptr.x, ptr.y, target);
    canvas.requestRenderAll();
  }
});

// mouse:move — 修补画笔
canvas.on('mouse:move', function (opt) {
  if (!brushMode || !brushPainting || isPanning) return;
  const ptr = canvas.getPointer(opt.e);
  const sp  = sceneToSubjectPx(brushTarget, ptr.x, ptr.y);
  if (sp) {
    paintDot(sp.x, sp.y);
    addOverlayDot(ptr.x, ptr.y, brushTarget);
    canvas.requestRenderAll();
  }
});

// mouse:up — 修补画笔：提交笔迹到后端，替换零件
canvas.on('mouse:up', async function (opt) {
  if (!brushMode || !brushPainting) return;
  brushPainting = false;

  if (!brushCanvas || !brushTarget) {
    clearBrushOverlays();
    return;
  }

  const group  = brushTarget;
  const partId = group.partId;
  brushTarget  = null;

  // 记录原始位置（替换后首件放回原位）
  const origLeft = group.left;
  const origTop  = group.top;

  // 导出笔迹为 PNG data-url（白色笔迹=涂抹区）
  const stroke_b64 = brushCanvas.toDataURL('image/png');
  brushCanvas = null;
  brushCtx    = null;

  // 清除预览圆点
  clearBrushOverlays();

  const mode = document.getElementById('brush-mode').value;
  setStatus('修补处理中…');
  showProgress(0.5);
  try {
    const r = await api('/api/brush', { id: partId, stroke_b64, mode });
    const { parts } = await r.json();

    // 移除原件（只从画布和 objById 移除，保留 partData/imgElById）
    const orig = objById.get(partId);
    if (orig) canvas.remove(orig);
    objById.delete(partId);
    // partData/imgElById 保留

    if (!parts || parts.length === 0) {
      setStatus('修补后无剩余主体（全部擦除）');
      canvas.requestRenderAll();
      pushSnapshot();
      return;
    }

    // addPart 每个返回零件：首件放原位，后续向右各偏移 40px
    for (let i = 0; i < parts.length; i++) {
      const px = origLeft + i * 40;
      const py = origTop;
      await addPart(parts[i], px, py);
    }

    if (pageRect) canvas.sendToBack(pageRect);
    canvas.requestRenderAll();
    setStatus(`修补完成，产出 ${parts.length} 个零件`);
    pushSnapshot();
  } catch (err) {
    setStatus('修补失败: ' + err.message);
  } finally {
    hideProgress();
  }
});

// 初始 fit-view（仅纸框）并推基线快照（使最早的导入也可撤销）
fitView();
pushSnapshot();
