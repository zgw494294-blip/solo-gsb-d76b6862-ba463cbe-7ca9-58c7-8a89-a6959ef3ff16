/* 六点盲文排版台 — 前端逻辑（原生 JS，无外部依赖，可离线） */
"use strict";

const $ = (sel) => document.querySelector(sel);

/* ---------------- 视图切换 ---------------- */

const VIEW_IDS = ["typeset", "decode", "avoid", "inspect", "emboss"];

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => {
      b.classList.toggle("active", b === btn);
    });
    VIEW_IDS.forEach((v) => {
      $("#view-" + v).hidden = v !== btn.dataset.view;
    });
  });
});

/* ---------------- 共用：错误展示与复制 ---------------- */

function showErrors(box, panel, input, errors) {
  panel.hidden = true;
  box.innerHTML = "";
  const h = document.createElement("h3");
  h.textContent = `发现 ${errors.length} 处问题，请修正后重试：`;
  box.appendChild(h);
  const ul = document.createElement("ul");
  for (const err of errors) {
    const li = document.createElement("li");
    li.textContent = err.message;
    if (typeof err.pos === "number") {
      li.title = "点击定位到输入位置";
      li.addEventListener("click", () => {
        input.focus();
        input.setSelectionRange(err.pos, err.pos + (err.length || 1));
      });
    }
    ul.appendChild(li);
  }
  box.appendChild(ul);
  box.hidden = false;
}

async function copyText(btn, text) {
  try {
    await navigator.clipboard.writeText(text);
    const old = btn.textContent;
    btn.textContent = "已复制 ✓";
    setTimeout(() => (btn.textContent = old), 1500);
  } catch (e) {
    // 退化方案
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

/* ---------------- 盲文排版视图 ---------------- */

const els = {
  input: $("#srcInput"),
  width: $("#widthInput"),
  count: $("#charCount"),
  btn: $("#btnTypeset"),
  btnSample: $("#btnSample"),
  btnClear: $("#btnClear"),
  errors: $("#errorBox"),
  panel: $("#resultPanel"),
  lines: $("#linesContainer"),
  stats: $("#statsBar"),
  download: $("#btnDownload"),
  copy: $("#btnCopy"),
};

let lastResult = null;

/* ---------------- 计数与校验 ---------------- */

function updateCount() {
  const n = els.input.value.length;
  els.count.textContent = String(n);
  els.count.parentElement.classList.toggle("over", n > 500);
}

els.input.addEventListener("input", updateCount);

/* ---------------- 发起排版 ---------------- */

async function doTypeset() {
  const text = els.input.value;
  const width = Number(els.width.value);

  // 前端即时校验（最终以服务端为准）
  const local = [];
  if (!/^[\x20\nA-Za-z0-9]*$/.test(text)) {
    local.push("含非法字符：仅允许 ASCII 字母、数字、空格与换行。");
  }
  if (text.length > 500) local.push("输入超过 500 个字符。");
  if (!/[A-Za-z0-9]/.test(text)) local.push("至少需要包含一个字母或数字。");
  if (!Number.isInteger(width) || width < 10 || width > 40) {
    local.push("每行格数须为 10～40 的整数。");
  }
  if (local.length) {
    showErrors(els.errors, els.panel, els.input, [{ message: local.join("\n") }]);
    return;
  }

  els.btn.disabled = true;
  try {
    const resp = await fetch("/api/typeset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, width }),
    });
    const data = await resp.json();
    if (!resp.ok || data.ok === false) {
      showErrors(els.errors, els.panel, els.input,
        data.errors || [{ message: "排版失败。" }]);
      return;
    }
    els.errors.hidden = true;
    renderResult(data);
  } catch (e) {
    showErrors(els.errors, els.panel, els.input, [{ message: "请求失败：" + e }]);
  } finally {
    els.btn.disabled = false;
  }
}

/* ---------------- 渲染盲文格 ---------------- */

// 点号 1..6 对应网格位置（左列 1/2/3，右列 4/5/6）
const DOT_ORDER = [1, 4, 2, 5, 3, 6];

function makeCell(cell) {
  const d = document.createElement("div");
  d.className = "cell " + cell.kind;

  const grid = document.createElement("div");
  grid.className = "dotgrid";
  const on = new Set(cell.dots);
  for (const dot of DOT_ORDER) {
    const s = document.createElement("span");
    s.className = "dot" + (on.has(dot) ? " on" : "");
    grid.appendChild(s);
  }
  d.appendChild(grid);

  if (cell.kind !== "space") {
    const u = document.createElement("span");
    u.className = "uni";
    u.textContent = cell.text;
    d.appendChild(u);
  }

  d.title = cell.note;
  return d;
}

function renderSourceLine(source) {
  // 原文行：空格淡化，行尾断词连字符高亮
  const div = document.createElement("div");
  div.className = "src-line";
  for (const ch of source) {
    const span = document.createElement("span");
    if (ch === " ") {
      span.className = "src-gap";
      span.textContent = "·";
    } else if (ch === "-") {
      span.className = "src-hyphen";
      span.textContent = "-";
    } else {
      span.textContent = ch;
    }
    div.appendChild(span);
  }
  return div;
}

function renderResult(r) {
  lastResult = r;
  els.panel.hidden = false;
  els.lines.innerHTML = "";
  els.stats.innerHTML = "";

  // 统计
  const stats = [
    `行宽：<b>${r.width}</b> 格`,
    `硬分段：<b>${r.paragraphs}</b> 段`,
    `共 <b>${r.total_lines}</b> 行`,
    `超宽词断词：<b>${r.breaks}</b> 次`,
    `数字续行重加标记：<b>${r.number_reopened}</b> 次`,
  ];
  els.stats.innerHTML = stats.map((s) => `<span>${s}</span>`).join("");

  for (const line of r.lines) {
    const row = document.createElement("div");
    row.className = "line-row";

    const no = document.createElement("div");
    no.className = "line-no";
    no.textContent = line.blank ? "" : String(line.index);

    const body = document.createElement("div");
    body.className = "line-body" + (line.blank ? " blank" : "");

    if (line.blank) {
      body.appendChild(document.createTextNode("（空段）"));
    } else {
      body.appendChild(renderSourceLine(line.source));

      const cells = document.createElement("div");
      cells.className = "cells";
      for (const c of line.cells) cells.appendChild(makeCell(c));
      body.appendChild(cells);

      const rem = document.createElement("div");
      rem.className = "remain";
      const pct = Math.round((line.used / r.width) * 100);
      rem.innerHTML =
        `用 ${line.used} 格 · 余 ${line.remain} 格` +
        `<span class="rail"><span class="fill" style="width:${pct}%"></span></span>`;
      body.appendChild(rem);
    }

    row.appendChild(no);
    row.appendChild(body);
    els.lines.appendChild(row);
  }

  els.panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------------- 下载与复制 ---------------- */

function downloadBraille() {
  if (!lastResult) return;
  // 加 BOM，保证 Windows 记事本等工具正确识别 UTF-8
  const blob = new Blob(["﻿" + lastResult.braille_text], {
    type: "text/plain;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "braille.txt";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

els.btn.addEventListener("click", doTypeset);
els.download.addEventListener("click", downloadBraille);
els.copy.addEventListener("click", () => {
  if (lastResult) copyText(els.copy, lastResult.braille_text);
});

els.btnClear.addEventListener("click", () => {
  els.input.value = "";
  updateCount();
  els.errors.hidden = true;
  els.panel.hidden = true;
  els.input.focus();
});

els.btnSample.addEventListener("click", () => {
  els.input.value =
`Hello Braille
The quick brown fox
2026 007`;
  els.width.value = 16;
  updateCount();
  doTypeset();
});

els.input.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    doTypeset();
  }
});

updateCount();

/* ---------------- 盲文识读视图 ---------------- */

const dec = {
  input: $("#decInput"),
  count: $("#decCellCount"),
  btn: $("#btnDecode"),
  btnSample: $("#btnDecSample"),
  btnClear: $("#btnDecClear"),
  errors: $("#decErrorBox"),
  panel: $("#decResultPanel"),
  stats: $("#decStatsBar"),
  output: $("#decOutput"),
  copy: $("#btnDecCopy"),
};

let lastDecode = null;

// 计数只算盲文格（U+2800～U+28FF），换行不占格
const countCells = (s) => (s.match(/[\u2800-\u28FF]/g) || []).length;
function updateDecCount() {
  const n = countCells(dec.input.value);
  dec.count.textContent = String(n);
  dec.count.parentElement.classList.toggle("over", n > 500);
}

dec.input.addEventListener("input", updateDecCount);

async function doDecode() {
  const text = dec.input.value;

  // 前端即时校验（最终以服务端为准）
  const local = [];
  if (!text) local.push("请输入盲文。");
  if (countCells(text) > 500) local.push("盲文超过 500 格。");
  if (/[^\u2800-\u28FF\n\r]/.test(text)) {
    local.push("含非法字符：仅允许 Unicode 六点盲文、盲文空格（U+2800）与换行。");
  }
  if (local.length) {
    showErrors(dec.errors, dec.panel, dec.input, [{ message: local.join("\n") }]);
    return;
  }

  dec.btn.disabled = true;
  try {
    const resp = await fetch("/api/decode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await resp.json();
    if (!resp.ok || data.ok === false) {
      showErrors(dec.errors, dec.panel, dec.input,
        data.errors || [{ message: "识读失败。" }]);
      return;
    }
    dec.errors.hidden = true;
    renderDecode(data);
  } catch (e) {
    showErrors(dec.errors, dec.panel, dec.input, [{ message: "请求失败：" + e }]);
  } finally {
    dec.btn.disabled = false;
  }
}

function renderDecode(r) {
  lastDecode = r;
  dec.panel.hidden = false;
  dec.stats.innerHTML = [
    `盲文 <b>${r.cells}</b> 格`,
    `结果 <b>${r.chars}</b> 字符`,
    `共 <b>${r.lines}</b> 行`,
  ].map((s) => `<span>${s}</span>`).join("");
  dec.output.textContent = r.text;
  dec.panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

dec.btn.addEventListener("click", doDecode);
dec.copy.addEventListener("click", () => {
  if (lastDecode) copyText(dec.copy, lastDecode.text);
});

dec.btnClear.addEventListener("click", () => {
  dec.input.value = "";
  updateDecCount();
  dec.errors.hidden = true;
  dec.panel.hidden = true;
  dec.input.focus();
});

dec.btnSample.addEventListener("click", () => {
  dec.input.value =
`⠠⠓⠑⠇⠇⠕⠀⠠⠃⠗⠁⠊⠇⠇⠑
⠼⠃⠚⠃⠋⠀⠁⠃⠉⠙⠑⠤
⠋⠛⠓`;
  updateDecCount();
  doDecode();
});

dec.input.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    doDecode();
  }
});

updateDecCount();

/* ---------------- 双面避让视图 ---------------- */

const avo = {
  front: $("#avoFront"),
  back: $("#avoBack"),
  frontCount: $("#avoFrontCount"),
  backCount: $("#avoBackCount"),
  width: $("#avoWidth"),
  dist: $("#avoDist"),
  btn: $("#btnAvoid"),
  btnSample: $("#btnAvoSample"),
  btnClear: $("#btnAvoClear"),
  errors: $("#avoErrorBox"),
  panel: $("#avoResultPanel"),
  verdict: $("#avoVerdict"),
  stats: $("#avoStats"),
  overlay: $("#avoOverlay"),
  confCount: $("#avoConfCount"),
  conflicts: $("#avoConflicts"),
  copy: $("#btnAvoCopy"),
};

let lastAvoid = null;

function updateAvoCounts() {
  const nf = avo.front.value.length;
  const nb = avo.back.value.length;
  avo.frontCount.textContent = String(nf);
  avo.backCount.textContent = String(nb);
  avo.frontCount.parentElement.classList.toggle("over", nf > 500);
  avo.backCount.parentElement.classList.toggle("over", nb > 500);
}

avo.front.addEventListener("input", updateAvoCounts);
avo.back.addEventListener("input", updateAvoCounts);

/* 错误展示：face 字段区分正反面，点击定位到对应输入框 */
function showAvoErrors(errors) {
  avo.panel.hidden = true;
  avo.errors.innerHTML = "";
  const h = document.createElement("h3");
  h.textContent = `发现 ${errors.length} 处问题，请修正后重试：`;
  avo.errors.appendChild(h);
  const ul = document.createElement("ul");
  for (const err of errors) {
    const li = document.createElement("li");
    const tag = err.face === "front" ? "【正面】" : err.face === "back" ? "【反面】" : "";
    li.textContent = tag + err.message;
    if (typeof err.pos === "number" && err.face) {
      li.title = "点击定位到输入位置";
      li.addEventListener("click", () => {
        const input = err.face === "front" ? avo.front : avo.back;
        input.focus();
        input.setSelectionRange(err.pos, err.pos + (err.length || 1));
      });
    }
    ul.appendChild(li);
  }
  avo.errors.appendChild(ul);
  avo.errors.hidden = false;
}

async function doAvoid() {
  const front = avo.front.value;
  const back = avo.back.value;
  const width = Number(avo.width.value);
  const dist = Number(avo.dist.value);

  // 前端即时校验（最终以服务端为准）
  const local = [];
  for (const [name, text] of [["正面", front], ["反面", back]]) {
    if (!/^[\x20\nA-Za-z0-9]*$/.test(text)) {
      local.push(`${name}含非法字符：仅允许 ASCII 字母、数字、空格与换行。`);
    }
    if (text.length > 500) local.push(`${name}超过 500 个字符。`);
    if (!/[A-Za-z0-9]/.test(text)) local.push(`${name}至少需要包含一个字母或数字。`);
  }
  if (!Number.isInteger(width) || width < 10 || width > 40) {
    local.push("共同行宽须为 10～40 的整数。");
  }
  if (
    !Number.isFinite(dist) || dist < 0.1 || dist > 3 ||
    Math.abs(dist * 10 - Math.round(dist * 10)) > 1e-9
  ) {
    local.push("最小点距须为 0.1～3.0 毫米、限一位小数。");
  }
  if (local.length) {
    showAvoErrors([{ message: local.join("\n") }]);
    return;
  }

  avo.btn.disabled = true;
  try {
    const resp = await fetch("/api/avoid", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ front, back, width, min_distance: dist }),
    });
    const data = await resp.json();
    if (!resp.ok || data.ok === false) {
      showAvoErrors(data.errors || [{ message: "避让计算失败。" }]);
      return;
    }
    avo.errors.hidden = true;
    renderAvoid(data);
  } catch (e) {
    showAvoErrors([{ message: "请求失败：" + e }]);
  } finally {
    avo.btn.disabled = false;
  }
}

/* ---------------- 叠加图与结果渲染 ---------------- */

const MM = 9;      // 叠加图比例：每毫米像素
const DOT_R = 0.8; // 点半径（毫米）
const SVGNS = "http://www.w3.org/2000/svg";
const CONF_LIST_MAX = 200; // 冲突列表最多直接列出的条数（叠加图始终全量标出）

function fmtShift(v) {
  return (v >= 0 ? "+" : "") + v.toFixed(1) + "mm";
}

// 点号 -> 格内偏移（毫米）：点 1～3 在左列，点 4～6 在右列
function dotOffset(d) {
  return d <= 3 ? [0, 2.5 * (d - 1)] : [2.5, 2.5 * (d - 4)];
}

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVGNS, tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

// 提取一面全部凸点在正面坐标系中的位置："行,格,点" -> [x, y]（毫米）
// shift 为 null 表示正面原坐标；否则为 {mirror, dx, dy}，反面先镜像再加位移
function collectPoints(side, shift) {
  const pts = new Map();
  side.lines.forEach((line, r) => {
    line.cells.forEach((cell, c) => {
      for (const d of cell.dots) {
        const [ox, oy] = dotOffset(d);
        let x = 6 * c + ox;
        let y = 10 * r + oy;
        if (shift) {
          x = shift.mirror - x + shift.dx;
          y += shift.dy;
        }
        pts.set(`${r},${c},${d}`, [x, y]);
      }
    });
  });
  return pts;
}

const keyOf = (end) => `${end.row},${end.cell},${end.dot}`;

function renderOverlay(r) {
  const rows = Math.max(r.front.lines.length, r.back.lines.length, 1);
  const spanX = 6 * (r.width - 1) + 2.5;   // 点阵横向跨度（毫米）
  const spanY = (rows - 1) * 10 + 5;       // 点阵纵向跨度（毫米）
  const pad = 4;                           // 留白，容纳 ±3mm 位移
  const X = (v) => (v + pad) * MM;
  const Y = (v) => (v + pad) * MM;

  const svg = avo.overlay;
  svg.innerHTML = "";
  svg.setAttribute("width", (spanX + 2 * pad) * MM);
  svg.setAttribute("height", (spanY + 2 * pad) * MM);

  // 行格参考线（每格 6×10 毫米）
  const grid = svgEl("g", { class: "ov-grid" });
  for (let rr = 0; rr < rows; rr++) {
    for (let c = 0; c < r.width; c++) {
      grid.appendChild(svgEl("rect", {
        x: X(6 * c - 1.75), y: Y(10 * rr - 2.5),
        width: 6 * MM, height: 10 * MM,
      }));
    }
  }
  svg.appendChild(grid);

  const frontPts = collectPoints(r.front, null);
  const backPts = collectPoints(r.back, {
    mirror: 6 * (r.width - 1) + 2.5, dx: r.dx, dy: r.dy,
  });

  // 冲突连线（画在点的下层）
  const links = svgEl("g", { class: "ov-links" });
  const confFront = new Set();
  const confBack = new Set();
  for (const cf of r.conflicts) {
    confFront.add(keyOf(cf.front));
    confBack.add(keyOf(cf.back));
    const p1 = frontPts.get(keyOf(cf.front));
    const p2 = backPts.get(keyOf(cf.back));
    if (!p1 || !p2) continue;
    links.appendChild(svgEl("line", {
      x1: X(p1[0]), y1: Y(p1[1]), x2: X(p2[0]), y2: Y(p2[1]),
    }));
  }
  svg.appendChild(links);

  const dots = svgEl("g", { class: "ov-dots" });
  for (const [key, [x, y]] of frontPts) {
    dots.appendChild(svgEl("circle", {
      class: "ov-front" + (confFront.has(key) ? " conf" : ""),
      cx: X(x), cy: Y(y), r: DOT_R * MM,
    }));
  }
  for (const [key, [x, y]] of backPts) {
    dots.appendChild(svgEl("circle", {
      class: "ov-back" + (confBack.has(key) ? " conf" : ""),
      cx: X(x), cy: Y(y), r: DOT_R * MM,
    }));
  }
  svg.appendChild(dots);
}

function renderConflicts(r) {
  avo.confCount.textContent = String(r.conflict_count);
  avo.conflicts.innerHTML = "";
  if (r.conflict_count === 0) {
    const div = document.createElement("div");
    div.className = "conf-empty";
    div.textContent = "零冲突：该位移下两面凸点互不干扰，可行。";
    avo.conflicts.appendChild(div);
    return;
  }
  const fmtEnd = (e) =>
    `${e.face === "front" ? "正面" : "反面"} 行${e.row}·格${e.cell}·点${e.dot}`;
  const shown = r.conflicts.slice(0, CONF_LIST_MAX);
  for (const cf of shown) {
    const div = document.createElement("div");
    div.className = "conf-item";
    div.textContent = `${fmtEnd(cf.front)} ↔ ${fmtEnd(cf.back)}`;
    avo.conflicts.appendChild(div);
  }
  if (r.conflict_count > shown.length) {
    const more = document.createElement("div");
    more.className = "conf-more";
    more.textContent = `…其余 ${r.conflict_count - shown.length} 对从略（叠加图中已全部标出）。`;
    avo.conflicts.appendChild(more);
  }
}

function renderAvoid(r) {
  lastAvoid = r;
  avo.panel.hidden = false;

  avo.verdict.className = "verdict " + (r.feasible ? "ok" : "bad");
  avo.verdict.textContent = r.feasible
    ? `✓ 可行：位移 dx=${fmtShift(r.dx)}、dy=${fmtShift(r.dy)} 下零冲突。`
    : `✗ 仍有冲突：最优位移 dx=${fmtShift(r.dx)}、dy=${fmtShift(r.dy)} 下仍有 ${r.conflict_count} 对冲突。`;

  avo.stats.innerHTML = [
    `行宽：<b>${r.width}</b> 格`,
    `最小点距：<b>${r.min_distance.toFixed(1)}</b> 毫米`,
    `正面凸点：<b>${r.front_dots}</b> 个`,
    `反面凸点：<b>${r.back_dots}</b> 个`,
    `最佳位移：<b>dx=${fmtShift(r.dx)}，dy=${fmtShift(r.dy)}</b>`,
    `冲突点对：<b>${r.conflict_count}</b>`,
  ].map((s) => `<span>${s}</span>`).join("");

  renderOverlay(r);
  renderConflicts(r);
  avo.panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

avo.btn.addEventListener("click", doAvoid);

avo.copy.addEventListener("click", () => {
  if (!lastAvoid) return;
  const r = lastAvoid;
  const head = r.feasible ? "双面避让结果：可行（零冲突）。" : `双面避让结果：仍有 ${r.conflict_count} 对冲突。`;
  copyText(avo.copy, head +
    `行宽 ${r.width} 格，最小点距 ${r.min_distance.toFixed(1)}mm，` +
    `最佳位移 dx=${fmtShift(r.dx)}、dy=${fmtShift(r.dy)}。`);
});

avo.btnClear.addEventListener("click", () => {
  avo.front.value = "";
  avo.back.value = "";
  updateAvoCounts();
  avo.errors.hidden = true;
  avo.panel.hidden = true;
  avo.front.focus();
});

avo.btnSample.addEventListener("click", () => {
  avo.front.value =
`Hello Braille
The quick brown fox`;
  avo.back.value =
`pack my box with
five dozen liquor jugs
2026 007`;
  avo.width.value = 20;
  avo.dist.value = "1.0";
  updateAvoCounts();
  doAvoid();
});

for (const input of [avo.front, avo.back]) {
  input.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      doAvoid();
    }
  });
}

updateAvoCounts();

/* ---------------- 压印复核视图 ---------------- */

const ins = {
  text: $("#insText"),
  points: $("#insPoints"),
  textCount: $("#insTextCount"),
  pointCount: $("#insPointCount"),
  width: $("#insWidth"),
  btn: $("#btnInspect"),
  btnSample: $("#btnInsSample"),
  btnClear: $("#btnInsClear"),
  errors: $("#insErrorBox"),
  panel: $("#insResultPanel"),
  verdict: $("#insVerdict"),
  stats: $("#insStats"),
  overlay: $("#insOverlay"),
  missCount: $("#insMissCount"),
  extraCount: $("#insExtraCount"),
  missing: $("#insMissing"),
  extra: $("#insExtra"),
  copy: $("#btnInsCopy"),
};

let lastInspect = null;

// 每行恰好一对 x,y：可选符号、整数或一位小数（与服务端正则一致）
const POINT_LINE_RE = /^[+-]?(\d+(\.\d)?|\.\d),[+-]?(\d+(\.\d)?|\.\d)$/;

// 结尾单个换行不产生空尾行（与服务端 POSIX 惯例一致），据此计数与分行
const pointLinesOf = (v) => (v === "" ? [] : v.replace(/\n$/, "").split("\n"));

function updateInsCounts() {
  ins.textCount.textContent = String(ins.text.value.length);
  ins.textCount.parentElement.classList.toggle("over", ins.text.value.length > 100);
  const n = pointLinesOf(ins.points.value).length;
  ins.pointCount.textContent = String(n);
  ins.pointCount.parentElement.classList.toggle("over", n > 400);
}

ins.text.addEventListener("input", updateInsCounts);
ins.points.addEventListener("input", updateInsCounts);

/* 错误展示：field 区分原文（text）与实测点（points），点击定位到对应输入框 */
function showInsErrors(errors) {
  ins.panel.hidden = true;
  ins.errors.innerHTML = "";
  const h = document.createElement("h3");
  h.textContent = `发现 ${errors.length} 处问题，请修正后重试：`;
  ins.errors.appendChild(h);
  const ul = document.createElement("ul");
  for (const err of errors) {
    const li = document.createElement("li");
    const tag = err.field === "points" ? "【实测点】" : err.field === "text" ? "【原文】" : "";
    li.textContent = tag + err.message;
    if (typeof err.pos === "number" && err.field) {
      li.title = "点击定位到输入位置";
      li.addEventListener("click", () => {
        const input = err.field === "points" ? ins.points : ins.text;
        input.focus();
        input.setSelectionRange(err.pos, err.pos + (err.length || 1));
      });
    }
    ul.appendChild(li);
  }
  ins.errors.appendChild(ul);
  ins.errors.hidden = false;
}

async function doInspect() {
  const text = ins.text.value;
  const width = Number(ins.width.value);
  const points = ins.points.value;

  // 前端即时校验（最终以服务端为准）
  const local = [];
  if (!/^[\x20\nA-Za-z0-9]*$/.test(text)) {
    local.push("【原文】含非法字符：仅允许 ASCII 字母、数字、空格与换行。");
  }
  if (text.length > 100) local.push("【原文】超过 100 个字符。");
  if (!/[A-Za-z0-9]/.test(text)) local.push("【原文】至少需要包含一个字母或数字。");
  if (!Number.isInteger(width) || width < 10 || width > 40) {
    local.push("每行格数须为 10～40 的整数。");
  }
  const lines = pointLinesOf(points);
  if (lines.length > 400) local.push("【实测点】超过 400 行。");
  lines.forEach((line, i) => {
    if (!POINT_LINE_RE.test(line)) {
      local.push(`【实测点】第 ${i + 1} 行 “${line.slice(0, 20)}” 格式有误：` +
        `每行须为一对 x,y（毫米，限一位小数），例如 “12.3,4.5”。`);
    }
  });
  if (local.length) {
    showInsErrors([{ message: local.join("\n") }]);
    return;
  }

  ins.btn.disabled = true;
  try {
    const resp = await fetch("/api/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, width, points }),
    });
    const data = await resp.json();
    if (!resp.ok || data.ok === false) {
      showInsErrors(data.errors || [{ message: "复核失败。" }]);
      return;
    }
    ins.errors.hidden = true;
    renderInspect(data);
  } catch (e) {
    showInsErrors([{ message: "请求失败：" + e }]);
  } finally {
    ins.btn.disabled = false;
  }
}

/* ---------------- 复核叠加图与结果渲染 ---------------- */

const INS_DOT_R = 0.75; // 点半径（毫米）

function diamond(x, y, r) {
  return `M ${x},${y - r} L ${x + r},${y} L ${x},${y + r} L ${x - r},${y} Z`;
}

function withTitle(node, text) {
  const t = svgEl("title", {});
  t.textContent = text;
  node.appendChild(t);
  return node;
}

function renderInsOverlay(r) {
  const rows = Math.max(r.layout.lines.length, 1);
  const spanX = 6 * (r.width - 1) + 2.5;   // 理论点阵横向跨度（毫米）
  const spanY = (rows - 1) * 10 + 5;       // 理论点阵纵向跨度（毫米）

  // 理论点阵参考范围（含格框留白），再并入全部位移后实测点（含远离版面的多余点）
  let minX = -1.75, minY = -2.5, maxX = spanX + 1.75, maxY = spanY + 2.5;
  for (const p of r.points) {
    const x = p.x + r.dx;
    const y = p.y + r.dy;
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  const pad = 4;
  const X = (v) => (v - minX + pad) * MM;
  const Y = (v) => (v - minY + pad) * MM;

  const svg = ins.overlay;
  svg.innerHTML = "";
  svg.setAttribute("width", (maxX - minX + 2 * pad) * MM);
  svg.setAttribute("height", (maxY - minY + 2 * pad) * MM);

  // 行格参考线（每格 6×10 毫米）
  const grid = svgEl("g", { class: "ov-grid" });
  for (let rr = 0; rr < rows; rr++) {
    for (let c = 0; c < r.width; c++) {
      grid.appendChild(svgEl("rect", {
        x: X(6 * c - 1.75), y: Y(10 * rr - 2.5),
        width: 6 * MM, height: 10 * MM,
      }));
    }
  }
  svg.appendChild(grid);

  const theoryPts = collectPoints(r.layout, null);
  const measuredPts = new Map(
    r.points.map((p) => [p.line, [p.x + r.dx, p.y + r.dy]]),
  );
  const missingSet = new Set(r.missing_dots.map(keyOf));
  const extraLines = new Set(r.extra_points.map((p) => p.line));

  // 配对连线（画在点的下层）
  const links = svgEl("g", { class: "ins-links" });
  for (const m of r.matches) {
    const p1 = theoryPts.get(keyOf(m));
    const p2 = measuredPts.get(m.line);
    if (!p1 || !p2) continue;
    links.appendChild(withTitle(
      svgEl("line", { x1: X(p1[0]), y1: Y(p1[1]), x2: X(p2[0]), y2: Y(p2[1]) }),
      `第 ${m.line} 行实测点 ↔ 行${m.row}·格${m.cell}·点${m.dot}，间距 ${m.distance.toFixed(2)} 毫米`,
    ));
  }
  svg.appendChild(links);

  const dots = svgEl("g", { class: "ins-dots" });

  // 理论凸点：缺失的描红圈，正常实心
  for (const [key, [x, y]] of theoryPts) {
    const [rr, c, d] = key.split(",").map(Number);
    const miss = missingSet.has(key);
    dots.appendChild(withTitle(
      svgEl("circle", {
        class: "ins-theory" + (miss ? " miss" : ""),
        cx: X(x), cy: Y(y),
        r: (miss ? INS_DOT_R + 0.35 : INS_DOT_R) * MM,
      }),
      miss ? `缺失理论点：行${rr}·格${c}·点${d}`
           : `理论点：行${rr}·格${c}·点${d}`,
    ));
  }

  // 实测点：多余的画红菱形，已配对画蓝点
  for (const p of r.points) {
    const [x, y] = measuredPts.get(p.line);
    if (extraLines.has(p.line)) {
      dots.appendChild(withTitle(
        svgEl("path", {
          class: "ins-extra",
          d: diamond(X(x), Y(y), (INS_DOT_R + 0.35) * MM),
        }),
        `多余实测点：第 ${p.line} 行（${p.x}, ${p.y}）`,
      ));
    } else {
      dots.appendChild(withTitle(
        svgEl("circle", {
          class: "ins-measured",
          cx: X(x), cy: Y(y), r: INS_DOT_R * MM,
        }),
        `实测点第 ${p.line} 行（${p.x}, ${p.y}）`,
      ));
    }
  }
  svg.appendChild(dots);
}

function renderInsAnomalies(r) {
  ins.missCount.textContent = String(r.missing);
  ins.missing.innerHTML = "";
  if (r.missing === 0) {
    const div = document.createElement("div");
    div.className = "conf-empty";
    div.textContent = "无缺失：理论凸点全部配对。";
    ins.missing.appendChild(div);
  } else {
    const shown = r.missing_dots.slice(0, CONF_LIST_MAX);
    for (const d of shown) {
      const div = document.createElement("div");
      div.className = "conf-item";
      div.textContent = `行${d.row}·格${d.cell}·点${d.dot}`;
      ins.missing.appendChild(div);
    }
    if (r.missing_dots.length > shown.length) {
      const more = document.createElement("div");
      more.className = "conf-more";
      more.textContent = `…其余 ${r.missing_dots.length - shown.length} 个从略（叠加图中已全部标出）。`;
      ins.missing.appendChild(more);
    }
  }

  ins.extraCount.textContent = String(r.extra);
  ins.extra.innerHTML = "";
  if (r.extra === 0) {
    const div = document.createElement("div");
    div.className = "conf-empty";
    div.textContent = "无多余：实测点全部配对。";
    ins.extra.appendChild(div);
  } else {
    const shown = r.extra_points.slice(0, CONF_LIST_MAX);
    for (const p of shown) {
      const div = document.createElement("div");
      div.className = "conf-item";
      div.textContent =
        `第 ${p.line} 行（x=${p.x.toFixed(1)}, y=${p.y.toFixed(1)} 毫米）`;
      div.title = "点击定位到实测点输入行";
      div.addEventListener("click", () => {
        ins.points.focus();
        const allLines = pointLinesOf(ins.points.value);
        const before = allLines.slice(0, p.line - 1)
          .reduce((n, s) => n + s.length + 1, 0);
        const len = allLines[p.line - 1] ? allLines[p.line - 1].length : 1;
        ins.points.setSelectionRange(before, before + len);
      });
      ins.extra.appendChild(div);
    }
    if (r.extra_points.length > shown.length) {
      const more = document.createElement("div");
      more.className = "conf-more";
      more.textContent = `…其余 ${r.extra_points.length - shown.length} 个从略（叠加图中已全部标出）。`;
      ins.extra.appendChild(more);
    }
  }
}

function renderInspect(r) {
  lastInspect = r;
  ins.panel.hidden = false;

  ins.verdict.className = "verdict " + (r.perfect ? "ok" : "bad");
  ins.verdict.textContent = r.perfect
    ? `✓ 复核通过：位移 dx=${fmtShift(r.dx)}、dy=${fmtShift(r.dy)} 下 ${r.theory_dots} 个理论凸点全部配对，无缺失、无多余。`
    : `✗ 存在异常：最优位移 dx=${fmtShift(r.dx)}、dy=${fmtShift(r.dy)} 下缺失 ${r.missing} 个理论点、多余 ${r.extra} 个实测点。`;

  ins.stats.innerHTML = [
    `行宽：<b>${r.width}</b> 格`,
    `理论凸点：<b>${r.theory_dots}</b> 个`,
    `实测点：<b>${r.measured_dots}</b> 个`,
    `已配对：<b>${r.matched}</b> 对`,
    `缺失：<b>${r.missing}</b>`,
    `多余：<b>${r.extra}</b>`,
    `最佳位移：<b>dx=${fmtShift(r.dx)}，dy=${fmtShift(r.dy)}</b>`,
    `距离平方和：<b>${r.sse.toFixed(2)}</b> mm²`,
  ].map((s) => `<span>${s}</span>`).join("");

  renderInsOverlay(r);
  renderInsAnomalies(r);
  ins.panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

ins.btn.addEventListener("click", doInspect);

ins.copy.addEventListener("click", () => {
  if (!lastInspect) return;
  const r = lastInspect;
  const head = r.perfect ? "压印复核结果：通过（无缺失、无多余）。"
    : `压印复核结果：缺失 ${r.missing} 个理论点、多余 ${r.extra} 个实测点。`;
  copyText(ins.copy, head +
    `行宽 ${r.width} 格，理论 ${r.theory_dots} 点、实测 ${r.measured_dots} 点、配对 ${r.matched} 对，` +
    `最佳位移 dx=${fmtShift(r.dx)}、dy=${fmtShift(r.dy)}，距离平方和 ${r.sse.toFixed(2)} mm²。`);
});

ins.btnClear.addEventListener("click", () => {
  ins.text.value = "";
  ins.points.value = "";
  updateInsCounts();
  ins.errors.hidden = true;
  ins.panel.hidden = true;
  ins.text.focus();
});

ins.btnSample.addEventListener("click", () => {
  ins.text.value = "Hello 2026";
  ins.points.value =
`2.7,4.9
6.2,-0.1
6.2,2.4
8.7,2.4
12.2,-0.1
14.7,2.4
18.2,-0.1
18.2,2.4
18.2,4.9
24.2,-0.1
24.2,2.4
24.2,4.9
30.2,-0.1
30.2,4.9
32.7,2.4
42.2,4.9
44.7,-0.1
44.7,2.4
44.7,4.9
48.2,-0.1
48.2,2.4
54.2,2.4
56.7,-0.1
56.7,2.4
60.2,-0.1
60.2,2.4
66.2,-0.1
66.2,2.4
95,5.5`;
  ins.width.value = 16;
  updateInsCounts();
  doInspect();
});

for (const input of [ins.text, ins.points]) {
  input.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      doInspect();
    }
  });
}

updateInsCounts();

/* ---------------- 单针压印路径视图 ---------------- */

const emb = {
  text: $("#embText"),
  width: $("#embWidth"),
  count: $("#embCount"),
  btn: $("#btnEmboss"),
  btnSample: $("#btnEmbSample"),
  btnClear: $("#btnEmbClear"),
  errors: $("#embErrorBox"),
  panel: $("#embResultPanel"),
  verdict: $("#embVerdict"),
  stats: $("#embStats"),
  overlay: $("#embOverlay"),
  dirs: $("#embDirs"),
  commands: $("#embCommands"),
  download: $("#btnEmbDownload"),
  copy: $("#btnEmbCopy"),
};

let lastEmboss = null;
const EMB_LABEL_MAX = 60; // 不超过该点数时在图上标注压印顺序号

function updateEmbCount() {
  const n = emb.text.value.length;
  emb.count.textContent = String(n);
  emb.count.parentElement.classList.toggle("over", n > 500);
}

emb.text.addEventListener("input", updateEmbCount);

async function doEmboss() {
  const text = emb.text.value;
  const width = Number(emb.width.value);

  // 前端即时校验（最终以服务端为准）
  const local = [];
  if (!/^[\x20\nA-Za-z0-9]*$/.test(text)) {
    local.push("含非法字符：仅允许 ASCII 字母、数字、空格与换行。");
  }
  if (text.length > 500) local.push("输入超过 500 个字符。");
  if (!/[A-Za-z0-9]/.test(text)) local.push("至少需要包含一个字母或数字。");
  if (!Number.isInteger(width) || width < 10 || width > 40) {
    local.push("每行格数须为 10～40 的整数。");
  }
  if (local.length) {
    showErrors(emb.errors, emb.panel, emb.text, [{ message: local.join("\n") }]);
    return;
  }

  emb.btn.disabled = true;
  try {
    const resp = await fetch("/api/emboss-path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, width }),
    });
    const data = await resp.json();
    if (!resp.ok || data.ok === false) {
      showErrors(emb.errors, emb.panel, emb.text,
        data.errors || [{ message: "路径规划失败。" }]);
      return;
    }
    emb.errors.hidden = true;
    renderEmboss(data);
  } catch (e) {
    showErrors(emb.errors, emb.panel, emb.text, [{ message: "请求失败：" + e }]);
  } finally {
    emb.btn.disabled = false;
  }
}

/* ---------------- 路径图渲染 ---------------- */

function renderEmbOverlay(r) {
  const rows = Math.max(r.layout.lines.length, 1);
  const spanX = 6 * (r.width - 1) + 2.5;   // 点阵横向跨度（毫米）
  const spanY = (rows - 1) * 10 + 5;       // 点阵纵向跨度（毫米）
  const pad = 4;                           // 留白，容纳原点与路径端
  const X = (v) => (v + pad) * MM;
  const Y = (v) => (v + pad) * MM;

  const svg = emb.overlay;
  svg.innerHTML = `
    <defs>
      <marker id="embArrowSweep" viewBox="0 0 10 10" refX="8" refY="5"
        markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 Z" fill="#8a5a24"></path>
      </marker>
      <marker id="embArrowMove" viewBox="0 0 10 10" refX="8" refY="5"
        markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 Z" fill="#2f6fb2"></path>
      </marker>
    </defs>`;
  svg.setAttribute("width", (spanX + 2 * pad) * MM);
  svg.setAttribute("height", (spanY + 2 * pad) * MM);

  // 行格参考线（每格 6×10 毫米）
  const grid = svgEl("g", { class: "emb-grid" });
  for (let rr = 0; rr < rows; rr++) {
    for (let c = 0; c < r.width; c++) {
      grid.appendChild(svgEl("rect", {
        x: X(6 * c - 1.75), y: Y(10 * rr - 2.5),
        width: 6 * MM, height: 10 * MM,
      }));
    }
  }
  svg.appendChild(grid);

  // 压头轨迹：由扫描线明细重放。每个凸点前都是一次抬针 MOVE（蓝虚线）；
  // 同一扫描线内相邻两个落针点之间的行程为扫描线落针行程（棕实线），
  // 末端的箭头给出实际走行方向；最后从末点抬针 MOVE 回原点。
  const flat = r.scanlines.flatMap((s) => s.points);
  const links = svgEl("g", {});
  let cursor = { x: 0, y: 0 };
  const sweeps = []; // [from, to] 扫描线内行程（毫米）
  const moves = [];  // [from, to] 抬针移动（毫米）
  for (const s of r.scanlines) {
    for (const p of s.points) {
      moves.push([cursor, { x: p.x, y: s.y }]);
      cursor = { x: p.x, y: s.y };
    }
    for (let i = 1; i < s.points.length; i++) {
      sweeps.push([{ x: s.points[i - 1].x, y: s.y }, { x: s.points[i].x, y: s.y }]);
    }
  }
  moves.push([cursor, { x: 0, y: 0 }]);

  for (const [a, b] of moves) {
    links.appendChild(svgEl("line", {
      class: "emb-move",
      x1: X(a.x), y1: Y(a.y), x2: X(b.x), y2: Y(b.y),
      "marker-end": "url(#embArrowMove)",
    }));
  }
  for (const [a, b] of sweeps) {
    links.appendChild(svgEl("line", {
      class: "emb-sweep",
      x1: X(a.x), y1: Y(a.y), x2: X(b.x), y2: Y(b.y),
      "marker-end": "url(#embArrowSweep)",
    }));
  }
  svg.appendChild(links);

  // 理论凸点（附压印顺序）
  const dotsG = svgEl("g", { class: r.punch_count > EMB_LABEL_MAX ? "emb-dim" : "" });
  const labeled = r.punch_count <= EMB_LABEL_MAX;
  for (const p of flat) {
    const g = svgEl("g", {});
    g.appendChild(withTitle(
      svgEl("circle", { class: "emb-dot", cx: X(p.x), cy: Y(p.y), r: DOT_R * MM }),
      `第 ${p.order} 针：行${p.row}·格${p.cell}·点${p.dot}（${p.x.toFixed(1)}, ${p.y.toFixed(1)} 毫米）`,
    ));
    if (labeled) {
      const t = svgEl("text", { x: X(p.x), y: Y(p.y), class: "emb-order" });
      t.textContent = String(p.order);
      g.appendChild(t);
    }
    dotsG.appendChild(g);
  }
  svg.appendChild(dotsG);

  // 原点
  svg.appendChild(withTitle(
    svgEl("circle", { class: "emb-origin", cx: X(0), cy: Y(0), r: 1.1 * MM }),
    "压头原点 (0,0)",
  ));
}

function renderEmboss(r) {
  lastEmboss = r;
  emb.panel.hidden = false;

  emb.verdict.textContent =
    `✓ 路径规划完成：${r.scanline_count} 条扫描线、${r.punch_count} 针，` +
    `方向序列 [${r.directions.join(",")}]，总移动距离 ${r.total_distance.toFixed(1)} 毫米。`;

  emb.stats.innerHTML = [
    `行宽：<b>${r.width}</b> 格`,
    `凸点（压针次数）：<b>${r.punch_count}</b>`,
    `扫描线：<b>${r.scanline_count}</b> 条`,
    `方向序列：<b>[${r.directions.join(",")}]</b>（0 递增 / 1 递减）`,
    `总移动距离：<b>${r.total_distance.toFixed(1)}</b> 毫米（曼哈顿）`,
  ].map((s) => `<span>${s}</span>`).join("");

  emb.dirs.innerHTML = "";
  r.scanlines.forEach((s, i) => {
    const span = document.createElement("span");
    span.className = "emb-dir d" + s.direction;
    span.textContent = String(r.directions[i]);
    span.title =
      `第 ${i + 1} 条扫描线：y=${s.y.toFixed(1)} 毫米，` +
      `${s.direction === 0 ? "x 递增" : "x 递减"}，${s.points.length} 针`;
    emb.dirs.appendChild(span);
  });

  emb.commands.textContent = r.command_text;

  renderEmbOverlay(r);
  emb.panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------------- 下载与复制 ---------------- */

function downloadEmboss() {
  if (!lastEmboss) return;
  // 指令仅含 ASCII（UP / MOVE x,y / PUNCH），无需 BOM
  const blob = new Blob([lastEmboss.command_text + "\n"], {
    type: "text/plain;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "emboss-path.txt";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

emb.btn.addEventListener("click", doEmboss);
emb.download.addEventListener("click", downloadEmboss);
emb.copy.addEventListener("click", () => {
  if (lastEmboss) copyText(emb.copy, lastEmboss.command_text);
});

emb.btnClear.addEventListener("click", () => {
  emb.text.value = "";
  updateEmbCount();
  emb.errors.hidden = true;
  emb.panel.hidden = true;
  emb.text.focus();
});

emb.btnSample.addEventListener("click", () => {
  emb.text.value =
`Hello Braille
2026`;
  emb.width.value = 16;
  updateEmbCount();
  doEmboss();
});

emb.text.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    doEmboss();
  }
});

updateEmbCount();
