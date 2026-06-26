"""Flask 后端：托管前端、抠图/切割/排版/导出 API、内存会话、浏览器自启。"""
import os
import io
import base64
import threading
import webbrowser

import cv2
import numpy as np
from flask import Flask, request, jsonify, send_file, send_from_directory

from app import segmentation, part_builder, nesting, exporter
from app.models import Part

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
app = Flask(__name__, static_folder=None)

PARTS = {}  # id -> Part（单用户本地工具，内存会话足够）


def _decode_image(b64: str):
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    data = base64.b64decode(b64)
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # 统一 BGR 3 通道
    return img


def part_to_dict(part: Part) -> dict:
    """零件图片层编码为 base64 PNG 给前端。"""
    rgba = part.image_layer
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    b64 = base64.b64encode(buf).decode()
    return {
        "id": part.id,
        "image_base64": "data:image/png;base64," + b64,
        "w": part.w, "h": part.h,
        "contour": part.contour,
    }


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/<path:fname>")
def static_files(fname):
    return send_from_directory(WEB_DIR, fname)


@app.route("/api/segment", methods=["POST"])
def api_segment():
    img = _decode_image(request.json["image_base64"])
    subjects = segmentation.segment_subjects(img)
    out = []
    for s in subjects:
        part = part_builder.build_part(img, s["mask"])
        PARTS[part.id] = part
        out.append(part_to_dict(part))
    return jsonify({"parts": out})


@app.route("/api/cut", methods=["POST"])
def api_cut():
    d = request.json
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
    items = request.json["items"]
    parts = []
    for it in items:
        p = PARTS.get(it["id"])
        if p is None:
            continue
        p.scale = it.get("scale", 1.0)
        parts.append(p)
    nesting.nest(parts)
    return jsonify({"positions": [{"id": p.id, "x": p.x, "y": p.y} for p in parts]})


@app.route("/api/export", methods=["POST"])
def api_export():
    items = request.json["items"]
    parts = []
    for it in items:
        p = PARTS.get(it["id"])
        if p is None:
            continue
        p.x, p.y, p.scale = int(it["x"]), int(it["y"]), it.get("scale", 1.0)
        parts.append(p)
    img = exporter.render_png(parts)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", as_attachment=True,
                     download_name="diecut_layout.png")


def main():
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    print("🚀 AutoPSTool 已启动: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
