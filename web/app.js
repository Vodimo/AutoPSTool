// 视图缩放：画布显示 630x891，对应物理 2100x2970 px
const VIEW_SCALE = 0.3;
const canvas = new fabric.Canvas('c', { selection: true, backgroundColor: '#fff' });
const statusEl = document.getElementById('status');
const setStatus = (t) => statusEl.textContent = t;

let cutMode = false;
// part id -> fabric.Image
const objById = new Map();

async function api(path, body) {
  const r = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error(await r.text());
  return r;
}

// 把后端返回的零件加到画布
function addPart(p, x = 20, y = 20) {
  fabric.Image.fromURL(p.image_base64, (img) => {
    img.set({
      left: x, top: y,
      scaleX: VIEW_SCALE, scaleY: VIEW_SCALE,
      partId: p.id, contour: p.contour,
      cornerSize: 8, transparentCorners: false
    });
    objById.set(p.id, img);
    canvas.add(img);
    canvas.requestRenderAll();
  });
}

// 导入图片 -> /api/segment
document.getElementById('btn-import').onclick = () => document.getElementById('file').click();
document.getElementById('file').onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  setStatus('抠图中…');
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const r = await api('/api/segment', { image_base64: reader.result });
      const { parts } = await r.json();
      let i = 0;
      for (const p of parts) { addPart(p, 20 + (i % 5) * 110, 20 + Math.floor(i / 5) * 110); i++; }
      setStatus(`分离出 ${parts.length} 个零件`);
    } catch (err) { setStatus('抠图失败: ' + err.message); }
  };
  reader.readAsDataURL(f);
};

// 切割模式
const cutBtn = document.getElementById('btn-cut');
cutBtn.onclick = () => {
  cutMode = !cutMode;
  cutBtn.classList.toggle('active', cutMode);
  canvas.selection = !cutMode;
  setStatus(cutMode ? '切割模式：在选中零件上拖一条线' : '就绪');
};

// 切割：在选中对象上按下->抬起，取两端点（换算为零件局部像素）
let cutStart = null;
canvas.on('mouse:down', (opt) => {
  if (!cutMode) return;
  const t = canvas.getActiveObject();
  if (!t || !t.partId) { setStatus('请先选中一个零件再切割'); return; }
  cutStart = canvas.getPointer(opt.e);
});
canvas.on('mouse:up', async (opt) => {
  if (!cutMode || !cutStart) return;
  const t = canvas.getActiveObject();
  const end = canvas.getPointer(opt.e);
  cutStart = (() => { const s = cutStart; cutStart = null; return s; })();
  if (!t || !t.partId) return;
  // 画布坐标 -> 零件局部像素坐标
  const toLocal = (pt) => ({
    x: Math.round((pt.x - t.left) / t.scaleX),
    y: Math.round((pt.y - t.top) / t.scaleY)
  });
  const a = toLocal(cutStart), b = toLocal(end);
  setStatus('切割中…');
  try {
    const r = await api('/api/cut', { id: t.partId, x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    const { parts } = await r.json();
    canvas.remove(t); objById.delete(t.partId);
    let i = 0;
    for (const p of parts) { addPart(p, t.left + i * 20, t.top + i * 20); i++; }
    setStatus(`切成 ${parts.length} 块`);
  } catch (err) { setStatus('切割失败: ' + err.message); }
});

// 整理排版 -> /api/nest
document.getElementById('btn-tidy').onclick = async () => {
  const items = [...objById.values()].map(o => ({ id: o.partId, scale: o.scaleX / VIEW_SCALE }));
  if (!items.length) return;
  setStatus('排版中…');
  try {
    const r = await api('/api/nest', { items });
    const { positions } = await r.json();
    for (const pos of positions) {
      const o = objById.get(pos.id);
      if (!o || pos.x < 0) continue;
      o.set({ left: pos.x * VIEW_SCALE, top: pos.y * VIEW_SCALE });
      o.setCoords();
    }
    canvas.requestRenderAll();
    setStatus('排版完成');
  } catch (err) { setStatus('排版失败: ' + err.message); }
};

// 删除选中
document.getElementById('btn-delete').onclick = () => {
  const t = canvas.getActiveObject();
  if (t && t.partId) { objById.delete(t.partId); canvas.remove(t); }
};

// 导出 PNG -> /api/export
document.getElementById('btn-export').onclick = async () => {
  const items = [...objById.values()].map(o => ({
    id: o.partId,
    x: Math.round(o.left / VIEW_SCALE),
    y: Math.round(o.top / VIEW_SCALE),
    scale: o.scaleX / VIEW_SCALE
  }));
  if (!items.length) { setStatus('画布为空'); return; }
  setStatus('导出中…');
  try {
    const r = await api('/api/export', { items });
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'diecut_layout.png'; a.click();
    URL.revokeObjectURL(url);
    setStatus('已导出');
  } catch (err) { setStatus('导出失败: ' + err.message); }
};
