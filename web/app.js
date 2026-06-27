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
const imgElById = new Map();             // id -> 已加载的 HTMLImageElement(只加载一次)

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

// —— 同步由「已缓存图片元素 + 当前 borderPx」构建一个 fabric.Group（无异步、无泄漏）——
// 关键：主体图只加载一次（loadPartImage），改白边只同步重算多边形，避免并发重建堆积。
function buildGroupSync(p) {
  const el = imgElById.get(p.id);
  if (!el) return null;
  if (p.kind === 'parametric') {
    const outline = parseDToPolyline(p.subject_outline);
    const die = bufferOutline(outline, borderPx);   // 物理像素
    if (die.length < 3) return null;
    const minx = die.reduce((a, q) => Math.min(a, q[0]), Infinity);
    const miny = die.reduce((a, q) => Math.min(a, q[1]), Infinity);
    const ringView = die.map(([x, y]) => ({ x: (x - minx) * VIEW_SCALE, y: (y - miny) * VIEW_SCALE }));
    const white = new fabric.Polygon(ringView, { fill: '#fff', stroke: '', selectable: false, evented: false, objectCaching: false });
    const dieLine = new fabric.Polygon(ringView, { fill: '', stroke: '#FF00FF', strokeWidth: 1, selectable: false, evented: false, objectCaching: false });
    const img = new fabric.Image(el, { left: (0 - minx) * VIEW_SCALE, top: (0 - miny) * VIEW_SCALE, scaleX: VIEW_SCALE, scaleY: VIEW_SCALE, selectable: false, evented: false });
    return new fabric.Group([white, img, dieLine], { partId: p.id, cornerSize: 8, transparentCorners: false });
  }
  const img = new fabric.Image(el, { scaleX: VIEW_SCALE, scaleY: VIEW_SCALE, selectable: false, evented: false });
  const children = [img];
  if (p.dieline_path) {
    const ring = parseDToPolyline(p.dieline_path).map(([x, y]) => ({ x: x * VIEW_SCALE, y: y * VIEW_SCALE }));
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

// —— 重建某零件 Group（同步：白边变化时重算多边形，保留位置/缩放/角度；无异步无泄漏）——
function rebuildPart(id) {
  const old = objById.get(id);
  if (!old) return;
  const grp = buildGroupSync(partData.get(id));
  if (!grp) return;
  grp.set({ left: old.left, top: old.top, scaleX: old.scaleX, scaleY: old.scaleY, angle: old.angle });
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
  if (t && t.partId) { objById.delete(t.partId); partData.delete(t.partId); imgElById.delete(t.partId); canvas.remove(t); canvas.discardActiveObject(); canvas.requestRenderAll(); }
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
