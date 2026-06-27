import base64
import io
import numpy as np
import cv2
from app import server
from app.models import Part


def _png_b64_white_circle():
    img = np.full((300, 300, 3), 255, np.uint8)
    cv2.circle(img, (150, 150), 70, (0, 140, 200), -1)
    ok, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf).decode()


def _fake_part(pid):
    layer = np.zeros((100, 100, 4), np.uint8)
    layer[:, :, 3] = 255
    mask = np.full((100, 100), 255, np.uint8)
    contour = [(0, 0), (99, 0), (99, 99), (0, 99)]
    return Part(id=pid, image_layer=layer, mask=mask, contour=contour)


def setup_function():
    server.PARTS.clear()


def test_index_served():
    client = server.app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200


def test_nest_returns_positions():
    server.PARTS["a"] = _fake_part("a")
    server.PARTS["b"] = _fake_part("b")
    client = server.app.test_client()
    resp = client.post("/api/nest", json={"items": [{"id": "a", "scale": 1.0},
                                                      {"id": "b", "scale": 1.0}]})
    assert resp.status_code == 200
    pos = {p["id"]: p for p in resp.get_json()["positions"]}
    assert pos["a"]["x"] >= 0 and pos["b"]["x"] >= 0


def test_export_returns_png():
    p = _fake_part("a"); p.x, p.y = 50, 50
    server.PARTS["a"] = p
    client = server.app.test_client()
    resp = client.post("/api/export", json={"items": [{"id": "a", "x": 50, "y": 50, "scale": 1.0}]})
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"


def test_set_border_updates_session():
    client = server.app.test_client()
    r = client.post("/api/set_border", json={"offset_mm": 5.5})
    assert r.status_code == 200
    assert r.get_json()["offset_mm"] == 5.5
    assert server.OFFSET_MM == 5.5


def test_set_page_updates_session():
    """POST /api/set_page 更新全局 PAGE_W_MM / PAGE_H_MM；非法请求返回 400。"""
    client = server.app.test_client()
    # 正常更新
    r = client.post("/api/set_page", json={"w_mm": 148, "h_mm": 210})
    assert r.status_code == 200, f"期望 200，实际 {r.status_code}"
    data = r.get_json()
    assert data["ok"] is True
    assert server.PAGE_W_MM == 148
    assert server.PAGE_H_MM == 210
    # 缺少字段 → 400
    r2 = client.post("/api/set_page", json={"w_mm": 210})
    assert r2.status_code == 400, f"缺 h_mm 应返回 400，实际 {r2.status_code}"
    # 非正数 → 400
    r3 = client.post("/api/set_page", json={"w_mm": 0, "h_mm": 210})
    assert r3.status_code == 400, f"w_mm=0 应返回 400，实际 {r3.status_code}"


def test_segment_returns_subject_fields():
    import numpy as np, cv2, base64
    img = np.full((300, 300, 3), 255, np.uint8)
    cv2.circle(img, (150, 150), 80, (0, 140, 200), -1)
    ok, buf = cv2.imencode(".png", img)
    b64 = "data:image/png;base64," + base64.b64encode(buf).decode()
    server.PARTS.clear()
    client = server.app.test_client()
    r = client.post("/api/segment", json={"image_base64": b64})
    assert r.status_code == 200
    parts = r.get_json()["parts"]
    assert parts and parts[0]["kind"] == "parametric"
    assert parts[0]["subject_outline"] and parts[0]["subject_image"].startswith("data:image/png")
