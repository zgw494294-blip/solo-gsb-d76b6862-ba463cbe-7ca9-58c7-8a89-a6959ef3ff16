"""FastAPI 后端：排版 / 识读接口 + 静态页面托管。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .avoid import avoid
from .braille import ValidationError, typeset
from .emboss import emboss_path
from .inspect import inspect
from .reader import decode

app = FastAPI(title="六点盲文排版台", version="1.4.0")


class TypesetIn(BaseModel):
    # 范围与长度由 braille.validate 统一处理并给出定位错误；
    # 这里仅约束基本类型。
    text: str = Field(..., description="ASCII 字母、数字、空格与换行，不超过 500 字符")
    width: int = Field(..., description="每行 10～40 格")


class DecodeIn(BaseModel):
    # 格数上限与点位合法性由 reader.decode 统一处理并给出盲文行列定位；
    # 这里仅约束基本类型。
    text: str = Field(..., description="Unicode 六点盲文（可含盲文空格与换行），不超过 500 格")


class AvoidIn(BaseModel):
    # 原文与行宽由 braille.validate 统一校验（错误带 face 区分正反面），
    # 最小点距由 avoid 校验为 0.1～3.0 毫米、限一位小数；这里仅约束基本类型。
    front: str = Field(..., description="正面原文：ASCII 字母、数字、空格与换行，不超过 500 字符")
    back: str = Field(..., description="反面原文：同正面")
    width: int = Field(..., description="共同行宽：每行 10～40 格")
    min_distance: float = Field(..., description="最小点距 0.1～3.0 毫米，限一位小数")


class InspectIn(BaseModel):
    # 原文（不超过 100 字符）与行宽由 braille.validate 统一校验（field="text"），
    # 实测点逐行格式与行数上限由 inspect 校验（错误带行、列定位，field="points"）；
    # 这里仅约束基本类型。
    text: str = Field(..., description="原文：ASCII 字母、数字、空格与换行，不超过 100 字符")
    width: int = Field(..., description="每行 10～40 格")
    points: str = Field(..., description="实测凸点：0～400 行，每行 “x,y”（毫米，限一位小数）")


class EmbossIn(BaseModel):
    # 原文与行宽完全复用 braille.validate / typeset 的校验与排版口径；
    # 这里仅约束基本类型。
    text: str = Field(..., description="ASCII 字母、数字、空格与换行，不超过 500 字符")
    width: int = Field(..., description="每行 10～40 格")


@app.exception_handler(RequestValidationError)
async def _on_validation_error(_request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        errors.append({
            "code": "bad_request",
            "field": loc,
            "message": f"参数 {loc or '请求体'} 格式有误：{err.get('msg', '')}",
        })
    return JSONResponse(status_code=422, content={"ok": False, "errors": errors})


@app.post("/api/typeset")
def api_typeset(payload: TypesetIn):
    try:
        result = typeset(payload.text, payload.width)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "errors": exc.errors})
    result["ok"] = True
    return result


@app.post("/api/decode")
def api_decode(payload: DecodeIn):
    try:
        result = decode(payload.text)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "errors": exc.errors})
    result["ok"] = True
    return result


@app.post("/api/avoid")
def api_avoid(payload: AvoidIn):
    try:
        result = avoid(payload.front, payload.back, payload.width, payload.min_distance)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "errors": exc.errors})
    result["ok"] = True
    return result


@app.post("/api/inspect")
def api_inspect(payload: InspectIn):
    try:
        result = inspect(payload.text, payload.width, payload.points)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "errors": exc.errors})
    result["ok"] = True
    return result


@app.post("/api/emboss-path")
def api_emboss_path(payload: EmbossIn):
    try:
        result = emboss_path(payload.text, payload.width)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "errors": exc.errors})
    result["ok"] = True
    return result


@app.get("/api/health")
def health():
    return {"ok": True}


app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def index():
    return FileResponse("app/static/index.html")
