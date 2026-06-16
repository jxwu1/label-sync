// 旧 SPA tab 深链解析。classic script —— 禁 ESM export/import（index.html 以
// <script defer> 加载，加 export 会让旧 SPA 首页语法错）。顶层函数声明即全局。
// 优先级：query ?page= 命中 pageIds > pathname 首段命中 > null（spec §7 硬验收 #4）。
function resolveInitialPage(pathname, search, pageIds) {
  try {
    var ids = Array.isArray(pageIds) ? pageIds : [];
    var qp = new URLSearchParams(search || "").get("page");
    if (qp && ids.indexOf(qp) !== -1) return qp;
    var seg = String(pathname || "").split("/").filter(Boolean)[0];
    if (seg && ids.indexOf(seg) !== -1) return seg;
  } catch (_) {
    /* ignore */
  }
  return null;
}
