/* The markets terminal: the big chart of the picked number (1W / 1M / 3M / 1Y) and the yield curves
   (today against about a month before). SVG built from numbers only; hover shows the day and value. */
"use strict";

(() => {
  const W = window.WWM;
  const { el, $ } = W;
  const SVG = "http://www.w3.org/2000/svg";
  const PAD = { left: 8, right: 64, top: 12, bottom: 22 };
  const DAY_MS = 86400000;
  const cache = { id: null, at: null, body: null, pending: null };
  const short = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "2-digit", month: "short" });
  const withYear = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "2-digit", month: "short", year: "2-digit" });
  const hour = new Intl.DateTimeFormat("en-GB", { timeZone: "America/Mexico_City", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

  function svgEl(tag, attrs, cls) {
    const node = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
    if (cls) node.setAttribute("class", cls);
    return node;
  }

  function text(x, y, label, anchor) {
    const t = svgEl("text", { x, y, "text-anchor": anchor || "start" });
    t.textContent = label;
    return t;
  }

  // The points the range asks for: everything for a week or a month; one per day (its last) beyond that.
  function inRange(points, rangeDays, nowIso) {
    const end = new Date(nowIso).getTime();
    const start = end - rangeDays * DAY_MS;
    const kept = points.filter((p) => { const t = new Date(p[0]).getTime(); return t >= start && t <= end + 300000; });
    if (rangeDays <= 30) return kept;
    const byDay = new Map();
    for (const p of kept) byDay.set(p[0].slice(0, 10), p);
    return [...byDay.values()];
  }

  function draw(state) {
    const view = state.prefs.view;
    for (const b of document.querySelectorAll("[data-view]")) b.setAttribute("aria-selected", String(b.dataset.view === view));
    for (const b of document.querySelectorAll("[data-range]")) b.setAttribute("aria-pressed", String(Number(b.dataset.range) === state.prefs.range));
    $("chart").hidden = view !== "chart";
    $("curves").hidden = view !== "curve";
    $("ranges").hidden = view !== "chart";
    if (view === "curve") { drawCurves(state); return; }
    const id = state.prefs.pick;
    if (cache.id === id && cache.at === state.now && cache.body) { plot(state, cache.body); return; }
    if (cache.id !== id) $("chart").replaceChildren(el("p", "Loading the chart…", "empty loading"));
    fetchSeries(state, id);
  }

  async function fetchSeries(state, id) {
    if (cache.pending === id) return;
    cache.pending = id;
    try {
      const answer = await fetch("/api/markets/series/" + encodeURIComponent(id), { cache: "no-store" });
      if (!answer.ok) throw new Error("HTTP " + answer.status);
      const body = await answer.json();
      Object.assign(cache, { id, at: state.now, body });
      if (state.prefs.pick === id && state.prefs.view === "chart") plot(state, body);
    } catch (err) {
      $("chart").replaceChildren(el("p", "Could not load the chart: " + err.message, "empty"));
    } finally {
      cache.pending = null;
    }
  }

  function plot(state, body) {
    const host = $("chart");
    host.replaceChildren();
    const item = state.items[body.id];
    const points = inRange(body.points || [], state.prefs.range, state.now);
    if (points.length < 2) {
      host.append(el("p", points.length ? "One number so far in this range: the chart fills as days pass." :
        "No numbers in this range yet.", "empty"));
      return;
    }
    const w = Math.max(200, host.clientWidth);
    const h = Math.max(160, host.clientHeight);
    const xs = points.map((p) => new Date(p[0]).getTime());
    const ys = points.map((p) => p[1]);
    let lo = Math.min(...ys), hi = Math.max(...ys);
    if (lo === hi) { lo -= 1; hi += 1; }
    const padY = (hi - lo) * 0.08;
    lo -= padY; hi += padY;
    const x0 = xs[0], x1 = xs[xs.length - 1] === x0 ? x0 + 1 : xs[xs.length - 1];
    const sx = (t) => PAD.left + (t - x0) / (x1 - x0) * (w - PAD.left - PAD.right);
    const sy = (v) => PAD.top + (hi - v) / (hi - lo) * (h - PAD.top - PAD.bottom);
    const svg = svgEl("svg", { viewBox: `0 0 ${w} ${h}`, role: "img",
      "aria-label": `${item ? item.en : body.id}: ${points.length} numbers from ${points[0][0].slice(0, 10)} to ${points[points.length - 1][0].slice(0, 10)}` });
    const grid = svgEl("g", {}, "grid");
    const axis = svgEl("g", {}, "axis");
    const decimals = Math.min(body.decimals || 2, 4);
    for (let i = 0; i <= 4; i++) {
      const v = lo + (hi - lo) * i / 4;
      grid.append(svgEl("line", { x1: PAD.left, x2: w - PAD.right, y1: sy(v), y2: sy(v) }));
      axis.append(text(w - PAD.right + 6, sy(v) + 4, W.fixed(v, decimals)));
    }
    const fmt = state.prefs.range > 91 ? withYear : short;
    [0, Math.floor(points.length / 2), points.length - 1].forEach((n, k) => {
      axis.append(text(sx(xs[n]), h - 6, fmt.format(new Date(xs[n])), ["start", "middle", "end"][k]));
    });
    const line = points.map((p, n) => `${sx(xs[n]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(" ");
    const area = `${sx(xs[0]).toFixed(1)},${sy(lo).toFixed(1)} ${line} ${sx(xs[xs.length - 1]).toFixed(1)},${sy(lo).toFixed(1)}`;
    svg.append(grid, axis, svgEl("polygon", { points: area }, "area"), svgEl("polyline", { points: line }, "line"));
    const cross = svgEl("line", { y1: PAD.top, y2: h - PAD.bottom, visibility: "hidden" }, "cross");
    const dot = svgEl("circle", { r: 3.5, visibility: "hidden" }, "dot");
    svg.append(cross, dot);
    const tip = el("div", null, "tip");
    tip.hidden = true;
    host.append(svg, tip);
    svg.addEventListener("mousemove", (event) => {
      const box = svg.getBoundingClientRect();
      const x = (event.clientX - box.left) * (w / box.width);
      let best = 0;
      for (let n = 1; n < xs.length; n++) if (Math.abs(sx(xs[n]) - x) < Math.abs(sx(xs[best]) - x)) best = n;
      const px = sx(xs[best]), py = sy(ys[best]);
      for (const [k, v] of [["x1", px], ["x2", px]]) cross.setAttribute(k, String(px));
      cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", String(px)); dot.setAttribute("cy", String(py)); dot.setAttribute("visibility", "visible");
      const daily = body.daily || points[best][0].endsWith("T00:00:00Z");
      tip.textContent = `${(daily ? withYear : hour).format(new Date(xs[best]))}  ${W.fixed(ys[best], decimals)}`;
      tip.hidden = false;
      const left = px / w * box.width;
      tip.style.left = Math.min(box.width - 160, Math.max(0, left + 10)) + "px";
      tip.style.top = Math.max(0, py / h * box.height - 30) + "px";
    });
    svg.addEventListener("mouseleave", () => {
      cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hidden = true;
    });
  }

  function maturity(years) {
    if (years < 1) return Math.round(years * 12) + "M";
    return Math.round(years) + "Y";
  }

  function drawCurves(state) {
    const host = $("curves");
    host.replaceChildren();
    const curves = state.body.curves || [];
    if (!curves.length) { host.append(el("p", "No yields stored yet.", "empty")); return; }
    for (const c of curves) {
      const box = el("section", null, "curve");
      box.dataset.curve = c.id;
      box.append(el("h3", `${c.en} · ${c.es}`));
      const legend = el("p", null, "legend");
      legend.append(el("span", "── today", "today"), el("span", "- - about a month before"));
      box.append(legend);
      const plotHost = el("div", null, "plot");
      box.append(plotHost);
      const table = el("table");
      const head = el("tr");
      ["Maturity", "Today", "Its date", "A month before", "Change"].forEach((t) => head.append(el("th", t)));
      table.append(head);
      for (const p of c.points) {
        const tr = el("tr");
        const diff = p.before === null ? null : p.value - p.before;
        tr.append(el("td", `${maturity(p.years)} · ${p.en}`), el("td", W.fixed(p.value, 2) + "%"),
          el("td", W.when(p.at, true)), el("td", p.before === null ? "—" : W.fixed(p.before, 2) + "%"),
          el("td", diff === null ? "—" : W.signed(diff, 2) + " pp", diff === null ? "" : W.direction(diff)));
        table.append(tr);
      }
      box.append(table);
      host.append(box);
      curvePlot(plotHost, c.points);
    }
  }

  function curvePlot(host, points) {
    const w = Math.max(240, host.clientWidth || 600), h = 220;
    const all = points.flatMap((p) => (p.before === null ? [p.value] : [p.value, p.before]));
    let lo = Math.min(...all), hi = Math.max(...all);
    if (lo === hi) { lo -= 0.5; hi += 0.5; }
    lo -= 0.1; hi += 0.1;
    const sx = (n) => PAD.left + 20 + n / Math.max(1, points.length - 1) * (w - PAD.left - PAD.right - 40);
    const sy = (v) => PAD.top + (hi - v) / (hi - lo) * (h - PAD.top - PAD.bottom);
    const svg = svgEl("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": "Yield by maturity, today and a month before" });
    const grid = svgEl("g", {}, "grid"), axis = svgEl("g", {}, "axis");
    for (let i = 0; i <= 4; i++) {
      const v = lo + (hi - lo) * i / 4;
      grid.append(svgEl("line", { x1: PAD.left, x2: w - PAD.right, y1: sy(v), y2: sy(v) }));
      axis.append(text(w - PAD.right + 6, sy(v) + 4, v.toFixed(2) + "%"));
    }
    points.forEach((p, n) => axis.append(text(sx(n), h - 6, maturity(p.years), "middle")));
    svg.append(grid, axis);
    const before = points.map((p, n) => (p.before === null ? null : `${sx(n).toFixed(1)},${sy(p.before).toFixed(1)}`)).filter(Boolean);
    if (before.length > 1) svg.append(svgEl("polyline", { points: before.join(" ") }, "before"));
    svg.append(svgEl("polyline", { points: points.map((p, n) => `${sx(n).toFixed(1)},${sy(p.value).toFixed(1)}`).join(" ") }, "line"));
    points.forEach((p, n) => svg.append(svgEl("circle", { cx: sx(n), cy: sy(p.value), r: 3 }, "dot")));
    host.append(svg);
  }

  function init() {
    for (const b of document.querySelectorAll("[data-view]")) b.addEventListener("click", () => W.setPref("view", b.dataset.view));
    for (const b of document.querySelectorAll("[data-range]")) b.addEventListener("click", () => W.setPref("range", Number(b.dataset.range)));
    let timer = null;
    window.addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(() => W.drawAll(), 150); });
  }

  W.chart = { inRange };
  W.register({ init, draw });
})();
