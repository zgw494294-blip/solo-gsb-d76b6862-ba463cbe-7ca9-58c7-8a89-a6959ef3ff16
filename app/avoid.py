"""双面点阵避让：为正反两篇盲文寻找冲突最少的相对位移。

复用 braille 模块的校验与排版，把两面排版结果展开为凸点坐标后，
在 ±3 毫米（步长 0.1 毫米）的位移网格上遍历全部位移并择优。

坐标约定（单位 0.1 毫米，全程整数运算）：
- 零基行格 (r, c)：点 1～3 在 (60c, 100r+25k)，点 4～6 在 (60c+25, 100r+25k)，
  k=0～2，只计凸点；
- 反面点 (x, y) 映射到正面坐标 (60(w-1)+25-x+dx, y+dy)；
- 两面点距平方（放大 10 倍的整数平方）小于 (10×最小点距)² 记一对冲突；
- 按 (冲突对数, dx²+dy², dx, dy) 依次最小择优。
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from math import isqrt

from .braille import ValidationError, typeset, validate

# 位移范围 ±3 毫米、步长 0.1 毫米（以 0.1 毫米为单位的整数）
SHIFT_MIN = -30
SHIFT_MAX = 30

# 最小点距范围 0.1～3.0 毫米（0.1 毫米整数）
DIST_MIN = 1
DIST_MAX = 30

# 一个凸点：(X, Y, 行, 格, 点号)，坐标单位 0.1 毫米
Dot = tuple[int, int, int, int, int]


def _dots_of(result: dict) -> list[Dot]:
    """从排版结果提取全部凸点（只计凸点；词间格等无点格自然跳过）。"""
    dots: list[Dot] = []
    for r, line in enumerate(result["lines"]):
        for c, cell in enumerate(line["cells"]):
            for d in cell["dots"]:
                if d <= 3:
                    dots.append((60 * c, 100 * r + 25 * (d - 1), r, c, d))
                else:
                    dots.append((60 * c + 25, 100 * r + 25 * (d - 4), r, c, d))
    return dots


def _check_inputs(front: str, back: str, width, min_distance) -> int:
    """复用 braille.validate 校验两篇原文与共同行宽，并校验最小点距。

    返回放大 10 倍的最小点距整数；不通过时抛出 ValidationError。
    原文错误带 face 字段（front/back）以区分属于哪一面；行宽错误两面相同，只报一次。
    """
    errors: list[dict] = []
    width_seen = False
    for face, text in (("front", front), ("back", back)):
        try:
            validate(text, width)
        except ValidationError as exc:
            for err in exc.errors:
                if err["code"] == "bad_width":
                    if width_seen:
                        continue
                    width_seen = True
                    errors.append(err)
                else:
                    errors.append({**err, "face": face})

    threshold = 0
    if isinstance(min_distance, bool) or not isinstance(min_distance, (int, float)):
        errors.append({
            "code": "bad_min_distance",
            "message": "最小点距必须为 0.1～3.0 毫米、限一位小数的数值。",
        })
    else:
        scaled = min_distance * 10
        nearest = round(scaled)
        if abs(scaled - nearest) > 1e-6 or not DIST_MIN <= nearest <= DIST_MAX:
            errors.append({
                "code": "bad_min_distance",
                "message": f"最小点距须为 0.1～3.0 毫米且限一位小数（当前为 {min_distance}）。",
            })
        else:
            threshold = nearest

    if errors:
        raise ValidationError(errors)
    return threshold


def _group_pairs(
    front_dots: list[Dot],
    back_dots: list[Dot],
    width: int,
    threshold: int,
) -> dict[tuple[int, int], list[tuple[Dot, Dot]]]:
    """按相对偏移 (AX, AY) 聚合可能冲突的正反点对。

    正面点 (fx, fy) 与映射后的反面点 (60(w-1)+25-bx+dx, by+dy) 的距离平方为
    (AX-dx)²+(AY-dy)²，其中 AX=fx+bx-60(w-1)-25、AY=fy-by，只与相对偏移有关；
    |AX| 或 |AY| 达到 30+点距 的点对在任何位移下都不可能冲突，直接排除。
    """
    mirror = 60 * (width - 1) + 25
    reach = (SHIFT_MAX - 1) + threshold  # |AX|、|AY| 的整数上界（严格小于 30+点距）

    # 反面点按行分组、行内按 X 排序，便于按镜像窗口二分筛选
    rows: dict[int, tuple[list[int], list[Dot]]] = {}
    by_row: dict[int, list[Dot]] = defaultdict(list)
    for b in back_dots:
        by_row[b[2]].append(b)
    for r, row in by_row.items():
        row.sort()
        rows[r] = ([b[0] for b in row], row)

    groups: dict[tuple[int, int], list[tuple[Dot, Dot]]] = defaultdict(list)
    for f in front_dots:
        fx, fy, fr = f[0], f[1], f[2]
        # |AY| ≤ reach < 100，只可能来自相邻三行
        for rb in (fr - 1, fr, fr + 1):
            if rb not in rows:
                continue
            xs, dots = rows[rb]
            lo = bisect_left(xs, mirror - fx - reach)
            hi = bisect_right(xs, mirror - fx + reach)
            for b in dots[lo:hi]:
                ax = fx + b[0] - mirror
                ay = fy - b[1]
                if abs(ax) <= reach and abs(ay) <= reach:
                    groups[(ax, ay)].append((f, b))
    return groups


def _best_shift(
    groups: dict[tuple[int, int], list[tuple[Dot, Dot]]],
    threshold: int,
) -> tuple[int, int, int]:
    """差分数组统计全部 61×61 个位移的冲突对数，按规则择优，返回 (dx, dy, 冲突对数)。

    偏移 (AX, AY) 的一组点对在位移 (dx, dy) 下冲突，当且仅当
    (AX-dx)²+(AY-dy)² < 点距²，即位移落在以 (AX, AY) 为圆心、点距为半径的
    开圆盘内；把每组的多重数累加进圆盘覆盖的整点位移即可。
    """
    span = SHIFT_MAX - SHIFT_MIN + 1
    diff = [[0] * (span + 1) for _ in range(span)]
    t2 = threshold * threshold
    for (ax, ay), pairs in groups.items():
        m = len(pairs)
        # 冲突要求 |AX-dx| < 点距，即 dx ∈ [AX-点距+1, AX+点距-1]
        dx_lo = max(SHIFT_MIN, ax - threshold + 1)
        dx_hi = min(SHIFT_MAX, ax + threshold - 1)
        for dx in range(dx_lo, dx_hi + 1):
            rem = t2 - (ax - dx) * (ax - dx)
            if rem <= 0:
                continue
            half = isqrt(rem - 1)  # (AY-dy)² < rem ⟺ |AY-dy| ≤ half
            dy_lo = max(SHIFT_MIN, ay - half)
            dy_hi = min(SHIFT_MAX, ay + half)
            if dy_lo > dy_hi:
                continue
            row = diff[dx - SHIFT_MIN]
            row[dy_lo - SHIFT_MIN] += m
            row[dy_hi - SHIFT_MIN + 1] -= m

    best_key = None
    best = (0, 0, 0)
    for dx in range(SHIFT_MIN, SHIFT_MAX + 1):
        row = diff[dx - SHIFT_MIN]
        run = 0
        for dy in range(SHIFT_MIN, SHIFT_MAX + 1):
            run += row[dy - SHIFT_MIN]
            key = (run, dx * dx + dy * dy, dx, dy)
            if best_key is None or key < best_key:
                best_key = key
                best = (dx, dy, run)
    return best


def _conflicts_at(
    groups: dict[tuple[int, int], list[tuple[Dot, Dot]]],
    threshold: int,
    dx: int,
    dy: int,
) -> list[tuple[Dot, Dot]]:
    """枚举最优位移下的全部冲突点对（按正面行、格、点号排序，结果确定）。"""
    t2 = threshold * threshold
    out: list[tuple[Dot, Dot]] = []
    for (ax, ay), pairs in groups.items():
        if (ax - dx) * (ax - dx) + (ay - dy) * (ay - dy) < t2:
            out.extend(pairs)
    out.sort(key=lambda p: (p[0][2], p[0][3], p[0][4], p[1][2], p[1][3], p[1][4]))
    return out


def avoid(front_text: str, back_text: str, width, min_distance) -> dict:
    """校验并排版正反两篇原文，搜索最优避让位移，返回位移与全部冲突点对。"""
    threshold = _check_inputs(front_text, back_text, width, min_distance)

    front_result = typeset(front_text, width)
    back_result = typeset(back_text, width)
    front_dots = _dots_of(front_result)
    back_dots = _dots_of(back_result)

    groups = _group_pairs(front_dots, back_dots, width, threshold)
    dx, dy, count = _best_shift(groups, threshold)
    pairs = _conflicts_at(groups, threshold, dx, dy)
    if len(pairs) != count:
        raise RuntimeError("避让统计不一致：差分计数与逐对枚举结果不同")

    def end(face: str, dot: Dot) -> dict:
        return {"face": face, "row": dot[2], "cell": dot[3], "dot": dot[4]}

    return {
        "width": width,
        "min_distance": threshold / 10,
        "dx": dx / 10,
        "dy": dy / 10,
        "feasible": count == 0,
        "conflict_count": count,
        "conflicts": [
            {"front": end("front", f), "back": end("back", b)} for f, b in pairs
        ],
        "front_dots": len(front_dots),
        "back_dots": len(back_dots),
        "front": front_result,
        "back": back_result,
    }
