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
