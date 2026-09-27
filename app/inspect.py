"""压印点位复核：把实测凸点整体平移后与排版理论凸点配准。

复用 braille 模块的校验与排版（原文上限收紧为 100 字符），沿用排版结果的
理论凸点坐标；实测点整体平移 dx、dy（各 −3～3 毫米、步长 0.1 毫米）后与
距离不超过 0.4 毫米的理论点一对一配对，遍历全部位移择优。

坐标约定（单位 0.1 毫米，全程整数运算）：
- 理论点与 avoid 模块一致：零基行格 (r, c) 中点 1～3 在 (60c, 100r+25k)，
  点 4～6 在 (60c+25, 100r+25k)，k=0～2，只计凸点；
- 实测点 (mx, my) 平移后为 (mx+dx, my+dy)，与理论点 (tx, ty) 的距离平方只与
  相对偏移 AX=tx-mx、AY=ty-my 有关：(AX-dx)²+(AY-dy)²；
- 距离不超过 0.4 毫米（距离平方 ≤ 16）才可配对。

配对规则（单个位移下）：
- 候选对按 (距离平方, 实测点输入行序, 理论点序号) 升序贪心选取，
  每个理论点、每个实测点至多配对一次（一对一）；
- 同一理论点有多个候选实测点时自然取距离最近者，同距取输入顺序较早者。

位移择优（全部 61×61 个位移）：
  匹配点数最多 → 距离平方和最小 → dx²+dy² 最小 → dx 最小 → dy 最小。

结果给出位移、缺失理论点（零基行/格/点号）与多余实测点（输入行号，一基）。
"""

from __future__ import annotations

import re

from .avoid import SHIFT_MAX, SHIFT_MIN, _dots_of
from .braille import ValidationError, typeset, validate

# 原文上限（字符）与实测点上限（行数）
MAX_TEXT_LENGTH = 100
MAX_POINTS = 400

# 配对距离上限 0.4 毫米（0.1 毫米为单位；距离平方 ≤ 16）
MATCH_RADIUS = 4
MATCH_RADIUS_SQ = MATCH_RADIUS * MATCH_RADIUS

# 实测点坐标：可选符号的整数或一位小数（毫米）；显式 [0-9]，不接受 Unicode 数字
_NUM_RE = re.compile(r"[+-]?([0-9]+(\.[0-9])?|\.[0-9])")


class _Line:
    """points 文本中一行的定位：行内下标换算 (pos, line, col)。"""

    def __init__(self, start: int, no: int):
        self.start = start          # 行首在原文中的 0 基偏移
        self.no = no                # 一基行号

    def pos_of(self, i: int) -> tuple[int, int, int]:
        """行内 0 基下标 -> (pos, line, col)，pos 为原文 0 基偏移。"""
        return self.start + i, self.no, i + 1


def _scale(token: str) -> int:
    """把 '±整数[.一位小数]' 或 '±.一位小数' 放大 10 倍为整数。"""
    neg = token.startswith("-")
    body = token.lstrip("+-")
    if "." in body:
        whole, frac = body.split(".")
        value = int(whole or "0") * 10 + int(frac)
    else:
        value = int(body) * 10
    return -value if neg else value


def _parse_points(points_text: str) -> list[tuple[int, int]]:
    """解析实测点文本，返回 [(X, Y), ...]（0.1 毫米整数，按输入行序）。

    每行恰好一对 'x,y' 坐标（毫米，限一位小数，可带符号）；空文本表示 0 行。
    不通过时抛出 ValidationError，错误带实测点行、列定位（field="points"）。
    """
    if points_text == "":
        return []

    normalized = points_text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.endswith("\n"):
        normalized = normalized[:-1]  # POSIX 惯例：结尾单个换行不产生空尾行
    lines = normalized.split("\n")
    errors: list[dict] = []

    def bad(line: _Line, i: int, length: int, detail: str) -> None:
        pos, lno, col = line.pos_of(i)
        errors.append({
            "code": "bad_points",
            "field": "points",
            "pos": pos,
            "line": lno,
            "col": col,
            "length": length,
            "message": f"实测点第 {lno} 行第 {col} 列{detail}",
        })

    points: list[tuple[int, int]] = []
    start = 0
    for no, raw in enumerate(lines, 1):
        line = _Line(start, no)
        start += len(raw) + 1

        if raw.strip() == "":
            bad(line, 0, max(len(raw), 1),
                "为空行：每行须为一对 “x,y” 坐标（毫米，限一位小数）。")
            continue

        comma = raw.find(",")
        if comma == -1 or raw.find(",", comma + 1) != -1:
            bad(line, 0, len(raw),
                f"的 {raw!r} 格式有误：每行须恰好为一对 “x,y” 坐标，"
                f"例如 “12.3,4.5”。")
            continue

        coords: list[int] = []
        ok = True
        for tok, off in ((raw[:comma], 0), (raw[comma + 1:], comma + 1)):
            if not _NUM_RE.fullmatch(tok):
                bad(line, off, max(len(tok), 1),
                    f"的坐标 {tok!r} 不是合法数值：须为毫米数，"
                    f"最多一位小数，可带正负号。")
                ok = False
            else:
                coords.append(_scale(tok))
        if ok:
            points.append((coords[0], coords[1]))

    if len(points) > MAX_POINTS:
        errors.append({
            "code": "too_many_points",
            "field": "points",
            "message": f"实测点共 {len(points)} 行，超过 {MAX_POINTS} 行上限。",
        })

    if errors:
        raise ValidationError(errors)
    return points


def _check_inputs(text: str, width, points_text: str) -> list[tuple[int, int]]:
    """校验原文（上限 100 字符）、行宽与实测点文本，返回实测点坐标列表。

    原文与行宽复用 braille.validate（错误定位不变，补 field="text"）；
    实测点错误带 field="points"。全部错误收集后一次抛出。
    """
    errors: list[dict] = []

    if len(text) > MAX_TEXT_LENGTH:
        errors.append({
            "code": "too_long",
            "field": "text",
            "message": f"输入长度为 {len(text)} 个字符，"
                       f"超过 {MAX_TEXT_LENGTH} 个字符上限。",
        })
    try:
        validate(text, width)
    except ValidationError as exc:
        for err in exc.errors:
            if err["code"] == "too_long":
                continue  # 上限不同，已按 100 字符单独报告
            errors.append({**err, "field": "text"})

    try:
        points = _parse_points(points_text)
    except ValidationError as exc:
        errors.extend(exc.errors)
        points = []

    if errors:
        raise ValidationError(errors)
    return points


def _candidate_groups(
    theory: list[tuple[int, int, int, int, int]],
    measured: list[tuple[int, int]],
) -> dict[tuple[int, int], list[tuple[int, int]]]:
    """把可能配对的 (实测, 理论) 对按相对偏移 (AX, AY) 分组。

    位移 (dx, dy) 下该组的距离平方为 (AX-dx)²+(AY-dy)²，故只有
    |AX|、|AY| ≤ 30+4 的组可能参与配对，其余直接排除。
    """
    reach = SHIFT_MAX + MATCH_RADIUS
    groups: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for mi, (mx, my) in enumerate(measured):
        for ti, t in enumerate(theory):
            ax = t[0] - mx
            ay = t[1] - my
            if abs(ax) <= reach and abs(ay) <= reach:
                groups.setdefault((ax, ay), []).append((mi, ti))
    return groups


def _match_at(
    groups: dict[tuple[int, int], list[tuple[int, int]]],
    dx: int,
    dy: int,
    n_theory: int,
    n_measured: int,
) -> tuple[int, int, list[tuple[int, int, int]]]:
    """位移 (dx, dy) 下的贪心一对一配对。

    返回 (匹配数, 距离平方和, [(理论序号, 实测序号, 距离平方), ...])。
    候选对按 (距离平方, 实测序号, 理论序号) 升序选取：同一理论点的多个
    候选实测点自然取最近者，同距取输入顺序较早者。
    """
    edges: list[tuple[int, int, int]] = []  # (距离平方, 实测序号, 理论序号)
    for (ax, ay), pairs in groups.items():
        rx = ax - dx
        ry = ay - dy
        if abs(rx) > MATCH_RADIUS or abs(ry) > MATCH_RADIUS:
            continue
        d2 = rx * rx + ry * ry
        if d2 > MATCH_RADIUS_SQ:
            continue
        # 同一 (AX, AY) 组在该位移下的距离平方相同，无需逐对重算
        edges.extend((d2, mi, ti) for mi, ti in pairs)
    edges.sort()

    used_t = bytearray(n_theory)
    used_m = bytearray(n_measured)
    matches: list[tuple[int, int, int]] = []
    sse = 0
    for d2, mi, ti in edges:
        if used_t[ti] or used_m[mi]:
            continue
        used_t[ti] = 1
        used_m[mi] = 1
        matches.append((ti, mi, d2))
        sse += d2
    return len(matches), sse, matches


def inspect(text: str, width, points_text: str) -> dict:
    """校验输入，遍历全部位移配准实测点与理论凸点，返回复核结果。"""
    measured = _check_inputs(text, width, points_text)

    result = typeset(text, width)
    theory = _dots_of(result)
    groups = _candidate_groups(theory, measured)

    best_key = None
    best = (0, 0, 0, [])  # (dx, dy, sse, matches)
    for dx in range(SHIFT_MIN, SHIFT_MAX + 1):
        for dy in range(SHIFT_MIN, SHIFT_MAX + 1):
            count, sse, matches = _match_at(
                groups, dx, dy, len(theory), len(measured),
            )
            key = (-count, sse, dx * dx + dy * dy, dx, dy)
            if best_key is None or key < best_key:
                best_key = key
                best = (dx, dy, sse, matches)

    dx, dy, sse, matches = best
    matched_t = {ti for ti, _, _ in matches}
    matched_m = {mi for _, mi, _ in matches}

    return {
        "width": width,
        "dx": dx / 10,
        "dy": dy / 10,
        "theory_dots": len(theory),
        "measured_dots": len(measured),
        "matched": len(matches),
        "missing": len(theory) - len(matches),
        "extra": len(measured) - len(matches),
        "perfect": len(matches) == len(theory) == len(measured),
        "sse": sse / 100,
        "missing_dots": [
            {"row": t[2], "cell": t[3], "dot": t[4]}
            for ti, t in enumerate(theory) if ti not in matched_t
        ],
        "extra_points": [
            {"line": mi + 1, "x": measured[mi][0] / 10, "y": measured[mi][1] / 10}
            for mi in range(len(measured)) if mi not in matched_m
        ],
        "matches": [
            {
                "row": theory[ti][2],
                "cell": theory[ti][3],
                "dot": theory[ti][4],
                "line": mi + 1,
                "distance": d2 ** 0.5 / 10,
            }
            for ti, mi, d2 in sorted(matches)
        ],
        "points": [
            {"line": mi + 1, "x": mx / 10, "y": my / 10}
            for mi, (mx, my) in enumerate(measured)
        ],
        "layout": result,
    }
