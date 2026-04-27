import { esc, jesc } from "./shared.js";

const p2DupSel = {};
const p2DupFixed = {};
const KEEP_ALL = "__all__";
let _resolveEx;

export function initDup(fns) { _resolveEx = fns.resolveEx; }

function dedupeWithSources(stockpileLocs, scanLocs) {
  const order = [];
  const sources = {};
  const add = (loc, src) => { if (!loc) return; if (!(loc in sources)) { order.push(loc); sources[loc] = new Set(); } sources[loc].add(src); };
  (stockpileLocs || []).forEach((loc) => add(loc, "stockpile"));
  (scanLocs || []).forEach((loc) => add(loc, "scan"));
  return { uniques: order, sources };
}

function badgeFor(sourceSet) {
  if (sourceSet.has("stockpile") && sourceSet.has("scan")) return '<span style="background:#4338ca;color:#fff;padding:1px 6px;border-radius:3px;font-size:11px;margin-left:4px">两者</span>';
  if (sourceSet.has("stockpile")) return '<span style="background:#6b7280;color:#fff;padding:1px 6px;border-radius:3px;font-size:11px;margin-left:4px">原库位</span>';
  return '<span style="background:#059669;color:#fff;padding:1px 6px;border-radius:3px;font-size:11px;margin-left:4px">扫描</span>';
}

function effectiveSingle(side) {
  if (side.scanLocs.length) return side.scanLocs[0];
  if (side.stockpileLocs.length) return side.stockpileLocs[0];
  return null;
}

function composeDupParts(fixed, sel) {
  const parts = [];
  const pick = (side, chosen) => {
    if (!side) return [];
    if (chosen && chosen.size) return side.uniques.filter((l) => chosen.has(l));
    const single = effectiveSingle(side);
    return single ? [single] : [];
  };
  parts.push(...pick(fixed.store, sel.store));
  parts.push(...pick(fixed.warehouse, sel.warehouse));
  return parts.join("/");
}

function dupSideSettled(side, chosen) { return !side || side.uniques.length <= 1 || (chosen && chosen.size > 0); }

function dupTryResolve(barcode) {
  const fixed = p2DupFixed[barcode] || {};
  const sel = p2DupSel[barcode] || {};
  const storeDone = dupSideSettled(fixed.store, sel.store);
  const warehouseDone = dupSideSettled(fixed.warehouse, sel.warehouse);
  const key = barcode.replace(/\W/g, "_");
  const confirmButton = document.getElementById("dpconf_" + key);
  if (confirmButton) confirmButton.disabled = !(storeDone && warehouseDone);
}

function dupHighlight(barcode, type) {
  const key = barcode.replace(/\W/g, "_");
  const chosen = (p2DupSel[barcode] || {})[type];
  const fixed = (p2DupFixed[barcode] || {})[type];
  const allSelected = fixed && chosen && chosen.size === fixed.uniques.length;
  document.querySelectorAll(".dpbtn-" + type + "-" + key).forEach((button) => {
    const loc = button.dataset.loc;
    const isKeep = loc === KEEP_ALL;
    const active = isKeep ? allSelected : (chosen && chosen.has(loc));
    button.style.background = active ? (isKeep ? "#047857" : "#c2410c") : "transparent";
    button.style.color = active ? "#fff" : "#fb923c";
  });
}

function toggleDupLoc(barcode, type, loc) {
  if (!p2DupSel[barcode]) p2DupSel[barcode] = { store: null, warehouse: null };
  if (!p2DupSel[barcode][type]) p2DupSel[barcode][type] = new Set();
  const chosen = p2DupSel[barcode][type];
  if (chosen.has(loc)) { if (chosen.size > 1) chosen.delete(loc); }
  else chosen.add(loc);
  dupHighlight(barcode, type);
  dupTryResolve(barcode);
}

function keepAllDupLoc(barcode, type) {
  const side = (p2DupFixed[barcode] || {})[type];
  if (!side) return;
  if (!p2DupSel[barcode]) p2DupSel[barcode] = { store: null, warehouse: null };
  p2DupSel[barcode][type] = new Set(side.uniques);
  dupHighlight(barcode, type);
  dupTryResolve(barcode);
}

function confirmDupLoc(barcode) {
  const fixed = p2DupFixed[barcode] || {};
  const sel = p2DupSel[barcode] || {};
  const value = composeDupParts(fixed, sel);
  if (!value) return;
  _resolveEx(barcode, value);
}

function buildDupSide(stockpileLocs, scanLocs) {
  const { uniques, sources } = dedupeWithSources(stockpileLocs, scanLocs);
  return { stockpileLocs: stockpileLocs || [], scanLocs: scanLocs || [], uniques, sources };
}

function renderDupSide(barcode, key, type, side, label, keepLabel) {
  if (side.uniques.length === 0) return "";
  if (side.uniques.length === 1) {
    const loc = side.uniques[0];
    return `<span class="sub">${label}：<span class="loc">${esc(loc)}</span>${badgeFor(side.sources[loc])} <span style="color:#4a5568">（自动保留）</span></span>`;
  }
  const chosen = (p2DupSel[barcode] || {})[type];
  const btns = side.uniques.map((loc) => {
    const selected = chosen && chosen.has(loc);
    return `<button class="btn-s is-warn dpbtn-${type}-${key}" data-loc="${esc(loc)}" style="${selected ? "background:#c2410c;color:#fff" : ""}" onclick="toggleDupLoc('${jesc(barcode)}','${type}','${jesc(loc)}')">${esc(loc)}${badgeFor(side.sources[loc])}</button>`;
  }).join("");
  const allSelected = chosen && chosen.size === side.uniques.length;
  const keepBtn = `<button class="btn-s is-success dpbtn-${type}-${key}" data-loc="${KEEP_ALL}" style="${allSelected ? "background:#047857;color:#fff" : ""}" onclick="keepAllDupLoc('${jesc(barcode)}','${type}')">${keepLabel}</button>`;
  return `<div><div class="sub" style="margin-bottom:4px">选择${label}库位：</div><div class="actions">${btns}${keepBtn}</div></div>`;
}

export function renderDupCard(warning) {
  const barcode = warning.barcode;
  const key = barcode.replace(/\W/g, "_");
  const storeSide = buildDupSide(warning.stockpile_stores, warning.scan_stores);
  const warehouseSide = buildDupSide(warning.stockpile_warehouses, warning.scan_warehouses);
  p2DupFixed[barcode] = { store: storeSide, warehouse: warehouseSide };
  const storeHtml = renderDupSide(barcode, key, "store", storeSide, "店面", "保留全部店面");
  const warehouseHtml = renderDupSide(barcode, key, "warehouse", warehouseSide, "仓库", "保留全部仓库");
  setTimeout(() => dupTryResolve(barcode), 0);
  return `<div class="warn"><div class="row"><div class="col"><span class="code">${esc(barcode)}</span><span class="sub" style="color:#fbbf24">多库位冲突，请手动选择</span></div></div><div class="col" style="gap:8px;margin-top:8px">${storeHtml}${warehouseHtml}</div><div class="actions" style="margin-top:8px"><button class="btn-s is-warn-solid" id="dpconf_${key}" disabled onclick="confirmDupLoc('${jesc(barcode)}')">确认选择</button></div></div>`;
}

window.toggleDupLoc = toggleDupLoc;
window.keepAllDupLoc = keepAllDupLoc;
window.confirmDupLoc = confirmDupLoc;