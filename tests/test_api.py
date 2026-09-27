"""FastAPI 接口层测试。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_index_and_assets_served():
    assert client.get("/").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_typeset_ok():
    resp = client.post("/api/typeset", json={"text": "ab", "width": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["braille_text"] == "⠁⠃"
    assert data["lines"][0]["cells"][0]["dots"] == [1]


def test_typeset_illegal_char_is_located():
    resp = client.post("/api/typeset", json={"text": "ab\tc", "width": 10})
    assert resp.status_code == 422
    data = resp.json()
    assert data["ok"] is False
    err = next(e for e in data["errors"] if e["code"] == "illegal_char")
    assert (err["line"], err["col"]) == (1, 3)


def test_typeset_mixed_word():
    resp = client.post("/api/typeset", json={"text": "ab1", "width": 10})
    assert resp.status_code == 422
    codes = {e["code"] for e in resp.json()["errors"]}
    assert "mixed_word" in codes


def test_typeset_bad_width():
    resp = client.post("/api/typeset", json={"text": "abc", "width": 41})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["code"] == "bad_width"


def test_typeset_missing_field():
    resp = client.post("/api/typeset", json={"text": "abc"})
    assert resp.status_code == 422
    assert resp.json()["ok"] is False


def test_typeset_too_long():
    resp = client.post("/api/typeset", json={"text": "a" * 501, "width": 10})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["code"] == "too_long"


def test_decode_ok():
    resp = client.post("/api/decode", json={"text": "⠠⠓⠑⠇⠇⠕⠀⠼⠃⠚⠃⠋"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["text"] == "Hello 2026"
    assert data["cells"] == 12


def test_decode_error_located_and_no_partial_text():
    resp = client.post("/api/decode", json={"text": "⠁⠃\n⠿"})
    assert resp.status_code == 422
    data = resp.json()
    assert data["ok"] is False
    assert "text" not in data  # 不输出部分解读文本
    err = data["errors"][0]
    assert err["code"] == "undefined_cell"
    assert (err["line"], err["col"]) == (2, 1)


def test_decode_bad_digit_continuation():
    resp = client.post("/api/decode", json={"text": "⠼⠁⠤\n⠃"})
    assert resp.status_code == 422
    codes = {e["code"] for e in resp.json()["errors"]}
    assert "bad_digit_continuation" in codes


@pytest.mark.parametrize("src,code,line,col", [
    ("⠁⠼⠃", "number_sign_in_word", 1, 2),       # 字母词内的数字标记
    ("⠤\n⠁", "hyphen_no_word", 1, 1),             # 行首断词标记前无未结束词
    ("⠁⠤\n⠼⠃", "break_kind_mismatch", 2, 1),  # 字母词断行后续数字词
])
def test_decode_illegal_word_boundary(src, code, line, col):
    resp = client.post("/api/decode", json={"text": src})
    assert resp.status_code == 422
    data = resp.json()
    assert data["ok"] is False
    assert "text" not in data  # 整体失败，不返回部分文本
    err = next(e for e in data["errors"] if e["code"] == code)
    assert (err["line"], err["col"]) == (line, col)


def test_decode_valid_break_continuation_ok():
    resp = client.post("/api/decode", json={"text": "⠁⠃⠉⠤\n⠙⠑"})
    assert resp.status_code == 200
    assert resp.json()["text"] == "abcde"


def test_decode_missing_field():
    resp = client.post("/api/decode", json={})
    assert resp.status_code == 422
    assert resp.json()["ok"] is False


def test_decode_too_long():
    resp = client.post("/api/decode", json={"text": "⠁" * 501})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["code"] == "too_long"


def test_avoid_ok_feasible():
    resp = client.post("/api/avoid", json={
        "front": "a", "back": "a", "width": 10, "min_distance": 1.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["feasible"] is True
    assert data["conflict_count"] == 0
    assert data["conflicts"] == []
    assert (data["dx"], data["dy"]) == (0.0, 0.0)
    assert data["front"]["braille_text"] == "⠁"
    assert data["back"]["braille_text"] == "⠁"


def test_avoid_unavoidable_conflicts():
    resp = client.post("/api/avoid", json={
        "front": "yyyyyyyyyy", "back": "yyyyyyyyyy",
        "width": 10, "min_distance": 3.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["feasible"] is False
    assert data["conflict_count"] == len(data["conflicts"]) > 0
    pair = data["conflicts"][0]
    assert pair["front"]["face"] == "front"
    assert pair["back"]["face"] == "back"
    assert set(pair["front"]) == {"face", "row", "cell", "dot"}


def test_avoid_bad_min_distance():
    for bad in (0.15, 0.05, 3.1, 0, -0.5):
        resp = client.post("/api/avoid", json={
            "front": "a", "back": "a", "width": 10, "min_distance": bad,
        })
        assert resp.status_code == 422
        assert resp.json()["errors"][0]["code"] == "bad_min_distance"


def test_avoid_text_errors_carry_face():
    resp = client.post("/api/avoid", json={
        "front": "ab\tc", "back": "ok", "width": 10, "min_distance": 1.0,
    })
    assert resp.status_code == 422
    err = resp.json()["errors"][0]
    assert err["code"] == "illegal_char"
    assert err["face"] == "front"
    assert (err["line"], err["col"]) == (1, 3)

    resp = client.post("/api/avoid", json={
        "front": "ok", "back": "ab\tc", "width": 10, "min_distance": 1.0,
    })
    assert resp.json()["errors"][0]["face"] == "back"


def test_avoid_bad_width_reported_once():
    resp = client.post("/api/avoid", json={
        "front": "a", "back": "b", "width": 41, "min_distance": 1.0,
    })
    assert resp.status_code == 422
    assert [e["code"] for e in resp.json()["errors"]] == ["bad_width"]


def test_avoid_missing_field():
    resp = client.post("/api/avoid", json={"front": "a", "back": "a", "width": 10})
    assert resp.status_code == 422
    assert resp.json()["ok"] is False


def test_inspect_ok_shift_recovers_offset():
    resp = client.post("/api/inspect", json={
        "text": "a", "width": 10, "points": "0.1,0.2",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert (data["dx"], data["dy"]) == (-0.1, -0.2)
    assert data["matched"] == 1
    assert data["perfect"] is True
    assert data["missing_dots"] == []
    assert data["extra_points"] == []
    assert data["layout"]["braille_text"] == "⠁"


def test_inspect_missing_and_extra_reported():
    # ab 的理论点为 (0,0)、(6,0)、(6,2.5) 毫米；实测第一点对齐、第二点多余
    resp = client.post("/api/inspect", json={
        "text": "ab", "width": 10, "points": "0,0\n9,9",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["perfect"] is False
    assert data["matched"] == 1
    assert data["missing"] == 2
    assert data["missing_dots"] == [
        {"row": 0, "cell": 1, "dot": 1},
        {"row": 0, "cell": 1, "dot": 2},
    ]
    assert data["extra_points"] == [{"line": 2, "x": 9.0, "y": 9.0}]


def test_inspect_empty_points_ok():
    resp = client.post("/api/inspect", json={"text": "a", "width": 10, "points": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert data["matched"] == 0
    assert data["missing"] == data["theory_dots"] == 1
    assert data["extra"] == 0


def test_inspect_bad_points_located():
    resp = client.post("/api/inspect", json={
        "text": "a", "width": 10, "points": "0,0\n1.25,3",
    })
    assert resp.status_code == 422
    data = resp.json()
    assert data["ok"] is False
    err = data["errors"][0]
    assert err["code"] == "bad_points"
    assert err["field"] == "points"
    assert (err["line"], err["col"]) == (2, 1)


def test_inspect_text_too_long_100():
    resp = client.post("/api/inspect", json={
        "text": "a" * 101, "width": 10, "points": "",
    })
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    assert [e["code"] for e in errors] == ["too_long"]
    assert "100" in errors[0]["message"]


def test_inspect_too_many_points():
    resp = client.post("/api/inspect", json={
        "text": "a", "width": 10, "points": "\n".join(["0,0"] * 401),
    })
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["code"] == "too_many_points"


def test_inspect_text_and_points_errors_together():
    resp = client.post("/api/inspect", json={
        "text": "a1", "width": 10, "points": "x,y",
    })
    assert resp.status_code == 422
    fields = {e["field"] for e in resp.json()["errors"]}
    assert fields == {"text", "points"}


def test_inspect_bad_width():
    resp = client.post("/api/inspect", json={
        "text": "a", "width": 41, "points": "",
    })
    assert resp.status_code == 422
    assert [e["code"] for e in resp.json()["errors"]] == ["bad_width"]


def test_inspect_missing_field():
    resp = client.post("/api/inspect", json={"text": "a", "width": 10})
    assert resp.status_code == 422
    assert resp.json()["ok"] is False
