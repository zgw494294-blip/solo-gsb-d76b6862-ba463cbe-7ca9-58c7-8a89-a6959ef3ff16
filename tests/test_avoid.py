"""双面点阵避让引擎测试（含与独立朴素枚举的随机对照）。"""

import random

import pytest

from app.avoid import avoid, _dots_of
from app.braille import ValidationError, typeset


# ---------------------------------------------------------------------------
# 独立朴素参照：逐位移、逐点对直接计数（仅用于小输入对照）
# ---------------------------------------------------------------------------

def _ref_dots(result):
    out = []
    for r, line in enumerate(result["lines"]):
        for c, cell in enumerate(line["cells"]):
            for d in cell["dots"]:
                x = 60 * c + (25 if d >= 4 else 0)
                y = 100 * r + 25 * ((d - 1) if d <= 3 else (d - 4))
                out.append((x, y, r, c, d))
    return out


def _reference(front, back, width, min_distance):
    """返回 ((dx, dy), 冲突点对集合)，点对以 (正面行列点, 反面行列点) 表示。"""
    t = round(min_distance * 10)
    fd = _ref_dots(typeset(front, width))
    bd = _ref_dots(typeset(back, width))
    mirror = 60 * (width - 1) + 25
    best_key = None
    best = None
    for dx in range(-30, 31):
        for dy in range(-30, 31):
            pairs = set()
            for f in fd:
                for b in bd:
                    ddx = f[0] - (mirror - b[0] + dx)
                    ddy = f[1] - (b[1] + dy)
                    if ddx * ddx + ddy * ddy < t * t:
                        pairs.add(((f[2], f[3], f[4]), (b[2], b[3], b[4])))
            key = (len(pairs), dx * dx + dy * dy, dx, dy)
            if best_key is None or key < best_key:
                best_key = key
                best = ((dx / 10, dy / 10), pairs)
    return best


def _check_against_reference(front, back, width, min_distance):
    r = avoid(front, back, width, min_distance)
    (rdx, rdy), rpairs = _reference(front, back, width, min_distance)
    assert (r["dx"], r["dy"]) == (rdx, rdy)
    assert r["conflict_count"] == len(rpairs)
    eng = {
        ((c["front"]["row"], c["front"]["cell"], c["front"]["dot"]),
         (c["back"]["row"], c["back"]["cell"], c["back"]["dot"]))
        for c in r["conflicts"]
    }
    assert eng == rpairs
    assert r["feasible"] == (r["conflict_count"] == 0)
    return r


# ---------------------------------------------------------------------------
# 凸点坐标
# ---------------------------------------------------------------------------

def test_dot_coordinates_single_cell():
    # a＝点1：零基行格 (0,0) -> (0, 0)，单位 0.1 毫米
    assert _dots_of(typeset("a", 10)) == [(0, 0, 0, 0, 1)]


def test_dot_coordinates_both_columns_and_rows():
    # q＝点12345，第二行第二格 (r=1, c=1)
    dots = _dots_of(typeset("a\nbq", 10))
    by_key = {(r, c, d): (x, y) for x, y, r, c, d in dots}
    assert by_key[(1, 1, 1)] == (60, 100)        # 点1：(6c, 10r)
    assert by_key[(1, 1, 2)] == (60, 125)        # 点2：(6c, 10r+2.5)
    assert by_key[(1, 1, 3)] == (60, 150)        # 点3：(6c, 10r+5)
    assert by_key[(1, 1, 4)] == (85, 100)        # 点4：(6c+2.5, 10r)
    assert by_key[(1, 1, 5)] == (85, 125)        # 点5：(6c+2.5, 10r+2.5)


def test_only_raised_dots_counted():
    # 词间格（无凸点）不产生坐标；空段仍占一行行距
    dots = _dots_of(typeset("a b", 10))
    assert {(r, c) for _, _, r, c, _ in dots} == {(0, 0), (0, 2)}
    dots = _dots_of(typeset("a\n\nb", 10))
    assert {r for _, _, r, _, _ in dots} == {0, 2}  # 空段占第 2 行（零基）


# ---------------------------------------------------------------------------
# 位移择优
# ---------------------------------------------------------------------------

def test_zero_conflict_prefers_origin():
    r = avoid("a", "a", 10, 1.0)
    assert r["feasible"] is True
    assert r["conflict_count"] == 0
    assert r["conflicts"] == []
    assert (r["dx"], r["dy"]) == (0.0, 0.0)  # 并列零冲突时 dx²+dy² 最小


def test_tie_break_by_shift_then_dx():
    # 正面点 (0,0)；反面末格 c＝点1,4，镜像后落在 (2.5,0) 与 (0,0)。
    # 点距 1.0mm：dx²+dy²<100 或 (dx+25)²+dy²<100（0.1mm 单位）即冲突，
    # 零冲突的最小 dx²+dy²＝100，并列中 dx 最小者为 (-10, 0)。
    r = avoid("a", "aaaaaaaaac", 10, 1.0)
    assert r["feasible"] is True
    assert (r["dx"], r["dy"]) == (-1.0, 0.0)


def test_unavoidable_conflicts_reported():
    # 双面同一行满排 y（点13456）、点距 3.0mm：任何位移都有冲突
    r = avoid("yyyyyyyyyy", "yyyyyyyyyy", 10, 3.0)
    assert r["feasible"] is False
    assert r["conflict_count"] == 37
    assert len(r["conflicts"]) == 37
    pair = r["conflicts"][0]
    assert pair["front"]["face"] == "front"
    assert pair["back"]["face"] == "back"
    assert set(pair["front"]) == {"face", "row", "cell", "dot"}
    assert set(pair["back"]) == {"face", "row", "cell", "dot"}
    # 冲突点对确实满足距离条件（放大 10 倍整数平方，镜像＋位移后比较）
    mirror = 60 * (10 - 1) + 25
    dots = {"front": _dots_of(r["front"]), "back": _dots_of(r["back"])}
    pos = {
        face: {(d[2], d[3], d[4]): (d[0], d[1]) for d in dots[face]}
        for face in ("front", "back")
    }
    dx, dy = round(r["dx"] * 10), round(r["dy"] * 10)
    for c in r["conflicts"]:
        fx, fy = pos["front"][(c["front"]["row"], c["front"]["cell"], c["front"]["dot"])]
        bx, by = pos["back"][(c["back"]["row"], c["back"]["cell"], c["back"]["dot"])]
        mx, my = mirror - bx + dx, by + dy
        assert (fx - mx) ** 2 + (fy - my) ** 2 < 30 ** 2


def test_result_embeds_typeset_and_counts():
    r = avoid("Hello 2026", "abc 007", 16, 1.5)
    assert r["width"] == 16
    assert r["min_distance"] == 1.5
    assert r["front"]["braille_text"] == typeset("Hello 2026", 16)["braille_text"]
    assert r["back"]["braille_text"] == typeset("abc 007", 16)["braille_text"]
    assert r["front_dots"] == len(_dots_of(r["front"]))
    assert r["back_dots"] == len(_dots_of(r["back"]))


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------

def test_min_distance_bounds_and_one_decimal():
    for ok in (0.1, 1.0, 2, 2.5, 3.0):
        assert avoid("a", "a", 10, ok)["min_distance"] == round(ok * 10) / 10
    for bad in (0, 0.05, 0.15, 2.55, 3.1, -1.0, 4):
        with pytest.raises(ValidationError) as ei:
            avoid("a", "a", 10, bad)
        assert ei.value.errors[0]["code"] == "bad_min_distance"


def test_text_errors_carry_face():
    with pytest.raises(ValidationError) as ei:
        avoid("ab\tc", "ok", 10, 1.0)
    err = ei.value.errors[0]
    assert err["code"] == "illegal_char"
    assert err["face"] == "front"
    assert (err["line"], err["col"]) == (1, 3)

    with pytest.raises(ValidationError) as ei:
        avoid("ok", "ab\tc", 10, 1.0)
    assert ei.value.errors[0]["face"] == "back"


def test_bad_width_reported_once_without_face():
    with pytest.raises(ValidationError) as ei:
        avoid("a", "b", 41, 1.0)
    assert [e["code"] for e in ei.value.errors] == ["bad_width"]
    assert "face" not in ei.value.errors[0]


def test_both_sides_errors_collected():
    with pytest.raises(ValidationError) as ei:
        avoid("a1", "b2", 10, 1.0)
    faces = sorted(e["face"] for e in ei.value.errors if e["code"] == "mixed_word")
    assert faces == ["back", "front"]


# ---------------------------------------------------------------------------
# 与独立朴素枚举的随机对照
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("front,back,width,md", [
    ("Hello", "world", 10, 1.0),
    ("Hello 2026", "abc 007", 16, 1.5),
    ("q", "q", 10, 3.0),
    ("yyyyyyyyyy", "qqqqqqqqqq", 10, 2.5),
    ("The quick brown fox", "pack my box", 20, 0.1),
    ("a\n\nb", "c\n\nd", 10, 2.0),
    ("Abc Def", "gHi Jkl", 12, 0.7),
])
def test_fixed_cases_match_reference(front, back, width, md):
    _check_against_reference(front, back, width, md)


def test_random_small_cases_match_reference():
    random.seed(20260927)
    for _ in range(8):
        def rnd_text():
            words = []
            for _ in range(random.randint(1, 3)):
                n = random.randint(1, 6)
                words.append("".join(random.choice("abcdqyz") for _ in range(n)))
            return " ".join(words)

        md = random.choice([0.1, 0.5, 1.0, 1.5, 2.0, 3.0])
        _check_against_reference(rnd_text(), rnd_text(), 10, md)
