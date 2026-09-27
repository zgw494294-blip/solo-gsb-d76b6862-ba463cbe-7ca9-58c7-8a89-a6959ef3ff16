"""六点盲文识读引擎：把 Unicode 六点盲文解读回 ASCII 文本。

与转写方向对应的识读规则：
- 沿用英语一级字母点位；盲文空格（U+2800）解读为词间空格，普通换行原样保留；
- ⠠（点 6）只把紧随的一个字母转为大写；
- ⠼（点 3456）使后续 a～i、j 点位分别读作 1～9、0；
  数字标记只能在词首（行首或词间格之后）开启数字词，或在数字词断行续行时
  重新起始；数字状态到词间格或普通换行结束；
- ⠤（点 36）仅作行尾断词标记：去掉该格及其后的换行并接续同一词，
  标记前后必须是同一类型的未结束词（字母词续字母词、数字词续数字词），
  数字词续行须以 ⠼ 重新起始；普通换行保留；
- 孤立标记、未定义点位、行内连字符、标记前无未结束词、断行前后词类型不一致
  与不合法的数字续行均按盲文行、列定位报错，且不返回任何部分解读文本。
"""

from __future__ import annotations

from .braille import (
    CAPITAL_CELL,
    DIGIT_LETTER,
    HYPHEN_CELL,
    LETTER_DOTS,
    NUMBER_CELL,
    SPACE_CELL,
    ValidationError,
    dots_to_unicode,
    line_col,
)

MAX_CELLS = 500

# Unicode 盲文字符 -> 小写字母
_LETTER_CELL = {dots_to_unicode(dots): ch for ch, dots in LETTER_DOTS.items()}
# 字母 -> 数字（a～i -> 1～9，j -> 0）
_LETTER_DIGIT = {letter: digit for digit, letter in DIGIT_LETTER.items()}


def _cell_dots(ch: str) -> frozenset[int]:
    """盲文字符 -> 点号集合（位 0～7 依次对应点 1～8）。"""
    bits = ord(ch) - 0x2800
    return frozenset(bit + 1 for bit in range(8) if bits >> bit & 1)


def decode(text: str) -> dict:
    """把 Unicode 六点盲文解读为 ASCII 字母、数字、空格与换行。

    识读过程中持续维护当前词的类型（字母词 / 数字词）以及断词待续状态：
    盲文空格与普通换行终止当前词；行尾断词标记 ⠤ 只在其前后为同一类型的
    未结束词时合法。输入非法时抛出 ValidationError（errors 含盲文行、列
    定位），不返回任何部分解读文本。
    """
    errors: list[dict] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    n = len(normalized)

    n_cells = sum(1 for ch in normalized if "⠀" <= ch <= "⣿")
    if normalized == "":
        errors.append({"code": "empty", "message": "请输入至少一格盲文。"})
    if n_cells > MAX_CELLS:
        errors.append({
            "code": "too_long",
            "message": f"输入共 {n_cells} 格盲文，超过 {MAX_CELLS} 格上限。",
        })

    out: list[str] = []
    # 当前未结束词的类型："alpha"（字母词）/ "digit"（数字词）/ None（词间）。
    # 跨 ⠤ 断词时保持不变，直到续行的首格确认类型一致。
    word_kind: str | None = None
    # 已消费 "⠤\n"、正在等待续行首格时，记录断词标记位置；否则为 None。
    break_hyphen: int | None = None
    pending_capital: int | None = None  # 等待紧随字母的大写标记位置

    def located(code: str, pos: int, detail: str, length: int = 1) -> None:
        line, col = line_col(normalized, pos)
        errors.append({
            "code": code, "pos": pos, "line": line, "col": col,
            "length": length,
            "message": f"第 {line} 行第 {col} 列{detail}",
        })

    def isolated_capital(pos: int) -> None:
        located(
            "isolated_capital", pos,
            f"的大写标记 {CAPITAL_CELL} 后没有紧随的字母：孤立标记。",
        )

    def enter_number(pos: int) -> None:
        """在 pos 处的数字标记格开启数字词；下一格不是字母点位记孤立标记。"""
        nonlocal word_kind
        word_kind = "digit"
        if pos + 1 >= n or normalized[pos + 1] not in _LETTER_CELL:
            located(
                "isolated_number", pos,
                f"的数字标记 {NUMBER_CELL} 后没有紧随的数字"
                f"（a～i、j 点位）：孤立标记。",
            )

    i = 0
    while i < n:
        ch = normalized[i]

        if ch == "\n":
            if break_hyphen is not None:
                # ⠤\n 之后直接又是换行：续行为空
                located(
                    "hyphen_no_continuation", break_hyphen,
                    f"的断词标记 {HYPHEN_CELL} 后缺少同一词的续行内容"
                    f"（下一行为空行）。",
                )
                break_hyphen = None
                word_kind = None
            if pending_capital is not None:
                isolated_capital(pending_capital)
                pending_capital = None
            out.append("\n")
            word_kind = None  # 普通换行终止词
            i += 1
            continue

        if not "⠀" <= ch <= "⣿":
            # 非法字符：连续段合并为一条错误
            j = i + 1
            while (
                j < n
                and normalized[j] != "\n"
                and not "⠀" <= normalized[j] <= "⣿"
            ):
                j += 1
            sample = normalized[i:j]
            if len(sample) > 10:
                sample = sample[:10] + "…"
            located(
                "illegal_char", i,
                f"起含非法字符 {sample!r}：仅允许 Unicode 六点盲文、"
                f"盲文空格（U+2800）与换行。",
                length=j - i,
            )
            if break_hyphen is not None:
                located(
                    "hyphen_no_continuation", break_hyphen,
                    f"的断词标记 {HYPHEN_CELL} 后缺少同一词的续行内容。",
                )
                break_hyphen = None
                word_kind = None
            i = j
            continue

        if ch == SPACE_CELL:
            if break_hyphen is not None:
                # 续行行首是词间格：断词没有接续同一词
                located(
                    "hyphen_no_continuation", break_hyphen,
                    f"的断词标记 {HYPHEN_CELL} 后缺少同一词的续行内容"
                    f"（续行行首是词间格）。",
                )
                break_hyphen = None
                word_kind = None
            if pending_capital is not None:
                isolated_capital(pending_capital)
                pending_capital = None
            out.append(" ")
            word_kind = None  # 盲文空格终止词
        elif ch in _LETTER_CELL:
            letter = _LETTER_CELL[ch]
            if break_hyphen is not None:
                # 续行首格是字母点位：仅字母词可这样续行；
                # 数字词续行必须以 ⠼ 重新起始。
                if word_kind == "digit":
                    located(
                        "bad_digit_continuation", i,
                        f"：数字词断行后的续行须以数字标记 {NUMBER_CELL} "
                        f"重新起始。",
                    )
                    word_kind = None
                break_hyphen = None
            if word_kind == "digit":
                digit = _LETTER_DIGIT.get(letter)
                if digit is None:
                    located(
                        "number_letter", i,
                        f"的 {ch}（字母 {letter} 点位）出现在数字状态中："
                        f"数字状态只把 a～i、j 点位读作 1～9、0。",
                    )
                else:
                    out.append(digit)
            else:
                out.append(letter.upper() if pending_capital is not None else letter)
                pending_capital = None
                word_kind = "alpha"
        elif ch == CAPITAL_CELL:
            if break_hyphen is not None:
                if word_kind == "digit":
                    located(
                        "bad_digit_continuation", i,
                        f"：数字词断行后的续行须以数字标记 {NUMBER_CELL} "
                        f"重新起始。",
                    )
                    word_kind = None
                break_hyphen = None
            if word_kind == "digit":
                located(
                    "number_capital", i,
                    f"的大写标记 {CAPITAL_CELL} 出现在数字状态中："
                    f"数字状态到词间格或普通换行才结束。",
                )
            else:
                if pending_capital is not None:
                    isolated_capital(pending_capital)
                pending_capital = i
        elif ch == NUMBER_CELL:
            if pending_capital is not None:
                isolated_capital(pending_capital)
                pending_capital = None
            if break_hyphen is not None:
                # 续行首格是数字标记：仅数字词可用它重启续行；
                # 字母词断行后接数字词属于断词前后类型不一致。
                if word_kind == "digit":
                    break_hyphen = None
                    enter_number(i)
                else:
                    located(
                        "break_kind_mismatch", i,
                        f"的数字标记 {NUMBER_CELL} 重启了数字词，但上一行行尾的"
                        f"断词标记 {HYPHEN_CELL} 前是字母词："
                        f"断词标记前后必须是同一类型的未结束词。",
                    )
                    break_hyphen = None
            elif word_kind == "digit":
                located(
                    "number_sign_repeat", i,
                    f"的数字标记 {NUMBER_CELL} 出现在数字状态中："
                    f"数字状态到词间格或普通换行才结束。",
                )
            elif word_kind == "alpha":
                located(
                    "number_sign_in_word", i,
                    f"的数字标记 {NUMBER_CELL} 出现在字母词内部："
                    f"数字标记只能在词首（行首或词间格之后）开启数字词，"
                    f"或在数字词断行续行时重新起始。",
                )
            else:
                enter_number(i)
        elif ch == HYPHEN_CELL:
            if break_hyphen is not None:
                # 续行首格又是断词标记：没有接续同一词的字母 / 数字
                located(
                    "hyphen_no_continuation", break_hyphen,
                    f"的断词标记 {HYPHEN_CELL} 后缺少同一词的续行内容"
                    f"（续行行首仍是断词标记）。",
                )
                break_hyphen = None
                word_kind = None
            if pending_capital is not None:
                isolated_capital(pending_capital)
                pending_capital = None
            if i + 1 < n and normalized[i + 1] == "\n":
                if word_kind is None:
                    # 标记前没有同一行内未结束的词（行首或词间格之后）
                    located(
                        "hyphen_no_word", i,
                        f"的断词标记 {HYPHEN_CELL} 前没有同一行内尚未结束的"
                        f"字母词或数字词：断词标记前后必须是同一类型的"
                        f"未结束词。",
                    )
                else:
                    # 行尾断词：去掉该格及其后的换行，等待续行首格确认
                    break_hyphen = i
                i += 2
                continue
            if i + 1 >= n:
                located(
                    "hyphen_no_continuation", i,
                    f"的断词标记 {HYPHEN_CELL} 位于输入末尾：缺少换行与续行内容。",
                )
            else:
                located(
                    "inline_hyphen", i,
                    f"的连字符 {HYPHEN_CELL} 位于行内："
                    f"{HYPHEN_CELL} 仅作行尾断词标记。",
                )
        else:
            dots = _cell_dots(ch)
            dot_text = "·".join(str(d) for d in sorted(dots))
            located(
                "undefined_cell", i,
                f"的盲文格 {ch}（点 {dot_text}）未定义：仅支持一级字母、"
                f"{CAPITAL_CELL}、{NUMBER_CELL}、{HYPHEN_CELL} 与盲文空格。",
            )
            if break_hyphen is not None:
                located(
                    "hyphen_no_continuation", break_hyphen,
                    f"的断词标记 {HYPHEN_CELL} 后缺少同一词的续行内容。",
                )
                break_hyphen = None
                word_kind = None
        i += 1

    if break_hyphen is not None:
        # 输入以 "⠤\n" 结束：缺少续行内容
        located(
            "hyphen_no_continuation", break_hyphen,
            f"的断词标记 {HYPHEN_CELL} 后缺少续行内容。",
        )
    if pending_capital is not None:
        isolated_capital(pending_capital)

    if errors:
        raise ValidationError(errors)

    result = "".join(out)
    return {
        "text": result,
        "cells": n_cells,
        "chars": len(result),
        "lines": result.count("\n") + 1,
    }
