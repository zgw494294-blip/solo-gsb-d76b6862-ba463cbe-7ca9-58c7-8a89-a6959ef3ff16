"""六点盲文识读引擎测试。"""

import pytest

from app.braille import ValidationError, typeset
from app.reader import decode


def err_codes(excinfo):
    return [e["code"] for e in excinfo.value.errors]


# ---------------------------------------------------------------------------
# 基本识读
# ---------------------------------------------------------------------------

def test_basic_letters():
    assert decode("⠁⠃⠉")["text"] == "abc"


def test_full_alphabet():
    assert decode(
        "⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚⠅⠇⠍⠝⠕⠏⠟⠗⠎⠞⠥⠧⠺⠭⠽⠵"
    )["text"] == "abcdefghijklmnopqrstuvwxyz"


def test_blank_becomes_space_and_newline_kept():
    r = decode("⠁⠀⠃\n⠉")
    assert r["text"] == "a b\nc"
    assert r["cells"] == 4
    assert r["lines"] == 2


def test_blank_lines_are_kept():
    assert decode("⠁\n\n⠃")["text"] == "a\n\nb"


# ---------------------------------------------------------------------------
# 大写标记 ⠠
# ---------------------------------------------------------------------------

def test_capital_marks_only_the_next_letter():
    assert decode("⠠⠁⠃⠉")["text"] == "Abc"
    assert decode("⠁⠠⠃⠉")["text"] == "aBc"
    assert decode("⠠⠁⠀⠠⠃")["text"] == "A B"


@pytest.mark.parametrize("src", ["⠠", "⠠⠀⠁", "⠠\n⠁", "⠠⠠⠁"])
def test_isolated_capital_sign(src):
    with pytest.raises(ValidationError) as ei:
        decode(src)
    assert "isolated_capital" in err_codes(ei)


def test_isolated_capital_position():
    with pytest.raises(ValidationError) as ei:
        decode("⠁⠃⠠")
    err = ei.value.errors[0]
    assert err["code"] == "isolated_capital"
    assert (err["line"], err["col"]) == (1, 3)


# ---------------------------------------------------------------------------
# 数字标记 ⠼
# ---------------------------------------------------------------------------

def test_number_sign_reads_aj_as_digits():
    assert decode("⠼⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚")["text"] == "1234567890"


def test_number_state_ends_at_blank_and_newline():
    assert decode("⠼⠁⠀⠁")["text"] == "1 a"
    assert decode("⠼⠁\n⠁")["text"] == "1\na"


@pytest.mark.parametrize("src", ["⠼", "⠼⠀⠁", "⠼\n⠁", "⠼⠼⠁"])
def test_isolated_number_sign(src):
    with pytest.raises(ValidationError) as ei:
        decode(src)
    assert "isolated_number" in err_codes(ei)


def test_number_state_rejects_letter_k_to_z():
    with pytest.raises(ValidationError) as ei:
        decode("⠼⠁⠅")  # ⠅ = k 点位
    assert "number_letter" in err_codes(ei)


def test_number_state_rejects_capital_sign():
    with pytest.raises(ValidationError) as ei:
        decode("⠼⠁⠠⠃")
    assert "number_capital" in err_codes(ei)


def test_number_state_rejects_second_number_sign():
    with pytest.raises(ValidationError) as ei:
        decode("⠼⠁⠼⠃")
    assert "number_sign_repeat" in err_codes(ei)


def test_number_sign_must_open_or_reopen_a_number_word():
    # ⠼ 只能开启数字词或重启数字词续行；字母词内部的 ⠼ 非法
    with pytest.raises(ValidationError) as ei:
        decode("⠁⠼⠃")  # 不得读成 a2
    err = ei.value.errors[0]
    assert err["code"] == "number_sign_in_word"
    assert (err["line"], err["col"]) == (1, 2)

    with pytest.raises(ValidationError) as ei:
        decode("⠁⠃⠀⠉⠼⠙")
    err = ei.value.errors[0]
    assert err["code"] == "number_sign_in_word"
    assert (err["line"], err["col"]) == (1, 5)


def test_number_word_after_space_or_plain_newline_still_opens():
    assert decode("⠁⠀⠼⠃")["text"] == "a 2"
    assert decode("⠼⠁\n⠼⠃")["text"] == "1\n2"


# ---------------------------------------------------------------------------
# 断词标记 ⠤
# ---------------------------------------------------------------------------

def test_hyphen_joins_word_across_lines():
    assert decode("⠁⠃⠉⠤\n⠙⠑")["text"] == "abcde"


def test_inline_hyphen_is_located():
    with pytest.raises(ValidationError) as ei:
        decode("⠁⠤⠃")
    err = ei.value.errors[0]
    assert err["code"] == "inline_hyphen"
    assert (err["line"], err["col"]) == (1, 2)


@pytest.mark.parametrize("src", ["⠁⠤", "⠁⠤\n", "⠁⠤\n\n⠃"])
def test_hyphen_without_continuation(src):
    with pytest.raises(ValidationError) as ei:
        decode(src)
    assert "hyphen_no_continuation" in err_codes(ei)


def test_digit_continuation_must_restart_with_number_sign():
    assert decode("⠼⠁⠃⠤\n⠼⠉⠙")["text"] == "1234"
    with pytest.raises(ValidationError) as ei:
        decode("⠼⠁⠃⠤\n⠉⠙")
    assert "bad_digit_continuation" in err_codes(ei)


def test_bad_digit_continuation_position():
    with pytest.raises(ValidationError) as ei:
        decode("⠼⠁⠤\n⠃")
    err = [e for e in ei.value.errors if e["code"] == "bad_digit_continuation"][0]
    assert (err["line"], err["col"]) == (2, 1)


def test_hyphen_requires_unfinished_word_before_it():
    # 行首直接是断词标记：标记前没有未结束词，不得读成 a
    with pytest.raises(ValidationError) as ei:
        decode("⠤\n⠁")
    err = [e for e in ei.value.errors if e["code"] == "hyphen_no_word"][0]
    assert (err["line"], err["col"]) == (1, 1)

    # 词间格之后的行尾断词标记前也没有未结束词
    with pytest.raises(ValidationError) as ei:
        decode("⠁⠀⠤\n⠃")
    err = [e for e in ei.value.errors if e["code"] == "hyphen_no_word"][0]
    assert (err["line"], err["col"]) == (1, 3)


def test_break_continuation_must_match_word_kind():
    # 字母词断行后续行以 ⠼ 重启数字词：前后不是同一类型，不得读成 a2
    with pytest.raises(ValidationError) as ei:
        decode("⠁⠤\n⠼⠃")
    err = [e for e in ei.value.errors if e["code"] == "break_kind_mismatch"][0]
    assert (err["line"], err["col"]) == (2, 1)

    # 数字词断行后直接续字母词同样前后类型不一致
    with pytest.raises(ValidationError) as ei:
        decode("⠼⠃⠤\n⠁")
    codes = err_codes(ei)
    assert "bad_digit_continuation" in codes
    assert "break_kind_mismatch" not in codes


def test_letter_continuation_still_joins_word():
    # 合法字母续行（含大写标记）
    assert decode("⠁⠃⠤\n⠉")["text"] == "abc"
    assert decode("⠁⠤\n⠠⠃")["text"] == "aB"
    assert decode("⠠⠁⠤\n⠃")["text"] == "Ab"


def test_hyphen_break_ends_when_space_or_blank_line_follows():
    for src, pos in [("⠁⠤\n⠀⠃", (1, 2)), ("⠁⠤\n\n⠃", (1, 2)), ("⠁⠤\n", (1, 2))]:
        with pytest.raises(ValidationError) as ei:
            decode(src)
        err = [e for e in ei.value.errors if e["code"] == "hyphen_no_continuation"][0]
        assert (err["line"], err["col"]) == pos, src


def test_hyphen_break_continuation_must_be_word_content():
    # 续行首格又是断词标记，前一个断词没有接续内容
    with pytest.raises(ValidationError) as ei:
        decode("⠁⠤\n⠤\n⠃")
    assert "hyphen_no_continuation" in err_codes(ei)

    # 续行首格是未定义点位：除未定义外，断词同样缺少续行内容
    with pytest.raises(ValidationError) as ei:
        decode("⠁⠤\n⠿⠃")
    codes = err_codes(ei)
    assert "undefined_cell" in codes
    assert "hyphen_no_continuation" in codes


# ---------------------------------------------------------------------------
# 非法输入
# ---------------------------------------------------------------------------

def test_undefined_cell_is_located():
    with pytest.raises(ValidationError) as ei:
        decode("⠁⠃\n⠿")  # ⠿ = 点 123456，未定义
    err = ei.value.errors[0]
    assert err["code"] == "undefined_cell"
    assert (err["line"], err["col"]) == (2, 1)


def test_eight_dot_pattern_is_undefined():
    with pytest.raises(ValidationError) as ei:
        decode("⣿")  # U+28FF，含点 7、8
    assert ei.value.errors[0]["code"] == "undefined_cell"


def test_illegal_chars_are_located():
    with pytest.raises(ValidationError) as ei:
        decode("⠁ab⠃")
    err = ei.value.errors[0]
    assert err["code"] == "illegal_char"
    assert (err["line"], err["col"]) == (1, 2)
    assert err["length"] == 2

    with pytest.raises(ValidationError) as ei:
        decode("⠁ ⠃")  # 普通空格不允许，词间格须用 U+2800
    assert ei.value.errors[0]["code"] == "illegal_char"


def test_too_long_counts_cells_not_newlines():
    decode("⠁" * 500)  # 边界可用
    with pytest.raises(ValidationError) as ei:
        decode("⠁" * 501)
    assert ei.value.errors[0]["code"] == "too_long"
    decode(("⠁" * 100 + "\n") * 5)  # 换行不占格数


def test_empty_input():
    with pytest.raises(ValidationError) as ei:
        decode("")
    assert ei.value.errors[0]["code"] == "empty"


def test_errors_suppress_partial_output():
    # 即使前面有可解读内容，出错也不返回文本
    with pytest.raises(ValidationError):
        decode("⠁⠃⠉⠿")


# ---------------------------------------------------------------------------
# 与排版引擎的往返对照
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,width", [
    ("Hello 2026", 16),
    ("The quick brown fox 12345", 40),
    ("ab\ncd", 40),
    ("ab\n\ncd", 40),
    ("abcdefghijkl", 10),       # 超宽词断行 -> ⠤ 接续
    ("123456789012", 10),       # 数字词断行 -> 续行重加 ⠼
    ("ab cdefghijklmnop", 10),  # 跨词断行
])
def test_roundtrip_typeset_then_decode(src, width):
    braille_text = typeset(src, width)["braille_text"]
    assert decode(braille_text)["text"] == src
