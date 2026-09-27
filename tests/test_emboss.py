"""单针压印路径引擎测试（含与朴素全枚举的随机对照）。"""

import random
from itertools import product

import pytest

from app.avoid import _dots_of
from app.braille import ValidationError, typeset
from app.emboss import _best_directions, _scanlines, emboss_path


# ---------------------------------------------------------------------------
# 独立朴素参照：枚举全部 2^L 个方向序列并模拟指令走行
# ---------------------------------------------------------------------------

def _reference(result):
    """返回 (方向序列, 总距离，单位 0.1 毫米)；总距离与指令走行完全一致。"""
    scan = _scanlines(_dots_of(result))
    best = None
    for seq in product((0, 1), repeat=len(scan)):
        x = y = 0
        dist = 0
        for (yy, line), d in zip(scan, seq):
            ordered = line[::-1] if d else line
            for dot in ordered:
                px = dot[0]
                dist += abs(px - x) + abs(yy - y)
                x, y = px, yy
        dist += abs(x) + abs(y)
        key = (dist, seq)
        if best is None or key < best:
            best = key
    return scan, best


def _simulate_commands(commands):
    """按指令模拟压头：返回 (走行距离, 压印点坐标序列, 末点)。"""
    x = y = 0
    raised = True
    dist = 0
    punched = []
    for cmd in commands:
        if cmd["op"] == "UP":
            raised = True
        elif cmd["op"] == "MOVE":
            assert raised, "MOVE 前必须抬针"
            dist += abs(round(cmd["x"] * 10) - x) + abs(round(cmd["y"] * 10) - y)
            x, y = round(cmd["x"] * 10), round(cmd["y"] * 10)
        elif cmd["op"] == "PUNCH":
            assert raised, "PUNCH 仅在抬针状态下落针"
            punched.append((x, y))
            raised = True  # PUNCH 完成后复位抬针
        else:
            raise AssertionError(f"未知指令 {cmd['op']}")
    return dist, punched, (x, y)


def _assert_path_valid(text, width):
    """对一次规划结果做完整的规则自检。"""
    result = typeset(text, width)
    scan, (ref_dist, ref_seq) = _reference(result)
    out = emboss_path(text, width)

    # 方向序列与总距离与朴素枚举一致（含字典序同分裁决）
    assert tuple(out["directions"]) == ref_seq
    assert out["scanline_count"] == len(scan)

    dist, punched, end = _simulate_commands(out["commands"])
    assert dist == ref_dist == round(out["total_distance"] * 10)
    assert end == (0, 0)  # 返回原点

    theory = sorted((d[0], d[1]) for d in _dots_of(result))
    assert sorted(punched) == theory          # 每个凸点恰好一次
    assert len(punched) == len(theory) == out["punch_count"]
    assert out["commands"][0] == {"op": "UP"}
    assert out["commands"][-1] == {"op": "MOVE", "x": 0.0, "y": 0.0}

    # 指令文本与结构化指令一一对应
    text_lines = out["command_text"].split("\n")
    assert len(text_lines) == len(out["commands"])
    assert text_lines[0] == "UP"
    for line, cmd in zip(text_lines, out["commands"]):
        if cmd["op"] in ("UP", "PUNCH"):
            assert line == cmd["op"]
        else:
            assert line == f"MOVE {cmd['x']:.1f},{cmd['y']:.1f}"

    # 每条扫描线方向与点序一致
    for i, s in enumerate(out["scanlines"]):
        assert s["direction"] == out["directions"][i]
        xs = [p["x"] for p in s["points"]]
        if s["direction"] == 0:
            assert xs == sorted(xs)
        else:
            assert xs == sorted(xs, reverse=True)
    return out


# ---------------------------------------------------------------------------
# 手写小例：方向序列与总距离
# ---------------------------------------------------------------------------

def test_single_dot_a():
    # a 仅点 1 (0,0)：原点出发压一针再回原点，总距离 0，方向序列 [0]
    out = _assert_path_valid("a", 10)
    assert out["directions"] == [0]
    assert out["total_distance"] == 0.0
    assert out["punch_count"] == 1
    assert out["scanline_count"] == 1
    assert out["commands"] == [
        {"op": "UP"},
        {"op": "MOVE", "x": 0.0, "y": 0.0},
        {"op": "PUNCH", "order": 1, "row": 0, "cell": 0, "dot": 1},
        {"op": "MOVE", "x": 0.0, "y": 0.0},
    ]
    assert out["command_text"] == "UP\nMOVE 0.0,0.0\nPUNCH\nMOVE 0.0,0.0"


def test_ab_two_scanlines():
    # a：点 1 (0,0)；b：点 1 (6,0)、点 2 (6,2.5)
    # 线1 y=0 [0,6]，线2 y=2.5 [6]；两线均递增时最短 17.0 毫米
    out = _assert_path_valid("ab", 10)
    assert out["directions"] == [0, 0]
    assert out["total_distance"] == 17.0


def test_q_snakes_down():
    # q 的两条双线（y=0、y=2.5 都含 x=0、2.5）适合蛇形：[0,1,0]
    out = _assert_path_valid("q", 10)
    assert out["directions"] == [0, 1, 0]
    assert out["total_distance"] == 15.0


def test_paragraph_gap_keeps_coordinate_origin():
    # 硬分段空行不产生点，但后续行仍按其零基行号取坐标（y 跨 10 毫米）
    out = _assert_path_valid("a\n\na", 10)
    ys = {s["y"] for s in out["scanlines"]}
    assert ys == {0.0, 20.0}
    assert out["directions"] == [0, 0]


def test_command_punch_locations_match_theory():
    out = emboss_path("ab", 10)
    punches = [c for c in out["commands"] if c["op"] == "PUNCH"]
    assert [(p["row"], p["cell"], p["dot"]) for p in punches] == [
        (0, 0, 1), (0, 1, 1), (0, 1, 2),
    ]
    assert [p["order"] for p in punches] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 扫描线分组
# ---------------------------------------------------------------------------

def test_scanlines_group_by_y_sorted():
    dots = _dots_of(typeset("bf", 10))
    scan = _scanlines(dots)
    assert [y for y, _ in scan] == [0, 25]
    assert [d[0] for d in scan[0][1]] == [0, 60, 85]
    assert [d[0] for d in scan[1][1]] == [0, 60]


def test_best_directions_tie_picks_lex_min():
    # 单点扫描线：递增/递减等价，字典序取 0
    scan = _scanlines(_dots_of(typeset("a", 10)))
    seq, total = _best_directions(scan)
    assert seq == (0,)
    assert total == 0


# ---------------------------------------------------------------------------
# 输入校验：完全复用 braille.validate / typeset
# ---------------------------------------------------------------------------

def test_invalid_text_raises_located():
    with pytest.raises(ValidationError) as ei:
        emboss_path("ab\tc", 10)
    err = ei.value.errors[0]
    assert err["code"] == "illegal_char"
    assert (err["line"], err["col"]) == (1, 3)


def test_mixed_word_rejected():
    with pytest.raises(ValidationError):
        emboss_path("ab1", 10)


def test_bad_width_rejected():
    with pytest.raises(ValidationError) as ei:
        emboss_path("a", 41)
    assert ei.value.errors[0]["code"] == "bad_width"


# ---------------------------------------------------------------------------
# 随机对照：独立朴素全枚举
# ---------------------------------------------------------------------------

WORDS = ["a", "b", "c", "q", "bf", "xyz", "pack", "2026", "07", "Hello"]


def test_random_against_brute_force():
    rng = random.Random(20260927)
    for _ in range(120):
        nwords = rng.randint(1, 4)
        parts = [rng.choice(WORDS) for _ in range(nwords)]
        text = " ".join(parts)
        if rng.random() < 0.3:
            text += "\n" + rng.choice(WORDS)
        width = rng.randint(10, 24)
        _assert_path_valid(text, width)
