"""Flask 后端：托管前端、抠图/切割/排版/导出 API、内存会话、浏览器自启。"""
import os
import io
import base64
import threading
import webbrowser

import cv2
import numpy as np
from flask import Flask, request, jsonify, send_file, send_from_directory, abort

from app import segmentation, part_builder, nesting, exporter, border, geometry as g
from app.models import Part

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
app = Flask(__name__, static_folder=None)

PARTS = {}  # id -> Part（单用户本地工具，内存会话足够）
OFFSET_MM = g.OFFSET_MM  # 全局白边(会话级)，前端 /api/set_border 同步
BLEED_MM = g.BLEED_MM    # 全局切割出血(会话级)，前端 /api/set_bleed 同步
PAGE_W_MM = 210           # 全局纸张宽度(mm)，前端 /api/set_page 同步
PAGE_H_MM = 297           # 全局纸张高度(mm)
SMOOTH_ITERS = 0          # 全局描边平滑迭代数(0=不平滑)，前端 /api/set_smooth 同步


def _decode_image(b64: str):
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    data = base64.b64decode(b64)
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # 统一 BGR 3 通道
    if img is None:
        abort(400, description="无法解码图像")
    return img


def _require_json(*keys):
    """取出 JSON 请求体并校验必需字段，缺失则返回 400（而非 500 堆栈）。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description="请求体必须是 JSON 对象")
    for k in keys:
        if k not in data:
            abort(400, description=f"缺少字段: {k}")
    return data


def part_to_dict(part: Part) -> dict:
    """零件序列化给前端：参数化零件下发主体图+轮廓；固定零件下发合成图+刀模。"""
    if part.subject_outline:
        ok, buf = cv2.imencode(".png", cv2.cvtColor(part.subject_image, cv2.COLOR_RGBA2BGRA))
        if not ok:
            raise RuntimeError("主体图 PNG 编码失败")
        return {
            "id": part.id, "kind": "parametric",
            "subject_image": "data:image/png;base64," + base64.b64encode(buf).decode(),
            "subject_outline": part.subject_outline,
            # 细采样的最外环点集：前端 clipper 直接缓冲它(无端点法粗棱角、无洞连线斜杠)
            "subject_poly": border.outer_polyline(part.subject_outline),
            # 切割半平面(主体帧)：前端渲染刀模时逐个求交(切口平直+出血越线)
            "cut_planes": part.cut_planes or [],
            "w": part.subject_image.shape[1], "h": part.subject_image.shape[0],
        }
    rgba = part.image_layer
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    if not ok:
        raise RuntimeError("零件图片层 PNG 编码失败")
    return {
        "id": part.id, "kind": "fixed",
        "image_base64": "data:image/png;base64," + base64.b64encode(buf).decode(),
        "w": part.w, "h": part.h, "dieline_path": part.dieline_path,
    }


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/<path:fname>")
def static_files(fname):
    return send_from_directory(WEB_DIR, fname)


@app.route("/api/segment", methods=["POST"])
def api_segment():
    d = _require_json("image_base64")
    img = _decode_image(d["image_base64"])
    subjects = segmentation.segment_subjects(img)
    out = []
    for s in subjects:
        part = part_builder.build_part(img, s["mask"])
        PARTS[part.id] = part
        out.append(part_to_dict(part))
    return jsonify({"parts": out})


@app.route("/api/set_bleed", methods=["POST"])
def api_set_bleed():
    """设置全局切割出血量（毫米）。必须大于 0。"""
    global BLEED_MM
    d = _require_json("bleed_mm")
    val = float(d["bleed_mm"])
    if val <= 0:
        abort(400, description="bleed_mm 必须大于 0")
    BLEED_MM = val
    return jsonify({"ok": True, "bleed_mm": BLEED_MM})


@app.route("/api/cut", methods=["POST"])
def api_cut():
    """切割零件：commit=false 仅预览（不改 PARTS），commit=true 两块入库（原件保留，供撤销重建）。

    坐标帧约定：参数化零件的切割坐标为「主体帧」（subject_image 局部坐标，与前端
    group 包围盒一致）；固定零件为 image_layer 局部坐标。参数化实体化后的局部原点
    = 主体帧内刀模包围盒左上（= 主体 bbox 左上各向外扩 offset_px），需先平移换算。
    """
    d = _require_json("id", "x1", "y1", "x2", "y2")
    commit = bool(d.get("commit", False))
    part = PARTS.get(d["id"])
    if part is None:
        return jsonify({"error": "part not found"}), 404
    x1, y1 = float(d["x1"]), float(d["y1"])
    x2, y2 = float(d["x2"]), float(d["y2"])
    if part.subject_outline:
        # 参数化路线：主体沿线截断，块仍为参数化零件（白边/出血/平滑保持实时可调）
        results = part_builder.cut_part_parametric(part, (x1, y1), (x2, y2))
        if commit:
            for p, _ in results:
                PARTS[p.id] = p
        out = []
        for p, (fdx, fdy) in results:
            item = part_to_dict(p)
            # 新块主体帧原点在原主体帧中的坐标：前端据此原位对齐/沿切线分开摆放
            item["frame_dx"] = int(fdx)
            item["frame_dy"] = int(fdy)
            out.append(item)
        return jsonify({"parts": out})
    # 固定零件（历史遗留）仍走像素切割
    a, b = part_builder.cut_part(part, (x1, y1), (x2, y2), bleed_mm=BLEED_MM)
    pieces = [x for x in (a, b) if x is not None]
    if commit:
        for piece in pieces:
            PARTS[piece.id] = piece
    return jsonify({"parts": [part_to_dict(p) for p in pieces]})


def _decode_mask_b64(b64: str, target_wh=None):
    """把 data-url base64 PNG 解码为单通道 0/255 掩膜。
    若 target_wh=(w,h) 与解码尺寸不一致，用最近邻插值 resize。
    """
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    data = base64.b64decode(b64)
    arr = np.frombuffer(data, np.uint8)
    gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        abort(400, description="无法解码笔迹掩膜")
    if target_wh is not None:
        tw, th = target_wh
        if gray.shape[1] != tw or gray.shape[0] != th:
            gray = cv2.resize(gray, (tw, th), interpolation=cv2.INTER_NEAREST)
    return gray


@app.route("/api/brush", methods=["POST"])
def api_brush():
    """手动修补画笔：对零件的 edit_mask 应用笔迹，重算白边/刀模，可能分裂为多块。
    请求体：{id, stroke_b64, mode}
      - id: 零件 id
      - stroke_b64: 与 subject_image 同尺寸的笔迹掩膜 PNG（白=涂抹处）data-url base64
      - mode: 'add' | 'erase'
    返回：{parts: [...]}，新块入库，原件保留（供撤销重建）。
    """
    d = _require_json("id", "stroke_b64", "mode")
    part = PARTS.get(d["id"])
    if part is None:
        return jsonify({"error": "part not found"}), 404
    if part.edit_mask is None or part.source_bgr is None:
        abort(400, description="该零件不含 edit_mask/source_bgr，无法修补")

    em_h, em_w = part.edit_mask.shape
    stroke = _decode_mask_b64(d["stroke_b64"], target_wh=(em_w, em_h))

    mode = d["mode"]
    if mode not in ("add", "erase"):
        abort(400, description="mode 必须是 'add' 或 'erase'")

    results = part_builder.apply_brush(part, stroke, mode)

    # 追加新零件，保留原件（支持 undo 重建）
    out = []
    for p, (fdx, fdy) in results:
        PARTS[p.id] = p
        item = part_to_dict(p)
        # 新零件主体帧原点在旧主体帧中的坐标：前端据此原位对齐摆放
        item["frame_dx"] = int(fdx)
        item["frame_dy"] = int(fdy)
        out.append(item)

    return jsonify({"parts": out})


# 排版后台任务状态（单用户单任务足够）：/api/nest async 模式写入，/api/nest_progress 轮询
NEST_JOB = {"running": False, "progress": 1.0, "positions": None, "error": None}


def _run_nest(parts, spacing_mm, angle_steps, uniform_scale, offset_mm, page_px,
              smooth_iters, bleed_mm):
    """后台线程执行排版，进度写入 NEST_JOB。"""
    def cb(done, total):
        NEST_JOB["progress"] = done / max(1, total)

    try:
        nesting.nest(
            parts,
            offset_mm=offset_mm,
            spacing_mm=spacing_mm,
            angle_steps=angle_steps,
            uniform_scale=uniform_scale,
            page_px=page_px,
            progress_cb=cb,
            smooth_iters=smooth_iters,
            bleed_mm=bleed_mm,
        )
        NEST_JOB["positions"] = [
            {"id": p.id, "cx": p.cx, "cy": p.cy, "angle": p.rotation, "scale": p.scale}
            for p in parts
        ]
    except Exception as e:  # noqa: BLE001 - 后台线程异常需要传回前端
        NEST_JOB["error"] = str(e)
    finally:
        NEST_JOB["running"] = False


@app.route("/api/nest", methods=["POST"])
def api_nest():
    """排版。默认同步返回 positions；body 带 "async": true 时启动后台任务，
    立即返回 {"job": true}，进度与结果经 /api/nest_progress 轮询。"""
    d = _require_json("items")
    items = d["items"]
    spacing_mm = float(d.get("spacing_mm", g.PADDING_MM))
    angle_steps = int(d.get("angle_steps", 8))
    uniform_scale = bool(d.get("uniform_scale", False))
    run_async = bool(d.get("async", False))

    parts = []
    for it in items:
        p = PARTS.get(it["id"])
        if p is None:
            continue
        p.scale = float(it.get("scale", 1.0))
        p.rotation = float(it.get("angle", 0.0))
        p.locked = bool(it.get("locked", False))
        parts.append(p)

    page_px = (g.mm_to_px(PAGE_W_MM), g.mm_to_px(PAGE_H_MM))

    if run_async:
        if NEST_JOB["running"]:
            abort(409, description="已有排版任务在执行")
        NEST_JOB.update({"running": True, "progress": 0.0, "positions": None, "error": None})
        threading.Thread(
            target=_run_nest,
            args=(parts, spacing_mm, angle_steps, uniform_scale, OFFSET_MM, page_px,
                  SMOOTH_ITERS, BLEED_MM),
            daemon=True,
        ).start()
        return jsonify({"job": True})

    nesting.nest(
        parts,
        offset_mm=OFFSET_MM,
        spacing_mm=spacing_mm,
        angle_steps=angle_steps,
        uniform_scale=uniform_scale,
        page_px=page_px,
        smooth_iters=SMOOTH_ITERS,
        bleed_mm=BLEED_MM,
    )

    return jsonify({
        "positions": [
            {"id": p.id, "cx": p.cx, "cy": p.cy, "angle": p.rotation, "scale": p.scale}
            for p in parts
        ]
    })


@app.route("/api/nest_progress", methods=["GET"])
def api_nest_progress():
    """轮询排版后台任务：{running, progress, positions?, error?}。
    positions 仅在任务结束后返回一次性读取即可（保留至下次任务覆盖）。"""
    return jsonify({
        "running": NEST_JOB["running"],
        "progress": NEST_JOB["progress"],
        "positions": None if NEST_JOB["running"] else NEST_JOB["positions"],
        "error": NEST_JOB["error"],
    })


@app.route("/api/set_border", methods=["POST"])
def api_set_border():
    global OFFSET_MM
    d = _require_json("offset_mm")
    OFFSET_MM = float(d["offset_mm"])
    return jsonify({"ok": True, "offset_mm": OFFSET_MM})


@app.route("/api/set_smooth", methods=["POST"])
def api_set_smooth():
    """设置全局描边平滑迭代数（0-4 整数，0=不平滑）。"""
    global SMOOTH_ITERS
    d = _require_json("smooth_iters")
    val = int(d["smooth_iters"])
    if val < 0 or val > 4:
        abort(400, description="smooth_iters 必须在 0-4 之间")
    SMOOTH_ITERS = val
    return jsonify({"ok": True, "smooth_iters": SMOOTH_ITERS})


@app.route("/api/set_page", methods=["POST"])
def api_set_page():
    """设置全局纸张尺寸（毫米）。两个字段均必须存在且为正数。"""
    global PAGE_W_MM, PAGE_H_MM
    d = _require_json("w_mm", "h_mm")
    w = float(d["w_mm"])
    h = float(d["h_mm"])
    if w <= 0 or h <= 0:
        abort(400, description="w_mm 和 h_mm 必须大于 0")
    PAGE_W_MM = w
    PAGE_H_MM = h
    return jsonify({"ok": True, "w_mm": PAGE_W_MM, "h_mm": PAGE_H_MM})


@app.route("/api/export", methods=["POST"])
def api_export():
    items = _require_json("items")["items"]
    parts = []
    for it in items:
        p = PARTS.get(it["id"])
        if p is None:
            continue
        p.scale = float(it.get("scale", 1.0))
        p.rotation = float(it.get("angle", 0.0))
        if "cx" in it:
            # 新契约：cx/cy 为视觉中心（物理 px）
            p.cx = float(it["cx"])
            p.cy = float(it["cy"])
            p.x = int(it.get("x", 0))
            p.y = int(it.get("y", 0))
        else:
            # 旧契约：x/y 为左上角，cx/cy 留 None（exporter 内部回退）
            p.x = int(it["x"])
            p.y = int(it["y"])
            p.cx = None
            p.cy = None
        parts.append(p)
    img = exporter.render_png(parts, offset_mm=OFFSET_MM,
                               page_px=(g.mm_to_px(PAGE_W_MM), g.mm_to_px(PAGE_H_MM)),
                               smooth_iters=SMOOTH_ITERS, bleed_mm=BLEED_MM)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", as_attachment=True,
                     download_name="diecut_layout.png")


def main():
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    print("AutoPSTool 已启动: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
