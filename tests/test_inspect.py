"""压印点位复核引擎测试（含与独立朴素枚举的随机对照）。"""

import random

import pytest

from app.avoid import _dots_of
from app.braille import ValidationError, typeset
from app.inspect import (
    _candidate_groups,
    _match_at,
    _parse_points,
    inspect,
)


# ---------------------------------------------------------------------------
# 独立朴素参照：逐位移、逐点对直接贪心配对（仅用于小输入对照）
# ---------------------------------------------------------------------------

def _reference(text, width, points_text):
    """返回 (理论点, 实测点, (dx, dy, 距离平方和, [(理论序号, 实测序号, d2)]))。"""
    measured = _parse_points(points_text)
    theory = _dots_of(typeset(text, width))
    best_key = None
    best = None
    for dx in range(-30, 31):
        for dy in range(-30, 31):
            edges = []
            for mi, (mx, my) in enumerate(measured):
                for ti, t in enumerate(theory):
                    d2 = (t[0] - mx - dx) ** 2 + (t[1] - my - dy) ** 2
                    if d2 <= 16:  # 距离 ≤ 0.4 毫米（0.1 毫米单位的平方）
                        edges.append((d2, mi, ti))
            edges.sort()  # (距离平方, 实测输入序, 理论序号) 升序贪心
            used_t, used_m = set(), set()
            matches = []
            sse = 0
            for d2, mi, ti in edges:
                if ti in used_t or mi in used_m:
                    continue
                used_t.add(ti)
                used_m.add(mi)
                matches.append((ti, mi, d2))
                sse += d2
            key = (-len(matches), sse, dx * dx + dy * dy, dx, dy)
            if best_key is None or key < best_key:
                best_key = key
                best = (dx, dy, sse, matches)
    return theory, measured, best


def _check_against_reference(text, width, points_text):
    r = inspect(text, width, points_text)
    theory, measured, (rdx, rdy, rsse, rmatches) = _reference(text, width, points_text)
    assert (round(r["dx"] * 10), round(r["dy"] * 10)) == (rdx, rdy)
    assert r["matched"] == len(rmatches)
    assert round(r["sse"] * 100) == rsse
    eng = {(m["row"], m["cell"], m["dot"], m["line"]) for m in r["matches"]}
    ref = {
        (theory[ti][2], theory[ti][3], theory[ti][4], mi + 1)
        for ti, mi, _ in rmatches
    }
    assert eng == ref
    assert r["missing"] == len(theory) - len(rmatches)
    assert r["extra"] == len(measured) - len(rmatches)
    assert r["perfect"] == (len(rmatches) == len(theory) == len(measured))
    assert len(r["missing_dots"]) == r["missing"]
    assert len(r["extra_points"]) == r["extra"]
    return r


# ---------------------------------------------------------------------------
# 实测点解析
# ---------------------------------------------------------------------------

def test_parse_points_scales_to_tenth_mm():
    assert _parse_points("0,0") == [(0, 0)]
    assert _parse_points("12.3,4.5\n-3,+2.5\n.7,-.8\n6,9.0") == [
        (123, 45), (-30, 25), (7, -8), (60, 90),
    ]


def test_parse_points_empty_and_trailing_newline():
    assert _parse_points("") == []
    assert _parse_points("0,0\n") == [(0, 0)]  # 结尾单个换行不产生空尾行


@pytest.mark.parametrize("src,line,col", [
    ("0,0\n\n1,1", 2, 1),        # 空行
    ("0 0", 1, 1),               # 缺少逗号
    ("1,,2", 1, 1),              # 多余逗号
    ("1,", 1, 3),                # 空坐标（逗号在行尾，定位到行尾）
    ("0,0\n1.25,3", 2, 1),       # 两位小数
    ("0,0\n1,x", 2, 3),          # 非数值（第二个坐标）
])
def test_parse_points_errors_located(src, line, col):
    with pytest.raises(ValidationError) as ei:
        _parse_points(src)
    err = ei.value.errors[0]
    assert err["code"] == "bad_points"
    assert err["field"] == "points"
    assert (err["line"], err["col"]) == (line, col)
    assert err["length"] >= 1


def test_parse_points_crlf_normalized():
    assert _parse_points("1,2\r\n3,4") == [(10, 20), (30, 40)]


def test_too_many_points():
    with pytest.raises(ValidationError) as ei:
        _parse_points("\n".join(["0,0"] * 401))
    assert ei.value.errors[0]["code"] == "too_many_points"


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------

def test_text_limit_is_100():
    assert inspect("a" * 100, 10, "")["theory_dots"] > 0
    with pytest.raises(ValidationError) as ei:
        inspect("a" * 101, 10, "")
    assert [e["code"] for e in ei.value.errors] == ["too_long"]
    assert "100" in ei.value.errors[0]["message"]


def test_text_errors_carry_text_field():
    with pytest.raises(ValidationError) as ei:
        inspect("ab\tc", 10, "")
    err = ei.value.errors[0]
    assert err["code"] == "illegal_char"
    assert err["field"] == "text"
    assert (err["line"], err["col"]) == (1, 3)


def test_text_and_points_errors_collected_together():
    with pytest.raises(ValidationError) as ei:
        inspect("a1", 10, "x,y")
    by_field = {}
    for err in ei.value.errors:
        by_field.setdefault(err["field"], set()).add(err["code"])
    assert by_field["text"] == {"mixed_word"}
    assert by_field["points"] == {"bad_points"}


def test_bad_width():
    with pytest.raises(ValidationError) as ei:
        inspect("a", 41, "")
    assert [e["code"] for e in ei.value.errors] == ["bad_width"]


# ---------------------------------------------------------------------------
# 配对与位移择优
# ---------------------------------------------------------------------------

def test_shift_recovers_offset():
    # 实测点是理论点 (0,0) 平移 (+0.1,+0.2) 的结果：应识别出反向位移
    r = inspect("a", 10, "0.1,0.2")
    assert (r["dx"], r["dy"]) == (-0.1, -0.2)
    assert r["matched"] == 1
    assert r["perfect"] is True
    assert r["sse"] == 0
    assert r["missing_dots"] == []
    assert r["extra_points"] == []


def test_empty_points_all_missing():
    r = inspect("a", 10, "")
    assert r["matched"] == 0
    assert r["missing"] == 1
    assert r["missing_dots"] == [{"row": 0, "cell": 0, "dot": 1}]
    assert r["extra"] == 0
    assert (r["dx"], r["dy"]) == (0.0, 0.0)  # 并列时 dx²+dy² 最小


def test_missing_theory_dot_is_zero_based():
    # ab：理论点 (0,0,1)＝(0,0)、(0,1,1)＝(6,0)、(0,1,2)＝(6,2.5) 毫米；
    # 实测只覆盖前两点，第三点缺失（行、格、点号均为零基）
    r = inspect("ab", 10, "0,0\n6,0")
    assert r["matched"] == 2
    assert r["missing_dots"] == [{"row": 0, "cell": 1, "dot": 2}]
    assert r["extra"] == 0


def test_extra_measured_point_reports_input_line():
    r = inspect("a", 10, "0,0\n5,5")
    assert r["matched"] == 1
    assert r["extra_points"] == [{"line": 2, "x": 5.0, "y": 5.0}]
    assert r["missing"] == 0


def test_nearest_candidate_wins_for_same_theory_dot():
    # 两个实测点都在理论点 (0,0) 的 0.4 毫米内：取最近的（第 1 行 0.1 毫米处）
    r = inspect("a", 10, "0.1,0\n0.3,0")
    assert r["matched"] == 1
    assert [m["line"] for m in r["matches"]] == [1]
    assert [p["line"] for p in r["extra_points"]] == [2]


def test_same_distance_earlier_input_wins():
    # 两个实测点与理论点等距（坐标相同）：取输入顺序较早者
    r = inspect("a", 10, "0,0\n0,0")
    assert (r["dx"], r["dy"]) == (0.0, 0.0)
    assert [m["line"] for m in r["matches"]] == [1]
    assert [p["line"] for p in r["extra_points"]] == [2]


def test_shift_tie_prefers_smaller_norm_then_dx():
    # 两个实测点各自只能单独对齐：dx=±0.3 并列时取 dx 较小者
    r = inspect("a", 10, "0.3,0\n-0.3,0")
    assert (r["dx"], r["dy"]) == (-0.3, 0.0)
    assert [m["line"] for m in r["matches"]] == [1]

    # dx²+dy² 同为 8 时先比 dx：(-0.2,-0.2) 胜 (0.2,0.2)
    r = inspect("a", 10, "0.2,0.2\n-0.2,-0.2")
    assert (r["dx"], r["dy"]) == (-0.2, -0.2)


def test_shift_tie_prefers_smaller_dy():
    r = inspect("a", 10, "0,0.3\n0,-0.3")
    assert (r["dx"], r["dy"]) == (0.0, -0.3)
    assert [m["line"] for m in r["matches"]] == [1]


def test_match_radius_boundary():
    # 距离 0.4 毫米（平方 16）可配对，0.5 毫米（平方 25）不可
    theory = [(0, 0, 0, 0, 1)]
    groups = _candidate_groups(theory, [(4, 0)])
    assert _match_at(groups, 0, 0, 1, 1)[0] == 1
    groups = _candidate_groups(theory, [(5, 0)])
    assert _match_at(groups, 0, 0, 1, 1)[0] == 0


def test_perfect_match_all_dots():
    result = typeset("Hi 26", 10)
    points = "\n".join(
        f"{x / 10},{y / 10}" for x, y, *_ in _dots_of(result)
    )
    r = inspect("Hi 26", 10, points)
    assert r["perfect"] is True
    assert (r["dx"], r["dy"]) == (0.0, 0.0)
    assert r["matched"] == r["theory_dots"] == r["measured_dots"] > 0
    assert r["sse"] == 0


def test_result_embeds_layout_and_echoes_points():
    r = inspect("Hi", 10, "0,0\n1.5,2.5\n0,0")
    assert r["layout"]["braille_text"] == typeset("Hi", 10)["braille_text"]
    assert r["width"] == 10
    assert r["points"] == [
        {"line": 1, "x": 0.0, "y": 0.0},
        {"line": 2, "x": 1.5, "y": 2.5},
        {"line": 3, "x": 0.0, "y": 0.0},
    ]
    assert r["theory_dots"] == len(_dots_of(r["layout"]))
    assert r["measured_dots"] == 3
    # 缺失点按理论点顺序（行、格、点号）排列，多余点按输入行号排列
    assert r["missing_dots"] == sorted(
        r["missing_dots"], key=lambda d: (d["row"], d["cell"], d["dot"])
    )
    assert [p["line"] for p in r["extra_points"]] == sorted(
        p["line"] for p in r["extra_points"]
    )


# ---------------------------------------------------------------------------
# 与独立朴素枚举的对照
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,width,points", [
    ("a", 10, "0.1,0.2"),
    ("ab", 10, "0,0\n0,0\n0.4,2.5"),
    ("ab", 10, "0,0\n0,0\n0.5,2.5"),
    ("q", 10, "0.1,0\n-0.2,0.3\n0,5.1\n6,0\n2.5,2.4"),
    ("a b", 10, ""),
    ("Hi 26", 10, "0.3,-0.1\n6.3,-0.1\n0.3,2.4\n6.3,2.4\n18.3,-0.1\n24.3,-0.1"),
    ("z q", 12, "0,0.2\n2.5,0\n0,2.7\n2.5,5\n12.2,2.5\n14.8,5.2\n50,50"),
])
def test_fixed_cases_match_reference(text, width, points):
    _check_against_reference(text, width, points)


def test_random_small_cases_match_reference():
    random.seed(20260927)
    for _ in range(4):
        text = random.choice(["ab", "q", "a b", "Ab", "12", "z q"])
        theory = _dots_of(typeset(text, 10))
        pts = []
        for x, y, *_ in theory:
            if random.random() < 0.8:  # 理论点附近抖动（±0.5 毫米）
                jx = x + random.randint(-5, 5)
                jy = y + random.randint(-5, 5)
                pts.append((jx, jy))
        for _ in range(random.randint(0, 3)):  # 杂散多余点
            pts.append((random.randint(-50, 300), random.randint(-50, 300)))
        random.shuffle(pts)
        points_text = "\n".join(f"{x / 10},{y / 10}" for x, y in pts)
        _check_against_reference(text, 10, points_text)
