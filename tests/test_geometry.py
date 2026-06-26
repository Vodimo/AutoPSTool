from app import geometry as g


def test_constants():
    assert g.PIXEL_RATIO == 10
    assert g.A4_WIDTH_PX == 2100
    assert g.A4_HEIGHT_PX == 2970


def test_mm_to_px():
    assert g.mm_to_px(1) == 10
    assert g.mm_to_px(2.0) == 20
    assert isinstance(g.mm_to_px(2.0), int)


def test_px_to_mm():
    assert g.px_to_mm(20) == 2.0
