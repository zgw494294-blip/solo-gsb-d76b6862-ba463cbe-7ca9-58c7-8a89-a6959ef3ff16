"""六点盲文排版引擎测试。"""

import random

import pytest

from app.braille import (
    HYPHEN_CELL,
    NUMBER_CELL,
    SPACE_CELL,
    ValidationError,
    typeset,
    validate,
)
from app.braille import _flatten, build_words, dots_to_unicode


def cells_str(line):
    return "".join(c["text"] for c in line["cells"])


# ---------------------------------------------------------------------------
# 转写规则
# ---------------------------------------------------------------------------

def test_basic_letters():
    r = typeset("ab", 10)
    assert r["braille_text"] == "⠁⠃"
    assert r["lines"][0]["used"] == 2


def test_full_alphabet_unicode_mapping():
    r = typeset("abcdefghijklmnopqrstuvwxyz", 40)
    # a=1 -> U+2801 ... 抽查若干
    text = r["braille_text"]
    assert text[0] == "⠁"  # a
    assert text[8] == "⠊"  # i: dots 2,4
    assert text[9] == "⠚"  # j: dots 2,4,5
    assert text[10] == "⠅"  # k: dots 1,3
    assert text[22] == "⠺"  # w: dots 2,4,5,6
    assert dots_to_unicode(frozenset({1, 3, 5, 6})) == "⠵"  # z


def test_capital_prefixes_dot6_before_each_uppercase():
    r = typeset("A", 10)
    assert cells_str(r["lines"][0]) == "⠠⠁"
    r = typeset("ABc", 10)
    assert cells_str(r["lines"][0]) == "⠠⠁⠠⠃⠉"
    cell_kinds = [c["kind"] for c in r["lines"][0]["cells"]]
    assert cell_kinds == ["capital", "char", "capital", "char", "char"]


def test_digit_word_uses_number_sign_and_aj_mapping():
    # 1..9,0 -> a..i,j
    r = typeset("10", 10)
    assert cells_str(r["lines"][0]) == NUMBER_CELL + "⠁⠚"
    r = typeset("1234567890", 40)
    assert cells_str(r["lines"][0]) == "⠼⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚"


def test_consecutive_spaces_collapse_to_one_word_gap():
    r = typeset("a     b", 10)
    assert r["braille_text"] == "⠁" + SPACE_CELL + "⠃"
    assert r["lines"][0]["used"] == 3


def test_no_space_cells_at_line_edges():
    r = typeset("   ab cd   ", 10)
    for line in r["lines"]:
        kinds = [c["kind"] for c in line["cells"]]
        assert kinds[0] != "space"
        assert kinds[-1] != "space"


def test_tabs_and_punctuation_are_illegal_with_location():
    with pytest.raises(ValidationError) as ei:
        validate("ab\tcd", 10)
    err = ei.value.errors[0]
    assert err["code"] == "illegal_char"
    assert (err["line"], err["col"]) == (1, 3)

    with pytest.raises(ValidationError) as ei:
        validate("ab\ncd#ef", 10)
    err = ei.value.errors[0]
    assert err["code"] == "illegal_char"
    assert (err["line"], err["col"]) == (2, 3)


def test_mixed_word_location():
    with pytest.raises(ValidationError) as ei:
        validate("ab12c", 10)
    err = ei.value.errors[0]
    assert err["code"] == "mixed_word"
    assert (err["line"], err["col"]) == (1, 1)
    assert err["word"] == "ab12c"

    with pytest.raises(ValidationError) as ei:
        validate("xx  9z", 10)
    err = [e for e in ei.value.errors if e["code"] == "mixed_word"][0]
    assert (err["line"], err["col"]) == (1, 5)


def test_rejects_empty_space_only_and_too_long():
    with pytest.raises(ValidationError) as ei:
        validate("", 10)
    assert ei.value.errors[0]["code"] == "empty"

    with pytest.raises(ValidationError) as ei:
        validate("   \n  \t ", 10)
    codes = {e["code"] for e in ei.value.errors}
    assert "illegal_char" in codes
    assert "no_alnum" in codes

    with pytest.raises(ValidationError) as ei:
        validate("a" * 501, 10)
    assert ei.value.errors[0]["code"] == "too_long"
    validate("a" * 500, 10)  # 边界可用


def test_bad_width():
    with pytest.raises(ValidationError) as ei:
        validate("abc", 9)
    assert ei.value.errors[0]["code"] == "bad_width"
    with pytest.raises(ValidationError) as ei:
        validate("abc", 41)
    assert ei.value.errors[0]["code"] == "bad_width"


# ---------------------------------------------------------------------------
# 排版规则
# ---------------------------------------------------------------------------

def test_hard_newline_is_paragraph_break():
    r = typeset("ab\ncd", 40)
    assert r["paragraphs"] == 2
    assert r["total_lines"] == 2
    assert r["braille_text"] == "⠁⠃\n⠉⠙"


def test_blank_paragraph_renders_blank_line():
    r = typeset("ab\n\ncd", 40)
    assert r["total_lines"] == 3
    assert r["lines"][1]["blank"] is True
    assert r["braille_text"].split("\n") == ["⠁⠃", "", "⠉⠙"]


def test_dp_prefers_smaller_square_sum_over_greedy():
    # 宽 10，词长 6,3,3：贪心 6+1+3=10 / 剩 3 -> 平方 49
    # 更优：6 独占一行(r4) + 3+1+3=7(r3) -> 16+9=25
    r = typeset("abcdef ghi jkl", 10)
    assert r["total_lines"] == 2
    assert r["breaks"] == 0
    assert [l["source"] for l in r["lines"]] == ["abcdef", "ghi jkl"]


def test_overlong_word_breaks_with_hyphen_dot36():
    r = typeset("abcdefghijkl", 10)  # 12 个字母
    assert r["breaks"] == 1
    assert r["hyphen_lines"] == [1]
    assert r["total_lines"] == 2
    l1, l2 = r["lines"]
    assert cells_str(l1).endswith(HYPHEN_CELL)
    assert l1["used"] == 6  # 5 字符 + 连字符
    assert l1["source"] == "abcde-"
    assert l2["source"] == "fghijkl"
    assert l2["used"] == 7
    assert not cells_str(l2).endswith(HYPHEN_CELL)


def test_forced_break_tie_uses_lexicographically_smaller_breakpoint():
    # p=5 与 p=6 平方和相同(25)，取断点更靠前的 p=5
    r = typeset("abcdefghijkl", 10)
    assert r["lines"][0]["source"] == "abcde-"


def test_digit_continuation_readds_number_sign():
    r = typeset("123456789012", 10)  # 12 位数字
    assert r["breaks"] == 1
    assert r["number_reopened"] == 1
    l1, l2 = r["lines"]
    assert cells_str(l1).startswith(NUMBER_CELL)
    assert cells_str(l1).endswith(HYPHEN_CELL)
    assert cells_str(l2).startswith(NUMBER_CELL)  # 续行重加数字标记
    assert l1["source"] == "12345-"
    assert l2["source"] == "6789012"


def test_ten_digit_word_must_break_because_sign_takes_a_cell():
    r = typeset("1234567890", 10)
    assert r["breaks"] == 1
    assert r["total_lines"] == 2
    assert all(l["cells"][0]["kind"] == "number" for l in r["lines"])


def test_break_after_full_word_shares_line_with_overlong_prefix():
    # 行宽 10：整词 "ab" 后接 14 字母超宽词。首行可为
    # "ab" + 词间格 + 超宽词首段 5 字符 + 点36连字符 = 10 格，
    # 共两行（旧实现漏掉该候选，把 "ab" 独占一行排成三行）。
    r = typeset("ab cdefghijklmnop", 10)
    assert r["total_lines"] == 2
    assert r["breaks"] == 1
    assert r["hyphen_lines"] == [1]
    l1, l2 = r["lines"]
    assert l1["source"] == "ab cdefg-"
    assert l1["used"] == 9  # ab(2)+格(1)+5字母(5)+连字符(1)
    assert l1["remain"] == 1
    assert cells_str(l1) == "⠁⠃" + SPACE_CELL + "⠉⠙⠑⠋⠛" + HYPHEN_CELL
    assert l2["source"] == "hijklmnop"
    assert l2["used"] == 9
    # k=5 与 k=6 平方和均为 2，取断点序列字典序更小的 k=5
    assert sum((10 - l["used"]) ** 2 for l in r["lines"]) == 2


def test_break_after_full_word_counts_capital_markers():
    # 超宽词首字符大写：大写标记占 1 格，首段可用字母少 1。
    r = typeset("ab Cdefghijklmnop", 10)
    assert r["total_lines"] == 2
    assert r["breaks"] == 1
    l1, l2 = r["lines"]
    assert l1["source"] == "ab Cdef-"
    assert l1["used"] == 9  # ab(2)+格(1)+大写标记(1)+Cdef(4)+连字符(1)
    kinds = [c["kind"] for c in l1["cells"]]
    assert kinds == [
        "char", "char", "space",
        "capital", "char", "char", "char", "char",
        "hyphen",
    ]
    assert len(kinds) == 9
    assert l2["source"] == "ghijklmnop"
    assert l2["used"] == 10


def test_break_after_full_word_digit_continuation_readds_sign():
    # 数字超宽词跨词断行：词首数字标记占 1 格，首段为
    # "ab" + 词间格 + 数字标记 + 5 位数字 + 点36连字符 = 10 格（余 0）；
    # 续行行首重新加数字标记。旧实现漏算跨词数字标记，used 误为 9。
    r = typeset("ab 12345678901234", 10)
    assert r["total_lines"] == 2
    assert r["breaks"] == 1
    assert r["number_reopened"] == 1
    l1, l2 = r["lines"]
    assert l1["source"] == "ab 12345-"
    assert l1["used"] == 10  # ab(2)+格(1)+数字标记(1)+12345(5)+连字符(1)
    assert l1["remain"] == 0
    assert cells_str(l1) == (
        "⠁⠃" + SPACE_CELL + NUMBER_CELL + "⠁⠃⠉⠙⠑" + HYPHEN_CELL
    )
    assert cells_str(l2).startswith(NUMBER_CELL)
    assert l2["source"] == "678901234"
    assert l2["used"] == 10


def test_complete_digit_word_after_gap_gets_number_sign():
    # 行内完整数字词（非行首）也要数字标记，且占格计入排版：
    # "ab" + 格 + 标记 + "12" = 6 格。
    r = typeset("ab 12", 10)
    l = r["lines"][0]
    assert l["source"] == "ab 12"
    assert l["used"] == 6
    assert cells_str(l) == "⠁⠃" + SPACE_CELL + NUMBER_CELL + "⠁⠃"
    kinds = [c["kind"] for c in l["cells"]]
    assert kinds == ["char", "char", "space", "number", "char", "char"]


def test_each_digit_word_after_gap_has_its_own_number_sign():
    r = typeset("1 2 3", 10)
    l = r["lines"][0]
    assert cells_str(l) == (
        NUMBER_CELL + "⠁" + SPACE_CELL + NUMBER_CELL + "⠃"
        + SPACE_CELL + NUMBER_CELL + "⠉"
    )
    assert l["used"] == 8


def test_number_sign_forces_wrap_of_full_digit_word():
    # 宽 10：abcdef(6)+格(1)+数字标记(1)+123(3)=11 放不下，完整数字词整体换行。
    r = typeset("abcdef 123", 10)
    assert r["breaks"] == 0
    assert r["total_lines"] == 2
    l1, l2 = r["lines"]
    assert l1["source"] == "abcdef"
    assert l2["source"] == "123"
    assert cells_str(l2) == NUMBER_CELL + "⠁⠃⠉"
    assert l2["used"] == 4


def test_non_overlong_word_never_splits():
    r = typeset("abcdefghij", 10)  # 恰好 10 格
    assert r["breaks"] == 0
    assert r["total_lines"] == 1
    assert r["lines"][0]["used"] == 10


def test_capital_inside_continued_word_keeps_its_own_dot6():
    # aBcdefghijkl（13 字符，B 额外带 1 个大写标记），宽 10：
    # 最优断点在 e 之后（行1 余 3、行2 余 3，平方和 18；
    # 若断在 f 之后则为 4+16=20）。B 的点 6 标记随 B 留在第一行。
    r = typeset("aBcdefghijkl", 10)
    l1, l2 = r["lines"]
    assert cells_str(l1) == "⠁⠠⠃⠉⠙⠑⠤"
    assert cells_str(l2) == "⠋⠛⠓⠊⠚⠅⠇"
    assert r["breaks"] == 1


def test_breaks_have_priority_over_line_count():
    # 12 字符超宽词必然断 1 次；检验统计一致
    r = typeset("aaaaaaaaaa bbbbbbbbbbbb", 10)
    assert r["breaks"] == 1
    assert r["total_lines"] == 3
    assert [l["source"] for l in r["lines"]][0] == "aaaaaaaaaa"


def test_long_digit_word_global_square_optimum_beats_greedy():
    # 500 位数字、宽 40：逐行塞满(每行38字符)会使末行余 33 格，平方和 1089；
    # DP 全局平衡为 5 行 35 字符(余3) + 9 行 36/37 字符(余2)，平方和 81。
    r = typeset("9" * 500, 40)
    used = [l["used"] for l in r["lines"]]
    assert used == [37] * 5 + [38] * 9
    assert sum((40 - u) ** 2 for u in used) == 81
    assert sum(1 for l in r["lines"] for c in l["cells"] if c["kind"] == "char") == 500
    assert all(l["cells"][0]["kind"] == "number" for l in r["lines"])
    assert r["number_reopened"] == 13
    assert all(l["cells"][-1]["kind"] == "hyphen" for l in r["lines"][:-1])
    assert r["lines"][-1]["cells"][-1]["kind"] == "char"


def test_continuation_segment_that_exactly_fills_line_has_no_hyphen():
    # 60 位数字、宽 40：
    # 贪心塞满首行(sign+38字符+连字符=40)会使末行余 17，平方和 289；
    # DP 取 29 字(余9) + 31 字(余8)，平方和 145；且续行段放完无连字符。
    r = typeset("9" * 60, 40)
    assert r["total_lines"] == 2
    assert r["breaks"] == 1
    l1, l2 = r["lines"]
    assert l1["cells"][-1]["kind"] == "hyphen"
    assert l2["cells"][-1]["kind"] == "char"  # 续行段结束，无连字符
    assert cells_str(l2).startswith(NUMBER_CELL)
    assert (40 - l1["used"]) ** 2 + (40 - l2["used"]) ** 2 == 145


def test_all_lines_within_width():
    r = typeset("the quick brown fox 12345 abcdefghijklmnop", 12)
    for line in r["lines"]:
        assert line["used"] <= 12


# ---------------------------------------------------------------------------
# 与独立暴力 DFS 的随机对照
# ---------------------------------------------------------------------------

def _word_sign(word):
    return 1 if word.kind == "digit" else 0


def _bruteforce(tokens, width):
    """独立的记忆化 DP：逐字符枚举所有合规排法，返回最优
    ((断词次数, 行数, 平方和, 断点序列), 行记录) 。
    行记录 (start, end, used, broke)。"""
    import functools

    atoms = _flatten(tokens)
    n = len(atoms)

    def cost(atom):
        return 1 + atom[1][3].extra

    @functools.lru_cache(maxsize=None)
    def solve(i):
        if i == n:
            return (0, 0, 0, ()), ()
        if atoms[i][0] == "gap":
            return solve(i + 1)

        wi = atoms[i][1][0]
        word = atoms[i][1][2]
        sign = 1 if word.kind == "digit" else 0

        best = None

        def consider(end, used, broke, bpoint):
            nonlocal best
            (b, l, s, bps), recs = solve(end)
            cand = (
                b + (1 if broke else 0),
                l + 1,
                s + (width - used) ** 2,
                (bpoint,) + bps,
            ), ((i, end, used, broke),) + recs
            if best is None or cand[0] < best[0]:
                best = cand

        # 同词字符逐位加入
        u = sign + cost(atoms[i])
        j = i + 1
        while j < n and atoms[j][0] == "char" and atoms[j][1][0] == wi:
            # 在 j 之前断开（j 字符已计入），后面还得有同词字符
            if (
                u + cost(atoms[j]) + 1 <= width
                and j + 1 < n
                and atoms[j + 1][0] == "char"
                and atoms[j + 1][1][0] == wi
            ):
                consider(j + 1, u + cost(atoms[j]) + 1, True, j)
            u += cost(atoms[j])
            j += 1

        if u <= width:
            # 词末结束本行
            consider(j, u, False, j - 1)
            # 继续拼 "词间格 + 整词"；整词放不下时改取
            # "词间格 + 超宽词首段 + 连字符" 的跨词断词候选。
            p, uu = j, u
            while (
                p < n and atoms[p][0] == "gap"
                and uu + 1 <= width
                and p + 1 < n and atoms[p + 1][0] == "char"
                and atoms[p + 1][1][1] == 0
            ):
                nwi = atoms[p + 1][1][0]
                nw = atoms[p + 1][1][2]
                nsign = _word_sign(nw)
                if uu + 1 + nsign + nw.base_len > width:
                    # 首段格数：词间格与数字标记之外，另留 1 格连字符
                    budget = width - (uu + 1) - nsign
                    np0 = p + 1
                    np1 = np0
                    while np1 < n and atoms[np1][0] == "char" and atoms[np1][1][0] == nwi:
                        np1 += 1
                    pu = 0
                    for q in range(np0, np1):
                        pu += cost(atoms[q])
                        if pu + 1 > budget or q + 1 >= np1:
                            break
                        consider(q + 1, uu + 1 + nsign + pu + 1, True, q)
                    break
                np = p + 2
                while np < n and atoms[np][0] == "char" and atoms[np][1][0] == nwi:
                    np += 1
                uu += 1 + nsign + nw.base_len
                p = np
                consider(p, uu, False, p - 1)

        assert best is not None
        return best

    return solve(0)


def _line_braille(atoms, rec):
    i, end, used, broke = rec
    out = []
    for t in range(i, end):
        if atoms[t][0] == "gap":
            out.append(SPACE_CELL)
        else:
            _, (wi, ci, w, ch) = atoms[t]
            # 数字词渲染起点：行首（词首或续行段）或词间格后的词首。
            if w.kind == "digit" and (t == i or ci == 0):
                out.append(NUMBER_CELL)
            if ch.extra:
                out.append("⠠")
            out.append(dots_to_unicode(ch.dots))
    if broke:
        out.append(HYPHEN_CELL)
    assert len(out) == used
    return "".join(out)


@pytest.mark.parametrize("seed", range(120))
def test_fuzz_matches_bruteforce(seed):
    rng = random.Random(seed)
    nwords = rng.randint(1, 6)
    words = []
    for _ in range(nwords):
        if rng.random() < 0.4:
            length = rng.randint(1, 14)
            words.append("".join(rng.choice("0123456789") for _ in range(length)))
        else:
            length = rng.randint(1, 14)
            w = "".join(rng.choice("abcdefgh") for _ in range(length))
            if rng.random() < 0.5:
                k = rng.randrange(length)
                w = w[:k] + w[k].upper() + w[k + 1:]
            words.append(w)
    source = " ".join(words)
    width = rng.randint(10, 14)

    tokens = build_words(source)
    atoms = _flatten(tokens)
    best = _bruteforce(tokens, width)
    assert best is not None

    r = typeset(source, width)
    assert r["breaks"] == best[0][0]
    assert r["total_lines"] == best[0][1]
    expected_sq = sum((width - ln["used"]) ** 2 for ln in r["lines"])
    assert best[0][2] == expected_sq

    expected_lines = [_line_braille(atoms, rec) for rec in best[1]]
    got = [
        "".join(c["text"] for c in ln["cells"])
        for ln in r["lines"]
    ]
    assert got == expected_lines
