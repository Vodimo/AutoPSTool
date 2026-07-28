import numpy as np
import cv2
from app import part_builder as pb
from app.models import Part
from tests.conftest import make_white_bg_image, make_blob_mask


def _single_subject():
    img = make_white_bg_image(size=(400, 400), centers=((200, 200),), radius=60)
    mask = make_blob_mask(size=(400, 400), centers=((200, 200),), radius=60)
    return img, mask


def test_build_part_returns_part_with_rgba_layer():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    assert isinstance(part, Part)
    assert part.image_layer.shape[2] == 4           # RGBA
    assert part.w > 0 and part.h > 0


def test_build_part_white_border_grows_bbox():
    """白边应让零件比原主体外扩约 offset_px。"""
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    # 原主体直径 ~120px，外扩 2mm=20px 两侧 -> 约 160px
    assert part.w >= 150


def test_build_part_background_transparent():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    # 角落像素应透明（alpha=0）
    assert part.image_layer[0, 0, 3] == 0


def test_build_part_contour_nonempty():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    assert len(part.contour) >= 3


def test_cut_part_makes_two_overlapping_parts():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    # 竖直切一刀（从上到下）
    midx = part.w // 2
    a, b = pb.cut_part(part, (midx, 0), (midx, part.h))
    # 两块各自有内容
    assert a.image_layer[:, :, 3].max() == 255
    assert b.image_layer[:, :, 3].max() == 255
    # 重叠：两块宽度之和应大于原宽（因为出血重叠）
    assert (a.w + b.w) > part.w


def test_build_part_mask_shape_and_values():
    """part.mask 应与 image_layer 同尺寸，且取值仅为 0/255。"""
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    assert part.mask.shape == (part.h, part.w)
    assert set(np.unique(part.mask)).issubset({0, 255})


def test_cut_part_zero_length_line_no_cut():
    """退化（零长）切割线：原样返回，不切出两份重叠整图。"""
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    midx = part.w // 2
    a, b = pb.cut_part(part, (midx, 10), (midx, 10))
    assert a is part        # 原零件原样返回
    assert b is None        # 没有第二块


def test_build_part_has_vector_dieline():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    assert part.dieline_path                 # 非空
    assert "C" in part.dieline_path.upper()  # 平滑贝塞尔


def test_cut_pieces_have_vector_dieline():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    midx = part.w // 2
    a, b = pb.cut_part(part, (midx, 0), (midx, part.h))
    assert a.dieline_path and b.dieline_path


def test_build_part_has_subject_image_and_outline():
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    # 主体图：透明底、RGBA（帧已含 SUBJECT_MARGIN，不再要求比 image_layer 小）
    assert part.subject_image is not None
    assert part.subject_image.shape[2] == 4
    assert part.subject_image[0, 0, 3] == 0          # 角落透明
    # 主体轮廓：非空且含曲线
    assert part.subject_outline and "C" in part.subject_outline.upper()


def test_build_part_has_source_and_editmask():
    """build_part 应产出 source_bgr 与 edit_mask，且它们与 subject_image 同帧。"""
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="p1")
    assert part.source_bgr is not None
    assert part.edit_mask is not None
    # edit_mask 与 subject_image 同尺寸
    assert part.edit_mask.shape[:2] == part.subject_image.shape[:2]


def test_apply_brush_erase_split():
    """擦断哑铃 mask 的细桥 → apply_brush 返回 2 个零件。"""
    # 构造哑铃：两个圆 + 细桥
    size = (300, 400)
    h, w = size
    mask = np.zeros((h, w), np.uint8)
    cv2.circle(mask, (80, 150), 60, 255, -1)          # 左圆
    cv2.circle(mask, (320, 150), 60, 255, -1)          # 右圆
    cv2.rectangle(mask, (80, 140), (320, 160), 255, -1)  # 细桥（高 20px）

    img = np.full((h, w, 3), 255, np.uint8)  # 白底图

    part = pb.build_part(img, mask, offset_mm=2.0)

    # 笔迹 stroke：覆盖桥中央，与 edit_mask 同尺寸
    em_h, em_w = part.edit_mask.shape
    stroke = np.zeros((em_h, em_w), np.uint8)
    # 桥在 padded 帧中央区域；画一个足够宽的白色矩形确保覆盖桥
    mid_x = em_w // 2
    cv2.rectangle(stroke, (mid_x - 20, 0), (mid_x + 20, em_h), 255, -1)

    results = pb.apply_brush(part, stroke, "erase")
    assert len(results) == 2, f"擦断细桥应分裂为 2 块，实际返回 {len(results)} 块"
    # 帧偏移：两块的新主体帧原点应分别落在旧帧左/右半区（对齐回原位用）
    offs = sorted(dx for _, (dx, _) in results)
    assert offs[0] < offs[1], "两块的 frame_dx 应不同（左右两块）"


def test_apply_brush_add_grows():
    """'add' 模式把笔迹区域加入 mask，分量面积应增大。"""
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0)

    em_h, em_w = part.edit_mask.shape
    orig_area = int(np.count_nonzero(part.edit_mask))

    # 先擦掉一块(左半)
    erase_stroke = np.zeros((em_h, em_w), np.uint8)
    erase_stroke[:, :em_w // 2] = 255
    erased = [p for p, _ in pb.apply_brush(part, erase_stroke, "erase")]
    assert len(erased) >= 1

    # 再加回(同一笔迹)→ 面积应大于擦后
    if len(erased) == 1:
        erased_part = erased[0]
        erased_area = int(np.count_nonzero(erased_part.edit_mask))
        add_stroke = np.zeros((erased_part.edit_mask.shape[0], erased_part.edit_mask.shape[1]), np.uint8)
        # 对 erased_part 的帧，在右侧加白笔迹
        add_stroke[:, erased_part.edit_mask.shape[1] // 2:] = 255
        added = [p for p, _ in pb.apply_brush(erased_part, add_stroke, "add")]
        added_area = sum(int(np.count_nonzero(p.edit_mask)) for p in added)
        assert added_area > erased_area, "add 笔迹后面积应增大"


def test_cut_parametric_pieces_and_die_geometry():
    """参数化切割：竖切过圆心 → 两块参数化零件；刀模线正好落在切割线上（切口平直），
    白边加大时切口边界不变（白边实时可调的几何基础）。"""
    from app import border, geometry as g
    img, mask = _single_subject()
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="pc")
    fh, fw = part.edit_mask.shape
    mid = fw / 2.0

    results = pb.cut_part_parametric(part, (mid, 0), (mid, fh))
    assert len(results) == 2, f"竖切过心应得两块，实际 {len(results)}"

    offset_px = g.mm_to_px(2.0)
    for piece, (fdx, fdy) in results:
        assert piece.subject_outline, "切块应仍为参数化零件"
        assert piece.cut_planes and len(piece.cut_planes) == 1, "切块应带 1 个切割平面"
        die = border.dieline_polygon(piece.subject_outline, offset_px,
                                     cut_planes=piece.cut_planes)
        assert not die.is_empty
        # 切线在新帧的 x 坐标；刀模在切口侧应恰好止于切线（不越线、也不留白边）
        line_x = mid - fdx
        minx, _, maxx, _ = die.bounds
        cut_side_over = min(abs(maxx - line_x), abs(line_x - minx))
        assert cut_side_over <= 2, \
            f"刀模线应落在切割线上，实际越线/退让 {cut_side_over:.1f}px"

        # 白边加大 → 主体侧扩张，切口边界仍在切线上
        die_big = border.dieline_polygon(piece.subject_outline, g.mm_to_px(5.0),
                                         cut_planes=piece.cut_planes)
        b0, b1 = die.bounds, die_big.bounds
        assert die_big.area > die.area, "白边加大刀模应变大（白边实时可调）"
        if maxx - line_x < line_x - minx:   # 切口在右侧（保留左半）
            assert abs(b1[2] - b0[2]) <= 2, "切口边界不应随白边变化"
        else:
            assert abs(b1[0] - b0[0]) <= 2, "切口边界不应随白边变化"

    # 两块刀模映射回原帧后应彼此不重叠（切口贴合，无出血重叠带）
    (pa, (adx, ady)), (pb_, (bdx, bdy)) = results
    import shapely.affinity
    da = shapely.affinity.translate(
        border.dieline_polygon(pa.subject_outline, offset_px,
                               cut_planes=pa.cut_planes), adx, ady)
    db = shapely.affinity.translate(
        border.dieline_polygon(pb_.subject_outline, offset_px,
                               cut_planes=pb_.cut_planes), bdx, bdy)
    assert da.intersection(db).area <= 4.0, "两块刀模应沿切线贴合，不重叠"


def test_cut_die_is_flat_at_line():
    """切口渲染回归：刀模线外无任何内容（无出血、无白边溢出），切口平直。"""
    from app import geometry as gg, exporter
    img = np.full((400, 400, 3), 255, np.uint8)
    cv2.circle(img, (200, 200), 130, (200, 120, 0), -1)      # 蓝色圆盘
    mask = np.zeros((400, 400), np.uint8)
    cv2.circle(mask, (200, 200), 130, 255, -1)
    part = pb.build_part(img, mask, offset_mm=2.0, part_id="w")

    fh, fw = part.edit_mask.shape
    pieces = pb.cut_part_parametric(part, (fw / 2, 0), (fw / 2, fh))
    assert len(pieces) == 2
    piece = pieces[0][0]

    tile = exporter._build_tile(piece, gg.mm_to_px(2.0), 0)[0]
    arr = np.array(tile.convert("RGBA"))
    row = arr[tile.height // 2]
    # 最右侧的洋红刀模线之后不应再有不透明像素（出血已移除）
    die_x = max(i for i, px in enumerate(row)
                if px[3] > 128 and px[0] > 200 and px[1] < 60 and px[2] > 200)
    beyond = sum(1 for px in row[die_x + 1:] if px[3] > 128)
    assert beyond <= 2, f"刀模线外不应有内容，实际 {beyond}px"

    # 切口侧的主体色应一直延伸到刀模线（切口无白边）
    near = row[die_x - 6:die_x - 1]
    blue = sum(1 for px in near if px[3] > 128 and px[2] > 120 and px[0] < 120)
    assert blue >= 3, "切口处应是主体画面直抵刀模线，不应有白边"


def test_materialize_parametric_then_cut():
    """参数化零件实体化后可正常切割，切出的两块为固定零件(无 subject_outline)。"""
    img, mask = _single_subject()
    p = pb.build_part(img, mask, offset_mm=2.0, part_id="mat1")
    # build_part 产出参数化零件
    assert p.subject_image is not None
    # 实体化：产出含 image_layer 和 mask 的新零件
    mp = pb.materialize_parametric(p, offset_mm=2.0)
    assert mp.mask is not None and mp.image_layer is not None
    # 切割实体化后的零件
    a, b = pb.cut_part(mp, (mp.w // 2, 0), (mp.w // 2, mp.h))
    # 两块均非空，各有刀模路径
    assert a is not None and b is not None
    assert a.dieline_path and b.dieline_path
    # 切割产出的两块为固定零件（_rebuild_from_die 不设 subject_outline）
    assert a.subject_outline == ""
    assert b.subject_outline == ""
