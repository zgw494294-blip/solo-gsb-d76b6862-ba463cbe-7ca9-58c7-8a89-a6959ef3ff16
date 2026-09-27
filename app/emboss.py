"""单针压印路径：为排版得到的全部理论凸点规划最短单针扫描路径。

复用 braille 模块的校验与排版，沿用 avoid/inspect 的理论凸点坐标
（零基行格 (r, c)，点 1～3 在 (60c, 100r+25k)，点 4～6 在 (60c+25, 100r+25k)，
k=0～2，单位 0.1 毫米，只计凸点）。

路径规则：
- 把全部凸点按 y 升序分成若干扫描线（同一 y 的点为一条扫描线）；
- 每条扫描线的 x 只能单调递增（方向 0）或单调递减（方向 1），
  扫描线之间按 y 升序执行，每个凸点恰好压一次；
- 压头从 (0,0) 出发，MOVE 前须抬针，PUNCH 仅在理论凸点落针并复位（抬针），
  结束后返回 (0,0)；
- 全部移动按曼哈顿距离计长，选择总距离最短的扫描线方向序列，
  同距取方向序列（递增 0 / 递减 1）字典序最小者。

同一扫描线内的点只可能来自同一行（相邻行 y 相差 100，而点列 k=0～2 跨度 50），
故各扫描线内 x 互不相同；第 i 条扫描线递增方向的进入点为 xmin、退出点为 xmax，
递减方向反之。用两条状态的动态规划即可在 O(扫描线数) 内完成择优。
"""

from __future__ import annotations

from collections import defaultdict

from .avoid import _dots_of
from .braille import typeset

# 与 avoid/inspect 一致：坐标以 0.1 毫米为单位的整数，全程整数运算
Scanline = tuple[int, list[tuple[int, int, int, int, int]]]


def _scanlines(dots: list[tuple[int, int, int, int, int]]) -> list[Scanline]:
    """把凸点按 y 升序分组为扫描线，线内按 x 升序（即递增方向的落针顺序）。"""
    by_y: dict[int, list[tuple[int, int, int, int, int]]] = defaultdict(list)
    for dot in dots:
        by_y[dot[1]].append(dot)
    scan: list[Scanline] = []
    for y in sorted(by_y):
        line = sorted(by_y[y], key=lambda d: d[0])
        xs = [d[0] for d in line]
        if len(set(xs)) != len(xs):  # 理论坐标不该重合：防御性校验
            raise RuntimeError("压印路径：同一扫描线上存在 x 重合的凸点")
        scan.append((y, line))
    return scan


def _best_directions(scan: list[Scanline]) -> tuple[tuple[int, ...], int]:
    """动态规划求最优扫描线方向序列，返回 (方向序列, 总距离，单位 0.1 毫米)。

    状态 dp[i][d]：压完第 i 条扫描线、压头停在该线退出点时的最小累计移动距离，
    并记录取得该值时字典序最小的方向序列；d=0 递增（退出点 xmax），
    d=1 递减（退出点 xmin）。总距离另含从 (0,0) 到首点与末点返回 (0,0) 的行程。
    """
    n = len(scan)
    y0, line0 = scan[0]
    x0min, x0max = line0[0][0], line0[-1][0]
    # 从原点进入首线：y 行程为 y0；递增先到 xmin，递减先到 xmax，线内扫过跨度
    states = [
        (x0min + y0 + (x0max - x0min), (0,)),
        (x0max + y0 + (x0max - x0min), (1,)),
    ]

    for i in range(1, n):
        py, pline = scan[i - 1]
        y, line = scan[i]
        pmin, pmax = pline[0][0], pline[-1][0]
        xmin, xmax = line[0][0], line[-1][0]
        span = xmax - xmin
        dy = y - py
        cur: list[tuple[int, tuple[int, ...]]] = []
        for d in (0, 1):
            entry = xmin if d == 0 else xmax  # 本线方向的进入点
            candidates = []
            for cost, seq in states:
                exitp = pmax if seq[-1] == 0 else pmin  # 上线退出点
                candidates.append((cost + abs(entry - exitp) + dy + span, seq + (d,)))
            cur.append(min(candidates, key=lambda c: (c[0], c[1])))
        states = cur

    yn, last_line = scan[-1]
    final = [
        (states[0][0] + last_line[-1][0] + yn, states[0][1]),    # 递增退出点 xmax
        (states[1][0] + last_line[0][0] + yn, states[1][1]),     # 递减退出点 xmin
    ]
    total, seq = min(final, key=lambda c: (c[0], c[1]))
    return seq, total


def _fmt_mm(v: int) -> str:
    """0.1 毫米整数 -> 一位小数字符串（毫米）。"""
    return f"{v / 10:.1f}"


def _build_commands(
    scan: list[Scanline], directions: tuple[int, ...]
) -> tuple[list[dict], list[dict], str, int]:
    """按方向序列生成执行指令并自检，返回 (扫描线明细, 指令列表, 指令文本, 走行距离)。

    指令语义：UP 抬针；MOVE 在抬针状态移动到目标点；PUNCH 在当前点落针压印后复位抬针。
    每个 PUNCH 前都有 MOVE 把压头送到该理论凸点，最后一条 MOVE 回到 (0,0)。
    """
    lines_out: list[dict] = []
    commands: list[dict] = [{"op": "UP"}]
    text_lines = ["UP"]

    x = y = 0
    moved = 0
    order = 0
    for li, ((yy, line), direction) in enumerate(zip(scan, directions)):
        ordered = list(reversed(line)) if direction == 1 else line
        points_out = []
        for dot in ordered:
            px = dot[0]
            moved += abs(px - x) + abs(yy - y)
            x, y = px, yy
            commands.append({"op": "MOVE", "x": px / 10, "y": yy / 10})
            text_lines.append(f"MOVE {_fmt_mm(px)},{_fmt_mm(yy)}")
            order += 1
            commands.append({
                "op": "PUNCH",
                "order": order,
                "row": dot[2],
                "cell": dot[3],
                "dot": dot[4],
            })
            text_lines.append("PUNCH")
            points_out.append({
                "x": px / 10,
                "row": dot[2],
                "cell": dot[3],
                "dot": dot[4],
                "order": order,
            })
        lines_out.append({"index": li, "y": yy / 10, "direction": direction, "points": points_out})

    moved += abs(x) + abs(y)
    commands.append({"op": "MOVE", "x": 0.0, "y": 0.0})
    text_lines.append("MOVE 0.0,0.0")
    return lines_out, commands, "\n".join(text_lines), moved


def emboss_path(text: str, width) -> dict:
    """校验并排版原文，规划单针压印路径，返回方向序列、总距离与执行指令。"""
    result = typeset(text, width)  # 校验、行宽范围与排版口径完全复用
    dots = _dots_of(result)
    scan = _scanlines(dots)

    directions, total = _best_directions(scan)
    lines_out, commands, command_text, moved = _build_commands(scan, directions)
    if moved != total:
        raise RuntimeError(f"压印路径距离不一致：规划 {total}，指令 {moved}")
    punches = sum(1 for c in commands if c["op"] == "PUNCH")
    if punches != len(dots):
        raise RuntimeError("压印路径点数不一致：存在未压或重复压印的凸点")

    return {
        "width": width,
        "punch_count": punches,
        "scanline_count": len(scan),
        "directions": list(directions),
        "total_distance": total / 10,
        "commands": commands,
        "command_text": command_text,
        "scanlines": lines_out,
        "layout": result,
    }
