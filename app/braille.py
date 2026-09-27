"""六点盲文转写与排版引擎。

实现英语一级（Grade 1）六点盲文转写，以及以
"断词次数 → 行数 → 各行剩余格数平方和 → 断点序列字典序"
为优先级的动态规划排版。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 六点盲文常量
# ---------------------------------------------------------------------------

# 点号到 Unicode 盲文图案位的映射：
#   左列点 1/2/3 -> 位 0/1/2；右列点 4/5/6 -> 位 3/4/5
_DOT_BIT = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}

# 英语一级盲文字母表（以 frozenset(点号) 表示）
LETTER_DOTS: dict[str, frozenset[int]] = {
    "a": frozenset({1}),
    "b": frozenset({1, 2}),
    "c": frozenset({1, 4}),
    "d": frozenset({1, 4, 5}),
    "e": frozenset({1, 5}),
    "f": frozenset({1, 2, 4}),
    "g": frozenset({1, 2, 4, 5}),
    "h": frozenset({1, 2, 5}),
    "i": frozenset({2, 4}),
    "j": frozenset({2, 4, 5}),
    "k": frozenset({1, 3}),
    "l": frozenset({1, 2, 3}),
    "m": frozenset({1, 3, 4}),
    "n": frozenset({1, 3, 4, 5}),
    "o": frozenset({1, 3, 5}),
    "p": frozenset({1, 2, 3, 4}),
    "q": frozenset({1, 2, 3, 4, 5}),
    "r": frozenset({1, 2, 3, 5}),
    "s": frozenset({2, 3, 4}),
    "t": frozenset({2, 3, 4, 5}),
    "u": frozenset({1, 3, 6}),
    "v": frozenset({1, 2, 3, 6}),
    "w": frozenset({2, 4, 5, 6}),
    "x": frozenset({1, 3, 4, 6}),
    "y": frozenset({1, 3, 4, 5, 6}),
    "z": frozenset({1, 3, 5, 6}),
}

# 数字：1～9、0 对应 a～i、j
DIGIT_LETTER = {
    "1": "a", "2": "b", "3": "c", "4": "d", "5": "e",
    "6": "f", "7": "g", "8": "h", "9": "i", "0": "j",
}

CAPITAL_DOTS = frozenset({6})          # 大写标记（点 6）
NUMBER_DOTS = frozenset({3, 4, 5, 6})  # 数字标记（点 3456）
HYPHEN_DOTS = frozenset({3, 6})        # 连字符（点 36）

CAPITAL_CELL = "⠠"  # U+2820
NUMBER_CELL = "⠼"   # U+283C
HYPHEN_CELL = "⠤"   # U+2824
SPACE_CELL = "⠀"    # U+2800


def dots_to_unicode(dots: frozenset[int]) -> str:
    """把一组点号转换为对应的 Unicode 盲文字符（U+2800 起）。"""
    code = 0x2800
    for dot in dots:
        code |= 1 << _DOT_BIT[dot]
    return chr(code)


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------

MAX_LENGTH = 500
MIN_WIDTH = 10
MAX_WIDTH = 40


class ValidationError(Exception):
    """输入非法；errors 为结构化错误列表。"""

    def __init__(self, errors: list[dict]):
        super().__init__("输入校验失败")
        self.errors = errors


def line_col(text: str, pos: int) -> tuple[int, int]:
    """0 基偏移 -> 1 基 (行号, 列号)。"""
    line = text.count("\n", 0, pos) + 1
    last_nl = text.rfind("\n", 0, pos)
    col = pos - last_nl if last_nl == -1 else pos - last_nl
    return line, col


def validate(text: str, width) -> None:
    """校验输入与行宽，不通过则抛出 ValidationError。"""
    errors: list[dict] = []

    if not isinstance(width, int) or isinstance(width, bool):
        errors.append({"code": "bad_width", "message": "行宽必须为整数。"})
    elif not MIN_WIDTH <= width <= MAX_WIDTH:
        errors.append({
            "code": "bad_width",
            "message": f"每行格数须在 {MIN_WIDTH}～{MAX_WIDTH} 之间。",
        })

    if len(text) > MAX_LENGTH:
        errors.append({
            "code": "too_long",
            "message": f"输入长度为 {len(text)} 个字符，超过 {MAX_LENGTH} 个字符上限。",
        })

    if not any(ch.isascii() and ch.isalnum() for ch in text):
        if text == "":
            errors.append({"code": "empty", "message": "请输入至少一个字母或数字。"})
        else:
            errors.append({
                "code": "no_alnum",
                "message": "输入中至少需要包含一个字母或数字。",
            })

    # 非法字符（仅允许 ASCII 字母、数字、空格、换行）
    start = -1
    for i, ch in enumerate(text):
        allowed = (
            ch in "\n "
            or ch.isascii() and (ch.isalpha() or ch.isdigit())
        )
        if not allowed:
            if start == -1:
                start = i
        elif start != -1:
            errors.append(_illegal_error(text, start, i))
            start = -1
    if start != -1:
        errors.append(_illegal_error(text, start, len(text)))

    # 混写词：同一词中字母与数字混用
    for word, wstart in _iter_words(text):
        has_alpha = any(c.isalpha() for c in word)
        has_digit = any(c.isdigit() for c in word)
        if has_alpha and has_digit:
            line, col = line_col(text, wstart)
            errors.append({
                "code": "mixed_word",
                "pos": wstart,
                "line": line,
                "col": col,
                "length": len(word),
                "word": word,
                "message": f"第 {line} 行第 {col} 列的词 “{word}” 字母与数字混写："
                           f"每个词只能全为字母或全为数字。",
            })

    if errors:
        raise ValidationError(errors)


def _illegal_error(text: str, s: int, e: int) -> dict:
    line, col = line_col(text, s)
    sample = text[s:e]
    if len(sample) > 10:
        sample = sample[:10] + "…"
    return {
        "code": "illegal_char",
        "pos": s,
        "line": line,
        "col": col,
        "length": e - s,
        "message": f"第 {line} 行第 {col} 列起含非法字符 {sample!r}："
                   f"仅允许 ASCII 字母、数字、空格与换行。",
    }


def _iter_words(text: str):
    """产出 (词, 在 text 中的起始偏移)；连续空格视作同一个词间分隔。"""
    i, n = 0, len(text)
    while i < n:
        if text[i] in " \n":
            i += 1
            continue
        start = i
        while i < n and text[i] not in " \n":
            i += 1
        yield text[start:i], start


# ---------------------------------------------------------------------------
# 词与字符的盲文展开
# ---------------------------------------------------------------------------

@dataclass
class CharItem:
    """词中的一个源字符。"""

    char: str                 # 小写字母 / 数字
    dots: frozenset[int]      # 字符本身的点
    extra: int = 0            # 前置标记格数（大写=1）


@dataclass
class Word:
    kind: str                 # "alpha" | "digit"
    chars: list[CharItem]
    source: str               # 原始词面（保留大小写）

    @property
    def base_len(self) -> int:
        """不含行首数字标记时该词占用的盲文格数。"""
        return sum(1 + c.extra for c in self.chars)


def build_words(source: str) -> list[str | Word]:
    """把一个硬分段展开成 [Word, ' ', Word, ...]（' ' 为词间格）。"""
    words: list[Word] = []
    for word_text, _ in _iter_words(source):
        if any(c.isalpha() for c in word_text):
            chars = [
                CharItem(c.lower(), LETTER_DOTS[c.lower()], 1 if c.isupper() else 0)
                for c in word_text
            ]
            words.append(Word("alpha", chars, word_text))
        else:
            chars = [
                CharItem(c, LETTER_DOTS[DIGIT_LETTER[c]])
                for c in word_text
            ]
            words.append(Word("digit", chars, word_text))

    tokens: list[str | Word] = []
    for w in words:
        if tokens:
            tokens.append(" ")
        tokens.append(w)
    return tokens


# 原子： ("gap", None) 或 ("char", (词序号, 词内字符序号, Word, CharItem))
def _flatten(tokens: list[str | Word]) -> list[tuple]:
    atoms: list[tuple] = []
    for wi, tok in enumerate(tokens):
        if tok == " ":
            atoms.append(("gap", None))
        else:
            for ci, ch in enumerate(tok.chars):
                atoms.append(("char", (wi, ci, tok, ch)))
    return atoms


# ---------------------------------------------------------------------------
# 行枚举与动态规划
# ---------------------------------------------------------------------------

@dataclass
class LaidCell:
    kind: str          # char / capital / number / hyphen / space
    text: str          # Unicode 盲文
    dots: list[int]    # 点位
    note: str          # 说明（页面悬浮提示）


@dataclass
class LaidLine:
    cells: list[LaidCell]
    source_text: str   # 与盲文行对应的原文
    is_blank: bool = False


@dataclass
class _Node:
    key: tuple          # (断词次数, 行数, 平方和)
    bps: tuple          # 自本行起的断点序列
    cand: dict | None   # 本行候选


def _char_cost(atom) -> int:
    return 1 + atom[1][3].extra


def _sign_cost(word: Word) -> int:
    """词（或数字词续行段）起点的数字标记占格：数字词 1 格，其余 0。"""
    return 1 if word.kind == "digit" else 0


def enum_line(atoms: list[tuple], width: int, start: int) -> list[dict]:
    """枚举行首状态 start 下所有合规行的结束候选。

    候选： end=下一原子下标, used=本行格数, break_here=是否超宽词断行,
          bpoint=本行最后一个源字符的原子下标。

    占格口径在候选枚举、DP 择优与逐格渲染间保持一致：
      - 数字词在其渲染起点（行首，或词间格之后的词首）占 1 格数字标记，
        续行段在行首重新占 1 格；
      - 词间格占 1 格，行首/行尾不留词间格；
      - 超宽词断行的行尾占 1 格点 36 连字符。

    断词候选有两处：行首词（含超宽词续行段）的前缀 + 连字符；
    以及行内已排若干完整词后，下一整词放不下时，
    "词间格 + 超宽词首段（含其数字标记）+ 连字符" 的跨词断行。
    """
    n = len(atoms)
    if start >= n:
        return []

    kind, payload = atoms[start]
    if kind != "char":
        return []  # 行首不可能是词间格
    wi, ci, word, ch = payload

    # 行首字符（数字词词首或续行段均需数字标记，统一计入）
    used = _sign_cost(word) + 1 + ch.extra

    # 同一词（或词的续行段）的原子范围：[start, end_word)
    end_word = start + 1
    while end_word < n:
        k2, p2 = atoms[end_word]
        if k2 != "char" or p2[0] != wi:
            break
        end_word += 1

    cands: list[dict] = []

    def add(end: int, used_total: int, broke: bool) -> None:
        cands.append({
            "end": end, "used": used_total,
            "break_here": broke, "bpoint": end - 1,
        })

    # 逐字符扫描行首词（行首为词首或超宽词续行，两种情形同一套规则）。
    # 设 k=本行已纳入的同词字符数（含行首字符），u=这些字符+行首标记的格数。
    # 对每个可行 k：
    #   - k 小于词内剩余字符数：若 u+1<=width，给"前缀 + 点36连字符"断词候选；
    #   - k 等于剩余字符数：词在本行结束，给无连字符的普通行尾候选。
    u = used
    for k in range(1, end_word - start + 1):
        if k > 1:
            u += _char_cost(atoms[start + k - 1])
        if u > width:
            break
        end_atom = start + k
        if end_atom < end_word:
            if u + 1 <= width:  # 留 1 格放连字符
                add(end_atom, u + 1, True)
        else:
            add(end_atom, u, False)
            # 词在本行结束：逐次尝试 "词间格 + 整词"；整词放不下时，
            # 改取 "词间格 + 超宽词首段 + 点36连字符" 的跨词断词候选。
            pos, total = end_atom, u
            while (
                pos < n
                and atoms[pos][0] == "gap"
                and total + 1 <= width
                and pos + 1 < n
                and atoms[pos + 1][0] == "char"
                and atoms[pos + 1][1][1] == 0
            ):
                next_atom = atoms[pos + 1]
                next_word: Word = next_atom[1][2]
                # 词间格 1 + 数字标记（数字词）+ 字符（含各自大写标记）
                extra = 1 + _sign_cost(next_word) + next_word.base_len
                if total + extra > width:
                    # 下一整词放不下：枚举词间格之后该超宽词的可行首段，
                    # 行尾以点 36 连字符收尾，且词必须剩余至少 1 个字符。
                    # budget 内须同时容纳数字标记与词首段，另留 1 格连字符。
                    budget = width - (total + 1) - _sign_cost(next_word)
                    nw_start = pos + 1
                    nw_end = nw_start + 1
                    while (
                        nw_end < n
                        and atoms[nw_end][0] == "char"
                        and atoms[nw_end][1][0] == next_atom[1][0]
                    ):
                        nw_end += 1
                    pu = 0
                    for q in range(nw_start, nw_end):
                        pu += _char_cost(atoms[q])
                        if pu + 1 > budget or q + 1 >= nw_end:
                            break
                        add(q + 1, total + 1 + _sign_cost(next_word) + pu + 1, True)
                    break
                new_pos = pos + 2
                while (
                    new_pos < n
                    and atoms[new_pos][0] == "char"
                    and atoms[new_pos][1][0] == next_atom[1][0]
                ):
                    new_pos += 1
                total += extra
                pos = new_pos
                add(pos, total, False)

    return cands


def layout_paragraph(atoms: list[tuple], width: int) -> list[dict]:
    """对一个非空分段做 DP 排版，返回有序行记录。"""
    n = len(atoms)
    INF = (10**9, 10**9, 10**18)

    memo: dict[int, _Node] = {n: _Node((0, 0, 0), (), None)}

    def solve(s: int) -> _Node:
        if s in memo:
            return memo[s]
        # 行落在词间格上：行首尾不留空格，零成本跳过该格，下行从词首开始。
        if atoms[s][0] == "gap":
            memo[s] = solve(s + 1)
            return memo[s]
        best: _Node | None = None
        for cand in enum_line(atoms, width, s):
            tail = solve(cand["end"])
            if tail.cand is None and cand["end"] != n:
                continue  # 走不到段尾的死路
            key = (
                tail.key[0] + (1 if cand["break_here"] else 0),
                tail.key[1] + 1,
                tail.key[2] + (width - cand["used"]) ** 2,
            )
            bps = (cand["bpoint"],) + tail.bps
            node = _Node(key, bps, cand)
            if best is None or (node.key, node.bps) < (best.key, best.bps):
                best = node
        if best is None:
            best = _Node(INF, (), None)
        memo[s] = best
        return best

    root = solve(0)
    if root.cand is None:
        raise RuntimeError("排版失败：存在无法放入一行的字符")

    records: list[dict] = []
    s = 0
    while s < n:
        if atoms[s][0] == "gap":
            s += 1
            continue
        cand = memo[s].cand
        records.append({"start": s, **cand})
        s = cand["end"]
    return records


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def _cell(kind: str, text: str, dots, note: str) -> LaidCell:
    return LaidCell(kind, text, sorted(dots), note)


def render_paragraph(atoms: list[tuple], records: list[dict]) -> tuple[list[LaidLine], int]:
    """把排版记录渲染为盲文格行，返回 (行, 数字标记重加次数)。"""
    laid: list[LaidLine] = []
    reopened = 0

    for rec in records:
        s, e = rec["start"], rec["end"]
        cells: list[LaidCell] = []
        src_parts: list[str] = []

        for t in range(s, e):
            kind, payload = atoms[t]
            if kind == "gap":
                cells.append(_cell("space", SPACE_CELL, (), "词间格（占 1 格）"))
                src_parts.append(" ")
            else:
                wi, ci, word, ch = payload
                # 数字词的渲染起点都要数字标记：行首（ci==0 或续行段 ci>0），
                # 或行内词间格之后的词首。与 enum_line 的占格口径一致。
                starts_word = t == s or ci == 0
                if word.kind == "digit" and starts_word:
                    if ci > 0:
                        note = "数字续行标记（点 3456 重加）"
                        reopened += 1
                    else:
                        note = "数字标记（点 3456）"
                    cells.append(_cell("number", NUMBER_CELL, NUMBER_DOTS, note))
                if ch.extra:
                    cells.append(_cell(
                        "capital", CAPITAL_CELL, CAPITAL_DOTS, "大写标记（点 6）",
                    ))
                if word.kind == "digit":
                    note = f"数字 {ch.char}（借字母 {DIGIT_LETTER[ch.char]} 的点位）"
                else:
                    note = f"字母 {ch.char}"
                cells.append(_cell(
                    "char", dots_to_unicode(ch.dots), ch.dots, note,
                ))
                src_parts.append(word.source[ci])

        if rec["break_here"]:
            cells.append(_cell(
                "hyphen", HYPHEN_CELL, HYPHEN_DOTS, "连字符（点 36，超宽词断行）",
            ))
            src_parts.append("-")

        # 逐格渲染占格须与候选枚举/DP 记录一致，防止漏算标记或词间格。
        if len(cells) != rec["used"]:
            raise RuntimeError(
                f"排版占格不一致：记录 {rec['used']} 格，渲染 {len(cells)} 格"
            )
        laid.append(LaidLine(cells, "".join(src_parts)))

    return laid, reopened


def typeset(text: str, width) -> dict:
    """校验并排版，返回前端使用的完整结果。"""
    validate(text, width)

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.endswith("\n"):
        normalized = normalized[:-1]  # POSIX 惯例：结尾单个换行不产生空尾段
    paragraph_sources = normalized.split("\n")

    all_lines: list[LaidLine] = []
    total_breaks = 0
    reopened = 0
    hyphen_lines: list[int] = []

    for psrc in paragraph_sources:
        tokens = build_words(psrc)
        if not tokens:
            all_lines.append(LaidLine([], "", is_blank=True))
            continue
        atoms = _flatten(tokens)
        records = layout_paragraph(atoms, width)
        for rec in records:
            if rec["break_here"]:
                total_breaks += 1
                hyphen_lines.append(len(all_lines) + 1)
        laid, rp = render_paragraph(atoms, records)
        reopened += rp
        all_lines.extend(laid)

    braille_text = "\n".join(
        "" if line.is_blank else "".join(c.text for c in line.cells)
        for line in all_lines
    )

    return {
        "width": width,
        "paragraphs": len(paragraph_sources),
        "total_lines": len(all_lines),
        "breaks": total_breaks,
        "number_reopened": reopened,
        "hyphen_lines": hyphen_lines,
        "braille_text": braille_text,
        "lines": [
            {
                "index": idx + 1,
                "blank": line.is_blank,
                "source": line.source_text,
                "used": len(line.cells),
                "remain": width - len(line.cells),
                "cells": [
                    {"kind": c.kind, "text": c.text, "dots": c.dots, "note": c.note}
                    for c in line.cells
                ],
            }
            for idx, line in enumerate(all_lines)
        ],
    }
