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
  fireMiddleClick: true,        // fabric 默认不派发中键事件，开启后中键拖拽平移才生效
});
// 阻止中键默认行为（浏览器自动滚动圆点），否则平移被劫持
canvas.upperCanvasEl.addEventListener('mousedown', (e) => { if (e.button === 1) e.preventDefault(); });
canvas.upperCanvasEl.addEventListener('auxclick', (e) => { if (e.button === 1) e.preventDefault(); });
// 缩放始终锁宽高比（spec：拖角等比缩放）
canvas.uniformScaling = true;
// 原型级隐藏中边手柄：覆盖单零件、多选 ActiveSelection、以及一切重建路径。
// 中边拖出的非等比缩放会与只按 scaleX 处理的快照/排版/导出不一致而变形
fabric.Object.prototype._controlsVisibility = { ml: false, mr: false, mt: false, mb: false };

// 视图缩放范围（支持超大自定义纸张也能"适应视图"看全）
const ZOOM_MIN = 0.02, ZOOM_MAX = 8;

// —— 模式提示横幅 ——
// 显示/隐藏会改变 #wrap 高度，必须同步画布尺寸与 fabric 偏移，否则命中检测错位
const modeBanner = document.getElementById('mode-banner');
function showBanner(text) {
  modeBanner.textContent = text;
  modeBanner.style.display = 'block';
  resizeCanvas();
  canvas.calcOffset();
}
function hideBanner() {
  modeBanner.style.display = 'none';
  resizeCanvas();
  canvas.calcOffset();
}

const statusEl = document.getElementById('status');
const setStatus = (t) => statusEl.textContent = t;

let borderPx = 20;                       // 当前白边(px，物理像素)，默认 2mm
let smoothIters = 0;                     // 描边平滑迭代数(Chaikin，0=不平滑)，与后端 /api/set_smooth 同步
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
  const zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.min(scaleX, scaleY)));

  // 使 bbox 中心对准画布中心
  const bboxCx = (minX + maxX) / 2 * zoom;
  const bboxCy = (minY + maxY) / 2 * zoom;
  const panX = cw / 2 - bboxCx;
  const panY = ch / 2 - bboxCy;

  // 用 setViewportTransform 整体设置：会重算所有对象的命中坐标(oCoords)。
  // 直接改 viewportTransform 数组会使命中检测用旧坐标 → 点 A 选中 B
  canvas.setViewportTransform([zoom, 0, 0, zoom, panX, panY]);
  canvas.requestRenderAll();
}

// —— 缩放：鼠标滚轮以光标为锚点 ——
canvas.on('mouse:wheel', function (opt) {
  const e = opt.e;
  const delta = e.deltaY;
  let zoom = canvas.getZoom();
  zoom *= Math.pow(0.999, delta);
  zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, zoom));
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
    // 焦点在表单控件上时不劫持空格（否则无法在输入框输入/触发按钮）
    const tag = document.activeElement && document.activeElement.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || tag === 'BUTTON') return;
    spaceDown = true;
    // 空格按下即全局跳过对象命中：fabric 在派发 mouse:down 之前就会开始
    // 拖拽命中的对象——事后取消 selectable 已太迟，会出现零件被拖走/抖动
    canvas.skipTargetFind = true;
    canvas.selection = false;
    canvas.defaultCursor = 'grab';
    // 阻止空格导致页面滚动
    e.preventDefault();
  }
});
window.addEventListener('keyup', (e) => {
  if (e.code === 'Space') {
    spaceDown = false;
    canvas.skipTargetFind = false;
    canvas.defaultCursor = 'default';
    if (!cutMode && !brushMode) canvas.selection = true;
    if (isPanning) isPanning = false;
  }
});

canvas.on('mouse:down', function (opt) {
  const e = opt.e;
  // 空格按住 或 中键
  if (spaceDown || e.button === 1) {
    isPanning = true;
    panStart = { x: e.clientX, y: e.clientY };
    e.preventDefault();
  }
});

canvas.on('mouse:move', function (opt) {
  if (!isPanning || !panStart) return;
  const e = opt.e;
  const dx = e.clientX - panStart.x;
  const dy = e.clientY - panStart.y;
  panStart = { x: e.clientX, y: e.clientY };
  // setViewportTransform 会重算对象命中坐标，直接改数组会导致平移后点选错位
  const vpt = canvas.viewportTransform.slice();
  vpt[4] += dx;
  vpt[5] += dy;
  canvas.setViewportTransform(vpt);
  canvas.requestRenderAll();
  opt.e.preventDefault();
});

canvas.on('mouse:up', function (opt) {
  if (isPanning) {
    isPanning = false;
    // 中键平移结束（空格平移由 keyup 统一恢复状态）
    if (!spaceDown && !cutMode && !brushMode) canvas.selection = true;
  }
  panStart = null;
});

// —— SVG path d → 点集（解析 M/L/C，C 取端点折线）——
function parseDToPolyline(d) {
  const pts = [];
  const re = /([MLC])([^MLCZ]*)/gi;
  let m;
  while ((m = re.exec(d))) {
    // 支持科学计数法（svgpathtools 输出的极小坐标可能带 e 指数）
    const nums = (m[2].match(/-?\d*\.?\d+(?:e[+-]?\d+)?/gi) || []).map(Number);
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

// —— 切割半平面裁剪（与后端 border.halfplane_polygon 同几何）——
// plane=[x1,y1,x2,y2]，保留侧 = 法线 n=(-dy,dx)/L 指向侧；边界就是切割线本身
const CLIP_SCALE = 100;
const _toPath = (pts) => pts.map(([x, y]) => ({ X: Math.round(x * CLIP_SCALE), Y: Math.round(y * CLIP_SCALE) }));
const _fromPath = (p) => p.map(pt => [pt.X / CLIP_SCALE, pt.Y / CLIP_SCALE]);
function _largestPath(sol, fallback) {
  if (!sol || !sol.length) return fallback;
  let best = sol[0], bestA = 0;
  for (const p of sol) { const a = Math.abs(ClipperLib.Clipper.Area(p)); if (a > bestA) { bestA = a; best = p; } }
  return _fromPath(best);
}
function _halfplaneQuad(plane) {
  const [x1, y1, x2, y2] = plane;
  const dx = x2 - x1, dy = y2 - y1;
  const L = Math.hypot(dx, dy) || 1;
  const ux = dx / L, uy = dy / L, nx = -uy, ny = ux;
  const E = 20000;   // 远大于零件尺寸即可（clipper 整数域安全）
  return [
    [x1 - ux * E, y1 - uy * E],
    [x2 + ux * E, y2 + uy * E],
    [x2 + ux * E + nx * E, y2 + uy * E + ny * E],
    [x1 - ux * E + nx * E, y1 - uy * E + ny * E],
  ];
}
// 按切割平面裁剪刀模：刀模线正好落在切割线上，切口平直、两端锋利
function clipToHalfplane(ring, plane) {
  const c = new ClipperLib.Clipper();
  c.AddPath(_toPath(ring), ClipperLib.PolyType.ptSubject, true);
  c.AddPath(_toPath(_halfplaneQuad(plane)), ClipperLib.PolyType.ptClip, true);
  const sol = new ClipperLib.Paths();
  c.Execute(ClipperLib.ClipType.ctIntersection, sol,
            ClipperLib.PolyFillType.pftNonZero, ClipperLib.PolyFillType.pftNonZero);
  return _largestPath(sol, ring);
}

// —— 把主体图裁剪到刀模区（离屏 canvas）——
// 切割块的主体图是沿切线的像素级截断，可能微溢出刀模多边形，裁掉以免露在刀模线外
function clipImageToRing(el, ring) {
  const c = document.createElement('canvas');
  c.width = el.width || el.naturalWidth;
  c.height = el.height || el.naturalHeight;
  const ctx = c.getContext('2d');
  ctx.beginPath();
  ctx.moveTo(ring[0][0], ring[0][1]);
  for (let i = 1; i < ring.length; i++) ctx.lineTo(ring[i][0], ring[i][1]);
  ctx.closePath();
  ctx.clip();
  ctx.drawImage(el, 0, 0);
  return c;
}

// —— Douglas-Peucker 简化（与后端 shapely simplify 等效，同容差保持同形）——
// 平滑前先简化：把轮廓上细碎抖动合并成长边，Chaikin 再把长边交角切圆，
// 才能得到大弧顺滑的效果；只 Chaikin 不简化时细抖动会被保留成"弯弯折折"。
function rdpSimplify(pts, tol) {
  if (pts.length < 4) return pts;
  const sqTol = tol * tol;
  const sqSegDist = (p, a, b) => {
    let x = a[0], y = a[1], dx = b[0] - x, dy = b[1] - y;
    if (dx !== 0 || dy !== 0) {
      const t = ((p[0] - x) * dx + (p[1] - y) * dy) / (dx * dx + dy * dy);
      if (t > 1) { x = b[0]; y = b[1]; }
      else if (t > 0) { x += dx * t; y += dy * t; }
    }
    dx = p[0] - x; dy = p[1] - y;
    return dx * dx + dy * dy;
  };
  const keep = new Uint8Array(pts.length);
  keep[0] = keep[pts.length - 1] = 1;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [first, last] = stack.pop();
    let maxSq = 0, idx = -1;
    for (let i = first + 1; i < last; i++) {
      const sq = sqSegDist(pts[i], pts[first], pts[last]);
      if (sq > maxSq) { maxSq = sq; idx = i; }
    }
    if (maxSq > sqTol && idx > 0) {
      keep[idx] = 1;
      stack.push([first, idx], [idx, last]);
    }
  }
  const out = [];
  for (let i = 0; i < pts.length; i++) if (keep[i]) out.push(pts[i]);
  return out.length >= 3 ? out : pts;
}

// —— Chaikin 切角平滑（与后端 border.smooth_ring 同算法，保证碰撞/渲染同形）——
function chaikinSmooth(ring, iterations) {
  let pts = ring;
  for (let k = 0; k < iterations; k++) {
    if (pts.length < 3) break;
    const out = [];
    const n = pts.length;
    for (let i = 0; i < n; i++) {
      const [x0, y0] = pts[i];
      const [x1, y1] = pts[(i + 1) % n];
      out.push([0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1]);
      out.push([0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1]);
    }
    pts = out;
  }
  return pts;
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
    let die = bufferOutline(outline, borderPx);   // 物理像素
    if (die.length < 3) return null;
    if (smoothIters > 0) {
      // 与后端 border.dieline_polygon 完全一致：先按档位简化再 Chaikin 切角
      die = chaikinSmooth(rdpSimplify(die, 0.8 + 0.6 * smoothIters), smoothIters);
    }
    // 切割块：刀模与各半平面求交 → 刀模线正好落在切割线上，切口平直
    let imgSrc = el;
    if (p.cut_planes && p.cut_planes.length) {
      for (const plane of p.cut_planes) die = clipToHalfplane(die, plane);
      if (die.length < 3) return null;
      imgSrc = clipImageToRing(el, die);
    }
    const minx = die.reduce((a, q) => Math.min(a, q[0]), Infinity);
    const miny = die.reduce((a, q) => Math.min(a, q[1]), Infinity);
    // 多边形点相对于 group 原点（物理坐标，scaleX/Y=1）
    const ringPts = die.map(([x, y]) => ({ x: x - minx, y: y - miny }));
    const white   = new fabric.Polygon(ringPts, { fill: '#fff', stroke: '', selectable: false, evented: false, objectCaching: false });
    const dieLine = new fabric.Polygon(ringPts, { fill: '', stroke: '#FF00FF', strokeWidth: 1, selectable: false, evented: false, objectCaching: false });
    // 主体图 scaleX/Y=1，left/top 相对 group 原点（物理像素）
    const img = new fabric.Image(imgSrc, {
      left: -minx, top: -miny,
      scaleX: 1, scaleY: 1,
      selectable: false, evented: false,
    });
    const grp = new fabric.Group([white, img, dieLine], {
      partId: p.id, cornerSize: 8, transparentCorners: false,
      // 逐像素命中：主体图带 60px 透明边距，默认矩形命中会点空白误选零件
      perPixelTargetFind: true,
    });
    // 组包围盒左上 → 主体帧原点的偏移（切割坐标换算用）：
    // 白边小于主体边距时组包围盒=主体图（偏移 0）；白边更大时=刀模包围盒（偏移=minx-0.5，含描边半宽）
    grp.frameOffX = Math.min(0, minx - 0.5);
    grp.frameOffY = Math.min(0, miny - 0.5);
    // 刀模环（主体帧坐标）：导出框内判定用（组 bbox 含透明主体图边距会偏大）
    grp.dieRingF = die;
    return grp;
  }
  // 固定白边模式：image_base64 + dieline_path
  const img = new fabric.Image(el, { scaleX: 1, scaleY: 1, selectable: false, evented: false });
  const children = [img];
  if (p.dieline_path) {
    const ring = parseDToPolyline(p.dieline_path).map(([x, y]) => ({ x, y }));
    if (ring.length >= 2) children.push(new fabric.Polygon(ring, { fill: '', stroke: '#FF00FF', strokeWidth: 1, selectable: false, evented: false, objectCaching: false }));
  }
  return new fabric.Group(children, {
    partId: p.id, cornerSize: 8, transparentCorners: false,
    perPixelTargetFind: true,
  });
}

// 加载零件图片元素（每个零件只一次），存入 imgElById
function loadPartImage(p) {
  return new Promise((resolve) => {
    const url = p.kind === 'parametric' ? p.subject_image : p.image_base64;
    fabric.Image.fromURL(url, (img) => { imgElById.set(p.id, img.getElement()); resolve(); }, { crossOrigin: null });
  });
}

// —— 新零件摆放：在纸框右侧的"暂存区"按网格找空位 ——
// 不再用全局递增计数器（删掉零件后仍会一直往下堆，越导越远）
const STAGE_GAP = 40;                 // 暂存区与纸框的间隔
function findFreeSpot(w, h) {
  const step = Math.max(120, Math.min(400, Math.max(w, h) + 30));
  const x0 = pageWpx + STAGE_GAP;
  const occupied = [...objById.values()].map(o => o.getBoundingRect(true));
  const hit = (x, y) => occupied.some(b =>
    !(x + w <= b.left || x >= b.left + b.width || y + h <= b.top || y >= b.top + b.height));
  // 逐列（每列 8 行）向右扫描找不重叠的位置
  for (let col = 0; col < 40; col++) {
    for (let row = 0; row < 8; row++) {
      const x = x0 + col * step, y = 20 + row * step;
      if (!hit(x, y)) return { x, y };
    }
  }
  return { x: x0, y: 20 };
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

// —— 锁角视觉标记 ——
// 锁角零件的「刀模描边」常显橙色（不选中也一眼可辨），选中框/手柄同色；自由 = 洋红描边+蓝框
const DIE_STROKE  = '#FF00FF';   // 常规刀模描边（洋红，与导出一致）
const LOCK_STROKE = '#F97316';   // 锁角零件刀模描边（橙，仅画布显示，导出仍洋红）
function updateLockVisual(o) {
  const locked = !!o.locked;
  // 组内有描边的 Polygon 即刀模线（参数化第 3 个子对象 / 固定第 2 个）
  // 锁角时描边加粗到 4px，远看也一眼可辨
  for (const ch of (o._objects || [])) {
    if (ch.type === 'polygon' && ch.stroke) {
      ch.set({ stroke: locked ? LOCK_STROKE : DIE_STROKE,
               strokeWidth: locked ? 4 : 1 });
    }
  }
  o.dirty = true;   // 组有缓存位图，需标脏重绘
  if (locked) {
    o.set({ borderColor: LOCK_STROKE, cornerColor: LOCK_STROKE });
  } else {
    o.set({ borderColor: 'rgba(102,153,255,0.75)', cornerColor: 'rgba(102,153,255,0.5)' });
  }
}
function markLocked(o) {
  o.locked = true;
  updateLockVisual(o);
  canvas.requestRenderAll();
  pushSnapshot();
}
function markFree(o) {
  o.locked = false;
  // 绕中心归零：fabric set angle 绕原点（左上）旋转，直接归零零件会跳位
  const c = o.getCenterPoint();
  o.set({ angle: 0 });
  updateLockVisual(o);
  o.setPositionByOrigin(c, 'center', 'center');
  o.setCoords();
  pushSnapshot();
}

// —— 锁角浮标签：选中锁角零件时悬浮「📌 角度已锁 · 点击解除」，点击=解锁归零 ——
const lockBadge = document.getElementById('lock-badge');
lockBadge.onclick = () => {
  const o = canvas.getActiveObject();
  if (o && o.partId && o.locked) {
    markFree(o);
    canvas.requestRenderAll();
    setStatus('已解除锁角');
  }
  lockBadge.style.display = 'none';
};
// 每帧渲染后更新标签位置（跟随选中对象与视口缩放/平移）；顺带刷新缩放百分比与切割确认条
const zoomLabel = document.getElementById('zoom-label');
const cutBar = document.getElementById('cut-bar');
canvas.on('after:render', () => {
  zoomLabel.textContent = Math.round(canvas.getZoom() * 100) + '%';
  const o = canvas.getActiveObject();
  if (o && o.partId && o.locked) {
    const br = o.getBoundingRect();   // viewport 坐标（即 #wrap 内像素）
    lockBadge.style.display = 'block';
    lockBadge.style.left = Math.round(br.left + br.width / 2 - lockBadge.offsetWidth / 2) + 'px';
    lockBadge.style.top  = Math.round(Math.max(2, br.top - 30)) + 'px';
  } else {
    lockBadge.style.display = 'none';
  }
  // 切割确认条跟随切割线
  if (cutPending && cutLine) {
    const br = cutLine.getBoundingRect();
    cutBar.style.display = 'flex';
    cutBar.style.left = Math.round(br.left + br.width / 2 - cutBar.offsetWidth / 2) + 'px';
    cutBar.style.top  = Math.round(Math.max(2, br.top - 40)) + 'px';
  } else {
    cutBar.style.display = 'none';
  }
});

// —— 重建某零件 Group（同步：白边变化时重算多边形，保留位置/缩放/角度/锁角）——
function rebuildPart(id) {
  const old = objById.get(id);
  if (!old) return;
  const grp = buildGroupSync(partData.get(id));
  if (!grp) return;
  // 中心锚定：白边变化时组尺寸改变，若沿用左上角会使零件向右下漂移
  const c = old.getCenterPoint();
  grp.set({ scaleX: old.scaleX, scaleY: old.scaleY, angle: old.angle });
  grp.setPositionByOrigin(c, 'center', 'center');
  grp.setCoords();
  // 保留锁角状态与拖动锁定（切割/修补模式中重建不解锁拖动）
  grp.locked = old.locked;
  grp.lockMovementX = old.lockMovementX;
  grp.lockMovementY = old.lockMovementY;
  updateLockVisual(grp);   // 不触发 pushSnapshot（rebuildPart 由 commitBorder 调用）
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
// 零件 transform 记录为绝对「中心坐标+角度+缩放」：多选 ActiveSelection 内
// 对象的 left/top/angle 是相对选区的坐标，直接记录会在撤销时错位，
// 故统一经 calcTransformMatrix 分解取绝对值。
function snapshot() {
  const activeIds = [...objById.keys()];
  const tf = {};
  for (const [id, g] of objById.entries()) {
    let cx, cy, sx, ang;
    if (g.group) {
      // 处于多选选区内：取绝对变换
      const d = fabric.util.qrDecompose(g.calcTransformMatrix());
      cx = d.translateX; cy = d.translateY; sx = d.scaleX; ang = d.angle;
    } else {
      const c = g.getCenterPoint();
      cx = c.x; cy = c.y; sx = g.scaleX || 1; ang = g.angle || 0;
    }
    tf[id] = { cx, cy, scaleX: sx, angle: ang, locked: !!g.locked };
  }
  return {
    activeIds,
    tf,
    g: {
      borderPx,
      smoothIters,
      pageWmm: pageWpx / PIXEL_RATIO,
      pageHmm: pageHpx / PIXEL_RATIO,
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
  // 先取消选区：选区存在时对成员 set 的坐标是相对坐标，会错位
  canvas.discardActiveObject();
  // 1. 全局参数
  borderPx = s.g.borderPx;
  // 平滑（旧快照可能无此字段，回退 0）
  const snapSmooth = s.g.smoothIters || 0;
  if (snapSmooth !== smoothIters) {
    smoothIters = snapSmooth;
    document.getElementById('smooth-range').value = snapSmooth;
    document.getElementById('smooth-label').textContent = snapSmooth;
    api('/api/set_smooth', { smooth_iters: snapSmooth }).catch(() => {});
  }
  // 纸张尺寸（如有变化）
  if (pageWpx / PIXEL_RATIO !== s.g.pageWmm || pageHpx / PIXEL_RATIO !== s.g.pageHmm) {
    applyPageSize(s.g.pageWmm, s.g.pageHmm);
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

  // 3. 应用每个零件 transform（中心坐标锚定，与快照记录格式一致）
  for (const id of s.activeIds) {
    const g  = objById.get(id);
    const tf = s.tf[id];
    if (!g || !tf) continue;
    g.set({
      scaleX: tf.scaleX,
      scaleY: tf.scaleX,   // 等比缩放
      angle:  tf.angle,
    });
    g.setPositionByOrigin(new fabric.Point(tf.cx, tf.cy), 'center', 'center');
    g.setCoords();
    // 锁角标记（内联设置，不触发 pushSnapshot）
    g.locked = !!tf.locked;
    updateLockVisual(g);
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
  // 模式中重建：继承拖动锁定
  grp.lockMovementX = old.lockMovementX;
  grp.lockMovementY = old.lockMovementY;
  if (tf) {
    grp.set({
      scaleX: tf.scaleX, scaleY: tf.scaleX,
      angle: tf.angle,
    });
    grp.setPositionByOrigin(new fabric.Point(tf.cx, tf.cy), 'center', 'center');
    grp.setCoords();
    grp.locked = !!tf.locked;
    updateLockVisual(grp);
  }
  canvas.remove(old);
  objById.set(id, grp);
  canvas.add(grp);
  if (pageRect) canvas.sendToBack(pageRect);
}

// 撤销
async function undo() {
  if (undoStack.length < 2) return;   // 保留基线快照
  if (cutDrawing || cutPending) cancelCutLine(); // 未确认的切割线随撤销一并取消
  redoStack.push(undoStack[undoStack.length - 1]);
  undoStack.pop();
  await applySnapshot(undoStack[undoStack.length - 1]);
  setStatus('已撤销');
}

// 重做
async function redo() {
  if (!redoStack.length) return;
  if (cutDrawing || cutPending) cancelCutLine();
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
  const total = files.length;
  // 醒目提示：横幅告知正在抠图（AI 抠图较慢，只有细进度条容易以为没反应）
  showBanner(`⏳ AI 抠图中… 0/${total} 张（首次运行需加载模型，请稍候）`);
  setStatus('抠图中…');
  try {
    for (let fileIdx = 0; fileIdx < total; fileIdx++) {
      const f = files[fileIdx];
      showProgress(fileIdx / total);
      showBanner(`⏳ AI 抠图中… ${fileIdx + 1}/${total} 张：${f.name}`);
      const dataUrl = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.readAsDataURL(f);
      });
      const r = await api('/api/segment', { image_base64: dataUrl });
      const { parts } = await r.json();
      showProgress((fileIdx + 0.7) / total);
      showBanner(`📦 摆放零件… ${fileIdx + 1}/${total} 张，分离出 ${parts.length} 个`);
      for (const p of parts) {
        // 在纸框右侧暂存区找空位（与已有零件不重叠），避免越导越远
        const spot = findFreeSpot(p.w || 300, p.h || 300);
        await addPart(p, spot.x, spot.y);
      }
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
    if (!cutMode && !brushMode) hideBanner();
  }
  e.target.value = '';
};

// —— 白边滑块（mm/px，全局，实时）——
const rng  = document.getElementById('border-range');
const num  = document.getElementById('border-num');
const unit = document.getElementById('border-unit');
function setBorderFromMm(mm) {
  // 先取消选区：选区内对象坐标是相对坐标，重建时读中心会错位
  canvas.discardActiveObject();
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

// —— 描边平滑滑块（0=不平滑；实时重建，松手同步后端+推快照）——
const smoothRng = document.getElementById('smooth-range');
const smoothLbl = document.getElementById('smooth-label');
function setSmoothIters(k) {
  canvas.discardActiveObject();
  smoothIters = k;
  smoothLbl.textContent = k;
  for (const id of objById.keys()) { if (partData.get(id).kind === 'parametric') rebuildPart(id); }
  canvas.requestRenderAll();
}
smoothRng.oninput = () => setSmoothIters(parseInt(smoothRng.value, 10) || 0);
smoothRng.onchange = () => {
  api('/api/set_smooth', { smooth_iters: smoothIters }).catch(() => {});
  pushSnapshot();
};

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
  // 同步输入框（撤销恢复页尺寸时 UI 不脱节；程序赋值不触发 onchange）
  if (pageUnitSel.value === 'px') {
    pageWInput.value = Math.round(wMm * PIXEL_RATIO);
    pageHInput.value = Math.round(hMm * PIXEL_RATIO);
  } else {
    pageWInput.value = wMm;
    pageHInput.value = hMm;
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
    updateLockVisual(o);
    setStatus('已锁角（按 L 解锁归零）');
  }
});
// object:modified 兜底：修改后 angle 非 0 则锁定；所有移动/缩放/旋转完成时推快照
// 多选 ActiveSelection 的变换也要推快照（成员绝对角度非 0 时锁角）
canvas.on('object:modified', (e) => {
  const o = e.target;
  if (!o) return;
  if (o.partId) {
    if (o.angle !== 0 && !o.locked) {
      o.locked = true;
      updateLockVisual(o);
      setStatus('已锁角（按 L 解锁归零）');
    }
    pushSnapshot();
    return;
  }
  if (o.type === 'activeSelection' || o.type === 'activeselection') {
    let anyPart = false;
    o.getObjects().forEach(m => {
      if (!m.partId) return;
      anyPart = true;
      const d = fabric.util.qrDecompose(m.calcTransformMatrix());
      if (Math.abs(d.angle) > 0.5 && !m.locked) {
        m.locked = true;
        updateLockVisual(m);
        setStatus('已锁角（按 L 解锁归零）');
      }
    });
    if (anyPart) pushSnapshot();
  }
});

// —— L 键解锁：选中锁角零件 → angle 归 0，恢复蓝色框 ——
window.addEventListener('keydown', (e) => {
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
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

// —— 零件的「刀模」场景包围盒（旋转/缩放感知）——
// 参数化组的 bbox 含透明主体图边距（旋转时更是外接矩形松弛），直接用会把
// 贴边零件误判为框外；这里用刀模环逐点经组变换矩阵映射，得到精确范围。
function dieSceneBBox(o) {
  if (!o.dieRingF || !o.dieRingF.length) return o.getBoundingRect(true);
  const m = o.calcTransformMatrix();
  const bx = o.frameOffX || 0, by = o.frameOffY || 0;
  const hw = o.width / 2, hh = o.height / 2;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [fx, fy] of o.dieRingF) {
    // 主体帧 → 组局部（bbox 左上原点）→ 组中心原点 → 场景
    const p = fabric.util.transformPoint(new fabric.Point(fx - bx - hw, fy - by - hh), m);
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }
  return { left: minX, top: minY, width: maxX - minX, height: maxY - minY };
}

// —— 导出 PNG -> /api/export（含框外过滤）——
document.getElementById('btn-export').onclick = async () => {
  // 计算所有零件中哪些完全在纸框内（物理坐标比较）
  const allParts = [...objById.values()];
  if (!allParts.length) { setStatus('画布为空'); return; }

  const insideParts = [];
  const outsideParts = [];

  // 判定容差：排版把刀模缓冲 spacing/2 贴到页边，加上前后端刀模几何的微小差异，
  // 允许 2px 内的越界视为在页内
  const EDGE_TOL = 2;
  for (const o of allParts) {
    // 刀模的物理 bbox（旋转/缩放感知，不受 viewport 影响）
    // 原实现用组 left/top+未旋转宽高：旋转零件 left/top 是原点位置而非 bbox 左上，
    // 且组 bbox 含透明主体图边距，均会误判
    const br = dieSceneBBox(o);
    const l = br.left;
    const t = br.top;
    const r = br.left + br.width;
    const b = br.top + br.height;
    // 判断是否完全在纸框内（含边界）
    if (l >= -EDGE_TOL && t >= -EDGE_TOL && r <= pageWpx + EDGE_TOL && b <= pageHpx + EDGE_TOL) {
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

// —— 删除选中（支持多选；只移出画布和 objById，保留 partData/imgElById 供 undo 重建）——
function deleteSelected() {
  const t = canvas.getActiveObject();
  if (!t) return;
  const targets = (t.type === 'activeSelection' || t.type === 'activeselection')
    ? t.getObjects().slice() : [t];
  const parts = targets.filter(o => o.partId);
  if (!parts.length) return;
  // 先取消选区，使成员坐标恢复为绝对坐标再移除
  canvas.discardActiveObject();
  for (const o of parts) {
    canvas.remove(o);
    objById.delete(o.partId);
    // partData/imgElById 保留，不删
  }
  canvas.requestRenderAll();
  setStatus(`已删除 ${parts.length} 个零件`);
  pushSnapshot();
}
document.getElementById('btn-delete').onclick = deleteSelected;

// Delete / Backspace 键删除选中零件（输入框内不拦截）
window.addEventListener('keydown', (e) => {
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (cutMode || brushMode) return;   // 模式中不误删
    e.preventDefault();
    deleteSelected();
  }
});

// 排版精度滑块数值联动
const nestPrecisionEl = document.getElementById('nest-precision');
nestPrecisionEl.oninput = () => {
  document.getElementById('nest-precision-label').textContent = nestPrecisionEl.value;
};

// —— 整理排版 -> /api/nest（旋转感知 BLF，中心+角度，间距，统一缩放）——
document.getElementById('btn-tidy').onclick = async () => {
  // 先取消选区：选区内对象的 setPositionByOrigin 是相对坐标，会错位
  canvas.discardActiveObject();
  // 构建 items：包含 id、当前 scale、角度、锁角状态
  const items = [...objById.values()].map(o => ({
    id:     o.partId,
    scale:  o.scaleX || 1,
    angle:  o.angle  || 0,
    locked: !!o.locked,
  }));
  if (!items.length) return;

  // 读取排版控件参数
  const angle_steps = parseInt(document.getElementById('nest-precision').value, 10);
  const spacingRaw  = parseFloat(document.getElementById('nest-spacing').value) || 0;
  const spacingUnit = document.getElementById('nest-spacing-unit').value;
  // 间距统一转换为 mm（后端接收 spacing_mm）
  const spacing_mm  = spacingUnit === 'px' ? spacingRaw / PIXEL_RATIO : spacingRaw;
  const uniform_scale = document.getElementById('nest-uniform').checked;

  setStatus('排版中…');
  showProgress(0.02);
  try {
    // 异步模式：后台线程排版，轮询 /api/nest_progress 获得逐零件真实进度
    await api('/api/nest', { items, spacing_mm, angle_steps, uniform_scale, async: true });
    const POLL_MS = 200, POLL_TIMEOUT_MS = 120000;   // 2 分钟兜底超时
    const positions = await new Promise((resolve, reject) => {
      let waited = 0;
      const timer = setInterval(async () => {
        try {
          waited += POLL_MS;
          if (waited > POLL_TIMEOUT_MS) { clearInterval(timer); reject(new Error('排版超时')); return; }
          const pr = await fetch('/api/nest_progress');
          if (!pr.ok) throw new Error(await pr.text());
          const s = await pr.json();
          if (s.error) { clearInterval(timer); reject(new Error(s.error)); return; }
          showProgress(Math.max(0.02, s.progress));
          // 中间状态：已放好的零件边算边挪到位，用户能看到排版在进行
          if (s.running && s.partial) {
            for (const pos of s.partial) {
              const o = objById.get(pos.id);
              if (!o || pos.cx < 0) continue;
              o.set({ scaleX: pos.scale, scaleY: pos.scale, angle: pos.angle });
              o.setPositionByOrigin(new fabric.Point(pos.cx, pos.cy), 'center', 'center');
              o.setCoords();
            }
            setStatus(`排版中… 已放置 ${s.partial.length}/${items.length}`);
            canvas.requestRenderAll();
          }
          if (!s.running && s.positions) { clearInterval(timer); resolve(s.positions); }
        } catch (e) { clearInterval(timer); reject(e); }
      }, POLL_MS);
    });
    // 放不下的零件按 spec「自然留在纸框外」：在纸框右侧整齐紧凑地列队
    // （按旋转后的实际包围盒逐行排布，行宽取该批最宽者，不再乱堆）
    const unplaced = positions.filter(p => p.cx < 0)
      .map(p => objById.get(p.id)).filter(Boolean);
    let outIdx = 0;
    if (unplaced.length) {
      const GAP = 20;
      let colX = pageWpx + STAGE_GAP, colW = 0, y = 20;
      for (const o of unplaced) {
        const br = o.getBoundingRect(true);   // 含旋转的实际占位
        if (y + br.height > pageHpx && y > 20) { colX += colW + GAP; colW = 0; y = 20; }
        // getBoundingRect 是 bbox，left/top 需按 bbox 与原点的偏移回推
        o.set({ left: o.left + (colX - br.left), top: o.top + (y - br.top) });
        o.setCoords();
        y += br.height + GAP;
        colW = Math.max(colW, br.width);
        outIdx++;
      }
    }
    for (const pos of positions) {
      const o = objById.get(pos.id);
      if (!o) continue;
      if (pos.cx < 0) continue;   // 已在上面整齐列队
      // 应用后端返回的缩放和角度（统一缩放时 scale 可能变化）
      o.set({ scaleX: pos.scale, scaleY: pos.scale, angle: pos.angle });
      // 按视觉中心物理坐标定位（与导出契约一致）
      o.setPositionByOrigin(new fabric.Point(pos.cx, pos.cy), 'center', 'center');
      o.setCoords();
      // 自由件被排版赋了角度后保持 locked=false（蓝框）；锁角件不改变状态
    }
    canvas.requestRenderAll();
    setStatus(outIdx > 0 ? `排版完成，${outIdx} 个零件放不下，已移到纸框右侧` : '排版完成');
    pushSnapshot();
  } catch (err) { setStatus('排版失败: ' + err.message); }
  finally { hideProgress(); }
};

// —— 适应视图按钮 ——
document.getElementById('btn-fit').onclick = fitView;

// ============================================================
// 切割模式（Phase 5 Task 2）
// ============================================================

// 切割状态变量
// 状态机（消除"选目标"与"画线"的左键歧义）：
//   选目标阶段：点击零件 = 设为目标 → 进入画线阶段（所有零件对鼠标透明）
//   画线阶段：第一次左键=起点，线随鼠标；第二次左键=终点 → 暂存态
//   暂存态：整线可拖 + 两个端点手柄可拖；「确认切割/取消」或 Enter/Esc
//   Esc 三级回退：取消线 → 清目标（回选目标阶段）→ 退出模式
let cutMode = false;            // 是否处于切割模式
let cutTarget = null;           // 切割目标零件
let cutDrawing = false;         // 画线中：线终点跟随鼠标
let cutPending = false;         // 暂存态：等待确认
let cutLine = null;             // 切割线(fabric.Line, 洋红虚线)
let cutP1 = null;               // 线端点（场景坐标，真相源——fabric.Line 改端点
let cutP2 = null;               //   不重算渲染位置，必须由端点变量重建线）
let cutHandles = [];            // 暂存态两个端点手柄(fabric.Circle)

// 画线阶段把零件设为对鼠标透明：左键点击纯画线，不会误选/误换零件
function setPartsEvented(flag) {
  canvas.getObjects().forEach(o => { if (o.partId) o.evented = flag; });
}

// 由 cutP1/P2 重建切割线；interactive=true 时线可拖动（暂存态）
// 线宽/虚线段随视图缩放反缩，任何缩放级别下屏幕观感一致且醒目
function renderCutLine(interactive) {
  if (cutLine) canvas.remove(cutLine);
  const k = 1 / Math.max(0.02, canvas.getZoom());
  cutLine = new fabric.Line([cutP1.x, cutP1.y, cutP2.x, cutP2.y], {
    stroke: '#FF00FF', strokeWidth: 3 * k, strokeDashArray: [10 * k, 7 * k],
    shadow: new fabric.Shadow({ color: 'rgba(255,255,255,0.9)', blur: 4 * k }),
    selectable: !!interactive, evented: !!interactive,
    hasControls: false, hasBorders: false, lockRotation: true,
    hoverCursor: 'move', excludeFromExport: true, objectCaching: false,
  });
  if (interactive) {
    cutLine.on('moving', () => {
      // 整线被拖动：从线的实际端点回写真相源并重定位手柄
      const m = cutLine.calcTransformMatrix();
      const lp = cutLine.calcLinePoints();
      const a = fabric.util.transformPoint(new fabric.Point(lp.x1, lp.y1), m);
      const b = fabric.util.transformPoint(new fabric.Point(lp.x2, lp.y2), m);
      cutP1 = { x: a.x, y: a.y };
      cutP2 = { x: b.x, y: b.y };
      positionCutHandles();
    });
  }
  canvas.add(cutLine);
  canvas.bringToFront(cutLine);
}

// 端点手柄：白底洋红圆，可拖动调整线端点
function makeCutHandles() {
  removeCutHandles();
  const k = 1 / Math.max(0.02, canvas.getZoom());
  const r = 9 * k;   // 屏幕上约 9px，够大好抓
  [cutP1, cutP2].forEach((pt, idx) => {
    const h = new fabric.Circle({
      left: pt.x, top: pt.y, radius: r,
      originX: 'center', originY: 'center',
      fill: '#fff', stroke: '#FF00FF', strokeWidth: 3 * k,
      shadow: new fabric.Shadow({ color: 'rgba(0,0,0,0.35)', blur: 4 * k }),
      hasControls: false, hasBorders: false,
      hoverCursor: 'crosshair', excludeFromExport: true, objectCaching: false,
    });
    h.isCutHandle = true;
    h.on('moving', () => {
      const c = h.getCenterPoint();
      if (idx === 0) cutP1 = { x: c.x, y: c.y };
      else cutP2 = { x: c.x, y: c.y };
      renderCutLine(true);
      cutHandles.forEach(hh => canvas.bringToFront(hh));
    });
    canvas.add(h);
    canvas.bringToFront(h);
    cutHandles.push(h);
  });
}
function positionCutHandles() {
  if (cutHandles.length === 2) {
    cutHandles[0].set({ left: cutP1.x, top: cutP1.y });
    cutHandles[0].setCoords();
    cutHandles[1].set({ left: cutP2.x, top: cutP2.y });
    cutHandles[1].setCoords();
  }
}
function removeCutHandles() {
  for (const h of cutHandles) canvas.remove(h);
  cutHandles = [];
}

// 目标聚焦视觉：选定目标后其他零件半透明置底，目标不透明置顶且带手柄隐藏
// （切割模式里零件完全不可变换，避免"还能移动旋转"的怪异感）
function applyCutFocus() {
  for (const o of objById.values()) {
    if (cutTarget && o !== cutTarget) {
      o.set({ opacity: 0.25 });
    } else {
      o.set({ opacity: 1 });
    }
  }
  if (cutTarget) canvas.bringToFront(cutTarget);
  if (pageRect) canvas.sendToBack(pageRect);
}
function clearCutFocus() {
  for (const o of objById.values()) o.set({ opacity: 1 });
}

// 切割模式：进入/退出
function enterCutMode() {
  // 若处于修补模式，先退出（两模式互斥，避免事件处理器叠加）
  if (brushMode) exitBrushMode();
  cutMode = true;
  document.getElementById('btn-cut').classList.add('active');
  // 切割模式内零件完全不可变换（移动/缩放/旋转全禁），只做"选目标"用
  canvas.getObjects().forEach(o => {
    if (o.partId) {
      o.lockMovementX = true;
      o.lockMovementY = true;
      o.lockRotation = true;
      o.lockScalingX = true;
      o.lockScalingY = true;
      o.hasControls = false;
    }
  });
  canvas.selection = false;
  // 若已有选中的可切零件，直接作为目标进入画线阶段
  const a = canvas.getActiveObject();
  if (a && a.partId && !a.locked && Math.abs(a.angle || 0) < 0.5) {
    cutTarget = a;
    setPartsEvented(false);
    applyCutFocus();
    showBanner('✂️ 画切割线：左键点起点 → 移动 → 左键点终点（Esc 重新选目标）');
    setStatus('目标已选中（其他零件已淡出），左键点切割线起点');
  } else {
    showBanner('✂️ 切割模式：先点选一个目标零件（Esc 退出）');
    setStatus('切割：先点选一个目标零件');
  }
  canvas.requestRenderAll();
}

function exitCutMode() {
  cutMode = false;
  document.getElementById('btn-cut').classList.remove('active');
  cancelCutLine();
  // 恢复所有零件可拖拽/可变换/可命中
  canvas.getObjects().forEach(o => {
    if (o.partId) {
      o.lockMovementX = false;
      o.lockMovementY = false;
      o.lockRotation = false;
      o.lockScalingX = false;
      o.lockScalingY = false;
      o.hasControls = true;
    }
  });
  setPartsEvented(true);
  clearCutFocus();
  canvas.selection = true;
  cutTarget = null;
  hideBanner();
  canvas.discardActiveObject();
  canvas.requestRenderAll();
  setStatus('已退出切割模式');
}

// 取消当前切割线（不退出模式、不清目标）
function cancelCutLine() {
  canvas.discardActiveObject();
  if (cutLine) {
    canvas.remove(cutLine);
    cutLine = null;
  }
  removeCutHandles();
  cutDrawing = false;
  cutPending = false;
  cutP1 = null;
  cutP2 = null;
  cutBar.style.display = 'none';
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

// Enter 确认切割 / Esc 三级回退：取消线 → 清目标 → 退出模式
window.addEventListener('keydown', (e) => {
  if (!cutMode) return;
  if (e.key === 'Enter' && cutPending) {
    doCut();
    return;
  }
  if (e.key === 'Escape') {
    if (cutDrawing || cutPending) {
      cancelCutLine();
      setStatus('已取消切割线，左键重新点起点');
    } else if (cutTarget) {
      cutTarget = null;
      setPartsEvented(true);
      clearCutFocus();
      canvas.discardActiveObject();
      canvas.requestRenderAll();
      showBanner('✂️ 切割模式：先点选一个目标零件（Esc 退出）');
      setStatus('已清除切割目标，点选零件');
    } else {
      exitCutMode();
    }
  }
});

// 切割 mouse:down：状态机分派
canvas.on('mouse:down', function (opt) {
  if (!cutMode || isPanning) return;
  const target = opt.target;

  // 暂存态：点线/端点手柄 = fabric 拖动；点其他地方仅提示
  if (cutPending) {
    if (target !== cutLine && !(target && target.isCutHandle)) {
      setStatus('拖动线或端点微调，点「确认切割」执行，Esc 取消');
    }
    return;
  }

  const ptr = canvas.getPointer(opt.e);

  // 画线阶段第二击：定终点 → 暂存态（线+端点手柄可拖）
  if (cutDrawing) {
    cutP2 = { x: ptr.x, y: ptr.y };
    if (Math.hypot(cutP2.x - cutP1.x, cutP2.y - cutP1.y) < 5) {
      return;   // 原地双击忽略，继续画线
    }
    cutDrawing = false;
    cutPending = true;
    renderCutLine(true);
    makeCutHandles();
    canvas.requestRenderAll();
    setStatus('拖动线或端点微调，点「确认切割」或 Enter 执行');
    return;
  }

  // 选目标阶段：点击零件 = 设为目标并进入画线阶段
  if (!cutTarget) {
    if (target && target.partId) {
      if (target.locked || Math.abs(target.angle || 0) > 0.5) {
        setStatus('该零件已锁角/旋转，请先按 L 归零再切割');
        return;
      }
      cutTarget = target;
      // 零件对鼠标透明：之后的左键全部用于画线，不会误选其他零件
      setPartsEvented(false);
      // 目标聚焦：其他零件淡出置底，目标醒目（不再靠选中框表达"已选"，
      // 因为点空白会取消选中框，让用户误以为目标丢了）
      applyCutFocus();
      canvas.discardActiveObject();
      canvas.requestRenderAll();
      showBanner('✂️ 画切割线：左键点起点 → 移动 → 左键点终点（Esc 重新选目标）');
      setStatus('目标已选中（其他零件已淡出），左键点切割线起点');
    } else {
      setStatus('切割：先点选一个目标零件');
    }
    return;
  }

  // 画线阶段第一击：起点（零件已透明，任意位置的左键都到这里）
  cutDrawing = true;
  cutP1 = { x: ptr.x, y: ptr.y };
  cutP2 = { x: ptr.x, y: ptr.y };
  renderCutLine(false);
  canvas.requestRenderAll();
  setStatus('移动鼠标，再次左键确定切割线终点');
});

// 画线阶段：线终点跟随鼠标（无需按住；每次由端点变量重建线，任意方向都正确渲染）
canvas.on('mouse:move', function (opt) {
  if (!cutMode || !cutDrawing || !cutP1 || isPanning) return;
  const ptr = canvas.getPointer(opt.e);
  cutP2 = { x: ptr.x, y: ptr.y };
  renderCutLine(false);
  canvas.requestRenderAll();
});

// 确认条按钮
document.getElementById('cut-confirm').onclick = () => doCut();
document.getElementById('cut-cancel').onclick = () => {
  cancelCutLine();
  setStatus('已取消切割线');
};

// 执行切割：按暂存切割线切目标零件，切完两块沿切割线法线分居两侧（内容对齐）
async function doCut() {
  if (!cutPending || !cutTarget || !cutP1 || !cutP2) return;
  const group = cutTarget;

  // 端点真相源（线/手柄拖动时已实时回写）
  const P1 = { x: cutP1.x, y: cutP1.y };
  const P2 = { x: cutP2.x, y: cutP2.y };
  cancelCutLine();

  if (Math.hypot(P2.x - P1.x, P2.y - P1.y) < 5) {
    setStatus('切割线太短，请重画');
    return;
  }

  // 场景坐标 → 主体帧坐标（组包围盒左上 + frameOff 偏移；固定零件 frameOff=0）
  const scaleX = group.scaleX || 1;
  const scaleY = group.scaleY || 1;
  const fox = group.frameOffX || 0;
  const foy = group.frameOffY || 0;
  const x1 = (P1.x - group.left) / scaleX + fox;
  const y1 = (P1.y - group.top)  / scaleY + foy;
  const x2 = (P2.x - group.left) / scaleX + fox;
  const y2 = (P2.y - group.top)  / scaleY + foy;

  const partId = group.partId;
  const origLeft = group.left;
  const origTop  = group.top;
  const gScale = scaleX;

  setStatus('切割中…');
  showProgress(0.5);
  try {
    const r = await api('/api/cut', { id: partId, x1, y1, x2, y2, commit: true });
    const { parts: pieces } = await r.json();
    if (!pieces || pieces.length === 0) {
      setStatus('切割未产生有效分块，请调整切割线');
      return;
    }

    // 移除原件（只从画布和 objById 移除，保留 partData/imgElById 供 undo）
    canvas.remove(group);
    objById.delete(partId);

    // 每块：内容原位对齐(frame_dx/dy) + 沿切割线法线向各自侧推开
    const ldx = x2 - x1, ldy = y2 - y1;
    const L = Math.hypot(ldx, ldy) || 1;
    const nX = -ldy / L, nY = ldx / L;      // dist>0 侧的单位法线（主体帧≈场景方向，无旋转）
    const GAP = 30;                          // 两块沿法线各自推开的距离（场景 px）
    for (const piece of pieces) {
      // 块中心在原主体帧中的位置 → 判定其在切割线哪一侧
      const pcx = (piece.frame_dx || 0) + piece.w / 2;
      const pcy = (piece.frame_dy || 0) + piece.h / 2;
      const side = Math.sign(ldx * (pcy - y1) - ldy * (pcx - x1)) || 1;
      const px = origLeft + (piece.frame_dx || 0) * gScale + side * nX * GAP;
      const py = origTop  + (piece.frame_dy || 0) * gScale + side * nY * GAP;
      await addPart(piece, px, py);
      const po = objById.get(piece.id);
      if (po && gScale !== 1) { po.set({ scaleX: gScale, scaleY: gScale }); po.setCoords(); }
    }

    canvas.requestRenderAll();
    pushSnapshot();
    // spec：确认完成后退出切割模式
    exitCutMode();
    setStatus(`切割完成，${pieces.length} 块已沿切割线两侧分开`);
  } catch (err) {
    setStatus('切割失败: ' + err.message);
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
// 交互流程（实时）：进入模式 → 画笔光标跟随鼠标 → 每涂一笔松手立即应用并看到效果
// → 不满意 Ctrl+Z 逐笔撤销 → Esc / B 退出模式。零件在模式内完全不可选中拖动。
let brushMode     = false;   // 是否处于修补画笔模式
let brushPainting = false;   // 当前是否正在涂抹（mouse down 中）
let brushTarget   = null;    // 当前笔画的目标零件（每笔独立）
let brushCanvas   = null;    // 离屏 canvas（subject_image 像素尺寸，单笔）
let brushCtx      = null;    // 对应 2D 上下文
let brushCurPts   = [];      // 当前笔画的场景坐标点
let brushCurLine  = null;    // 当前笔画的临时预览折线
let brushCursor   = null;    // 画笔圆形光标（跟随鼠标）
let brushBusy     = false;   // 正在提交后端（避免并发）

// 画笔光标：圆圈随鼠标移动，半径=笔刷大小/2（场景 px，随视图缩放显示）
function ensureBrushCursor() {
  if (brushCursor) return;
  brushCursor = new fabric.Circle({
    left: -9999, top: -9999, radius: 1,
    originX: 'center', originY: 'center',
    fill: 'rgba(255,255,255,0.15)',
    stroke: '#0ea5e9', strokeWidth: 1,
    selectable: false, evented: false,
    excludeFromExport: true, objectCaching: false,
  });
  canvas.add(brushCursor);
}
function updateBrushCursor(ptr) {
  if (!brushCursor) return;
  const mode = document.getElementById('brush-mode').value;
  const k = 1 / Math.max(0.02, canvas.getZoom());
  brushCursor.set({
    left: ptr.x, top: ptr.y,
    radius: parseInt(brushSizeEl.value, 10) / 2,
    stroke: mode === 'add' ? '#16a34a' : '#dc2626',
    fill: mode === 'add' ? 'rgba(22,163,74,0.15)' : 'rgba(220,38,38,0.15)',
    strokeWidth: 2 * k,
  });
  brushCursor.setCoords();
  canvas.bringToFront(brushCursor);
  canvas.requestRenderAll();
}
function removeBrushCursor() {
  if (brushCursor) { canvas.remove(brushCursor); brushCursor = null; }
}

// 进入修补画笔模式
function enterBrushMode() {
  // 若处于切割模式，先退出
  if (cutMode) exitCutMode();
  brushMode = true;
  document.getElementById('btn-brush').classList.add('active');
  // 零件在修补模式内完全不可选中/拖动/变换（只作为涂抹底图）
  canvas.discardActiveObject();
  canvas.getObjects().forEach(o => {
    if (o.partId) {
      o.__prevSel = o.selectable;
      o.selectable = false;
      o.hasControls = false;
    }
  });
  canvas.selection = false;
  canvas.defaultCursor = 'none';    // 用画笔圆圈代替系统光标
  canvas.hoverCursor = 'none';
  ensureBrushCursor();
  showBanner('🖌️ 修补模式：在零件上涂抹即刻生效（工具栏切换 加/擦）· Ctrl+Z 撤销 · Esc 退出');
  setStatus('修补：涂抹即时生效，Ctrl+Z 可逐笔撤销');
  canvas.requestRenderAll();
}

// 退出修补画笔模式
function exitBrushMode() {
  brushMode = false;
  document.getElementById('btn-brush').classList.remove('active');
  // 恢复零件可选中/可变换
  canvas.getObjects().forEach(o => {
    if (o.partId) {
      o.selectable = (typeof o.__prevSel === 'boolean') ? o.__prevSel : true;
      delete o.__prevSel;
      o.hasControls = true;
    }
  });
  canvas.selection = true;
  canvas.defaultCursor = 'default';
  canvas.hoverCursor = 'move';
  clearBrushStroke();
  removeBrushCursor();
  hideBanner();
  canvas.requestRenderAll();
  setStatus('已退出修补模式');
}

// 清除当前笔画的临时状态
function clearBrushStroke() {
  if (brushCurLine) { canvas.remove(brushCurLine); brushCurLine = null; }
  brushCurPts   = [];
  brushPainting = false;
  brushTarget   = null;
  brushCanvas   = null;
  brushCtx      = null;
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

// Esc 退出修补模式（实时模式无待确认笔迹）
window.addEventListener('keydown', (e) => {
  if (!brushMode) return;
  if (e.key === 'Escape' && !brushPainting) exitBrushMode();
});

// 加/擦切换、笔刷大小变化时刷新光标外观
document.getElementById('brush-mode').addEventListener('change', () => {
  if (brushMode && brushCursor) updateBrushCursor(brushCursor.getCenterPoint());
});
brushSizeEl.addEventListener('input', () => {
  if (brushMode && brushCursor) updateBrushCursor(brushCursor.getCenterPoint());
});

// 计算 subject_image 像素坐标（场景物理坐标 → subject_image px）
// group._objects = [white(0), img(1), dieLine(2)]（参数化）；img.left = -minx（die bbox 左偏移）
function sceneToSubjectPx(group, sceneX, sceneY) {
  const pd  = partData.get(group.partId);
  if (!pd) return null;
  // group 内 img 的 left/top：fabric 分组后子对象坐标以「组中心」为基准（非组左上角）
  const objs = group._objects;
  // 参数化 group 的 image 子对象在索引 1
  const imgChild = objs && objs.length >= 2 ? objs[1] : null;
  if (!imgChild) return null;
  // subject_image 左上角在场景（物理）坐标 = 组中心 + 子对象偏移×缩放
  const scaleX = group.scaleX || 1;
  const scaleY = group.scaleY || 1;
  const gc = group.getCenterPoint();
  const subjOriginX = gc.x + imgChild.left * scaleX;
  const subjOriginY = gc.y + imgChild.top  * scaleY;
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

// 在离屏 canvas 上画一个白色圆点（笔迹记录，主体帧像素坐标）
function paintDot(px, py, r) {
  if (!brushCtx) return;
  brushCtx.beginPath();
  brushCtx.arc(px, py, r, 0, Math.PI * 2);
  brushCtx.fillStyle = '#ffffff';
  brushCtx.fill();
}

// 记录一个笔迹点：写入离屏画布 + 更新当前笔画预览折线
function brushAddPoint(ptr) {
  const sp = sceneToSubjectPx(brushTarget, ptr.x, ptr.y);
  if (sp) {
    // 主体帧内笔径 = 物理笔径 / 组缩放（组被放大时帧内笔迹相应变细，屏上大小一致）
    const gScale = brushTarget.scaleX || 1;
    paintDot(sp.x, sp.y, (parseInt(brushSizeEl.value, 10) / 2) / gScale);
  }
  brushCurPts.push({ x: ptr.x, y: ptr.y });
  rebuildCurStrokeLine();
}

// 重建当前笔画的预览折线（单对象，替代逐点 Circle 的性能问题）
function rebuildCurStrokeLine() {
  if (brushCurLine) canvas.remove(brushCurLine);
  const mode  = document.getElementById('brush-mode').value;
  const color = mode === 'add' ? 'rgba(0,200,0,0.45)' : 'rgba(220,0,0,0.45)';
  // 单点时补一个近点，保证圆头帽画出圆点
  const pts = brushCurPts.length === 1
    ? [brushCurPts[0], { x: brushCurPts[0].x + 0.1, y: brushCurPts[0].y }]
    : brushCurPts;
  brushCurLine = new fabric.Polyline(pts, {
    stroke: color,
    strokeWidth: parseInt(brushSizeEl.value, 10),
    strokeLineCap: 'round',
    strokeLineJoin: 'round',
    fill: '',
    selectable: false,
    evented: false,
    excludeFromExport: true,
    objectCaching: false,
  });
  canvas.add(brushCurLine);
  canvas.requestRenderAll();
}

// 命中零件：修补模式下零件 selectable=false，opt.target 不可靠，
// 用 findTarget(skipGroup) 主动查（perPixelTargetFind 仍生效，透明处不命中）
function brushHitPart(opt) {
  const t = canvas.findTarget(opt.e, true);
  return (t && t.partId) ? t : null;
}

// mouse:down — 修补画笔：开始一笔
canvas.on('mouse:down', function (opt) {
  if (!brushMode || isPanning || brushBusy) return;

  const target = brushHitPart(opt);
  if (!target) {
    setStatus('修补：请在零件主体或白边上涂抹');
    return;
  }
  const pd = partData.get(target.partId);
  if (!pd || pd.kind !== 'parametric') {
    setStatus('修补：仅支持参数化零件');
    return;
  }
  // 旋转零件的场景→主体帧映射未处理角度，先归零再修补
  if (Math.abs(target.angle || 0) > 0.5) {
    setStatus('修补：请先按 L 将零件角度归零再修补');
    return;
  }

  // 每笔独立：锁定本笔目标并新建离屏 canvas（subject_image 原生像素尺寸）
  brushTarget = target;
  brushCanvas = document.createElement('canvas');
  brushCanvas.width  = pd.w;
  brushCanvas.height = pd.h;
  brushCtx = brushCanvas.getContext('2d');
  brushPainting = true;
  brushCurPts = [];
  brushAddPoint(canvas.getPointer(opt.e));
});

// mouse:move — 延续当前笔画；未按下时只更新画笔光标位置
canvas.on('mouse:move', function (opt) {
  if (!brushMode || isPanning) return;
  const ptr = canvas.getPointer(opt.e);
  updateBrushCursor(ptr);
  if (!brushPainting) return;
  brushAddPoint(ptr);
});

// mouse:up — 松手即刻提交本笔到后端并替换零件（实时看到效果）
canvas.on('mouse:up', function () {
  if (!brushMode || !brushPainting) return;
  brushPainting = false;
  applyBrushStroke();
});

// 应用当前一笔：提交后端，替换零件（内容原位对齐），一笔一步快照
async function applyBrushStroke() {
  if (!brushTarget || !brushCanvas || brushBusy) { clearBrushStroke(); return; }
  const group  = brushTarget;
  const partId = group.partId;
  const origLeft = group.left;
  const origTop  = group.top;
  const gScale = group.scaleX || 1;

  // 导出笔迹为 PNG data-url（白色笔迹=涂抹区）
  const stroke_b64 = brushCanvas.toDataURL('image/png');
  const mode = document.getElementById('brush-mode').value;
  clearBrushStroke();

  brushBusy = true;
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

    // 按后端帧偏移原位对齐：新主体帧原点在旧主体帧的 (frame_dx, frame_dy)
    for (const piece of parts) {
      const px = origLeft + (piece.frame_dx || 0) * gScale;
      const py = origTop  + (piece.frame_dy || 0) * gScale;
      await addPart(piece, px, py);
      const po = objById.get(piece.id);
      if (po) {
        // 继承原零件缩放（绕左上角缩放，left/top 不动，对齐关系保持）
        if (gScale !== 1) { po.set({ scaleX: gScale, scaleY: gScale }); po.setCoords(); }
        // 修补模式内新零件同样不可选中，且画笔光标保持在最上层
        if (brushMode) { po.selectable = false; po.hasControls = false; }
      }
    }

    if (pageRect) canvas.sendToBack(pageRect);
    if (brushCursor) canvas.bringToFront(brushCursor);
    canvas.requestRenderAll();
    setStatus(parts.length > 1
      ? `修补完成，分裂为 ${parts.length} 个零件（Ctrl+Z 撤销）`
      : '修补完成（Ctrl+Z 撤销）');
    pushSnapshot();
  } catch (err) {
    setStatus('修补失败: ' + err.message);
  } finally {
    brushBusy = false;
    hideProgress();
  }
}

// 初始 fit-view（仅纸框）并推基线快照（使最早的导入也可撤销）
fitView();
pushSnapshot();
