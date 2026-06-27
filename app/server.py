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


@app.route("/api/cut", methods=["POST"])
def api_cut():
    d = _require_json("id", "x1", "y1", "x2", "y2")
    part = PARTS.get(d["id"])
    if part is None:
        return jsonify({"error": "part not found"}), 404
    a, b = part_builder.cut_part(part, (d["x1"], d["y1"]), (d["x2"], d["y2"]))
    del PARTS[d["id"]]
    res = []
    for np_ in (a, b):
        if np_ is None:
            continue
        PARTS[np_.id] = np_
        res.append(part_to_dict(np_))
    return jsonify({"parts": res})


@app.route("/api/nest", methods=["POST"])
def api_nest():
    items = _require_json("items")["items"]
    parts = []
    for it in items:
        p = PARTS.get(it["id"])
        if p is None:
            continue
        p.scale = it.get("scale", 1.0)
        parts.append(p)
    nesting.nest(parts)
    return jsonify({"positions": [{"id": p.id, "x": p.x, "y": p.y} for p in parts]})


@app.route("/api/set_border", methods=["POST"])
def api_set_border():
    global OFFSET_MM
    d = _require_json("offset_mm")
    OFFSET_MM = float(d["offset_mm"])
    return jsonify({"ok": True, "offset_mm": OFFSET_MM})


@app.route("/api/export", methods=["POST"])
def api_export():
    items = _require_json("items")["items"]
    parts = []
    for it in items:
        p = PARTS.get(it["id"])
        if p is None:
            continue
        p.x, p.y, p.scale = int(it["x"]), int(it["y"]), it.get("scale", 1.0)
        parts.append(p)
    img = exporter.render_png(parts, offset_mm=OFFSET_MM)
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
