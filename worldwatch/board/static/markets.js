/* World Watch — Markets (/markets). Everything comes from the read-only /api/markets.
   Information only, never advice: the page shows numbers, where they come from and how late they are.
   Source text is data: set with textContent only; a link is used only after safe() re-checks it (D-17).
   The small charts are SVG polylines built from numbers, never from markup. */
"use strict";

(() => {
  const TZ = "America/Mexico_City";
  const REFRESH_MS = 60 * 1000;
  const SVG = "http://www.w3.org/2000/svg";
  const $ = (id) => document.getElementById(id);
  const moment = new Intl.DateTimeFormat("en-GB", {
    timeZone: TZ, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });
  const day = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", weekday: "short", day: "2-digit", month: "short", year: "numeric" });
  const state = { now: null, terms: {}, open: new Set(), waiting: {} };

  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (cls) node.className = cls;
    return node;
  }

  function safe(url) {
    if (typeof url !== "string") return null;
    try {
      const parsed = new URL(url);
      return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
    } catch (_) {
      return null;
    }
  }

  function link(text, url) {
    const safeUrl = safe(url);
    if (!safeUrl) return el("span", text);
    const a = el("a", text);
    a.href = safeUrl;
    a.rel = "noopener noreferrer";
    a.target = "_blank";
    return a;
  }

  function when(iso, dateOnly) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "?";
    return dateOnly ? day.format(d) : moment.format(d) + " CDMX";
  }

  function ago(iso) {
    const minutes = Math.round((new Date(state.now).getTime() - new Date(iso).getTime()) / 60000);
    if (Number.isNaN(minutes)) return "?";
    if (minutes < 60) return Math.max(0, minutes) + " min ago";
    if (minutes < 48 * 60) return Math.round(minutes / 60) + " h ago";
    return Math.round(minutes / 1440) + " days ago";
  }

  function grouped(text) {
    // "18.6226" -> "18.6226", "74732.77" -> "74,732.77": digits only, the source's decimals kept.
    const m = /^(-?)(\d+)(\.\d+)?$/.exec(String(text));
    if (!m) return String(text);
    return m[1] + m[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (m[3] || "");
  }

  function signed(n, digits) {
    if (typeof n !== "number" || !Number.isFinite(n)) return "";
    return (n > 0 ? "+" : n < 0 ? "−" : "±") + Math.abs(n).toFixed(digits);
  }

  function direction(n) {
    return n > 0 ? "up" : n < 0 ? "down" : "flat";
  }

  function spark(history) {
    const points = (history || []).map((p) => Number(p[1])).filter(Number.isFinite);
    if (points.length < 2) return null;
    const min = Math.min(...points);
    const max = Math.max(...points);
    const span = max - min || 1;
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("class", "spark");
    svg.setAttribute("viewBox", "0 0 100 30");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Last ${points.length} numbers, from ${grouped(String(points[0]))} to ${grouped(String(points[points.length - 1]))}`);
    const line = document.createElementNS(SVG, "polyline");
    line.setAttribute("points", points.map((v, i) =>
      `${(i / (points.length - 1) * 100).toFixed(2)},${(28 - (v - min) / span * 26).toFixed(2)}`).join(" "));
    svg.append(line);
    return svg;
  }

  function definition(id) {
    const term = state.terms[id];
    if (!term) return null;
    const box = el("div", null, "define");
    box.append(el("p", `${term.en}: ${term.en_text}`), el("p", `${term.es}: ${term.es_text}`));
    const from = el("p", null, "meta");
    from.append("From: ", link(new URL(term.source).hostname, term.source));
    box.append(from);
    return box;
  }

  function termButton(id, host, key) {
    if (!state.terms[id]) return null;
    const button = el("button", "?", "term");
    button.type = "button";
    button.setAttribute("aria-label", `What is “${state.terms[id].en}”?`);
    const opened = state.open.has(key);
    button.setAttribute("aria-expanded", String(opened));
    if (opened) host.append(definition(id));
    button.addEventListener("click", () => {
      const open = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(open));
      const shown = host.querySelector(".define");
      if (shown) shown.remove();
      if (open) { state.open.add(key); host.append(definition(id)); } else { state.open.delete(key); }
    });
    return button;
  }

  function tile(item) {
    const box = el("article", null, "tile");
    box.dataset.id = item.id;
    const name = el("div", null, "name");
    name.append(el("span", item.en, "label"));
    box.append(name);
    const more = termButton(item.term, box, "tile:" + item.id);
    if (more) name.append(more);
    if (!item.latest) {
      const why = state.waiting[item.source];
      box.append(el("p", `No number yet from ${item.source}` + (why ? ` — ${why}.` : "."), "empty"));
      box.append(el("p", item.delay_en, "meta"));
      return box;
    }
    const value = el("p", grouped(item.latest.value), "value");
    value.append(el("span", item.unit_en, "unit"));
    box.append(value);
    const c = item.change;
    if (c) {
      let text;
      if (c.since === "reported") {
        text = `${signed(c.pct, 2)}% (as reported${item.source === "coingecko" ? ", 24 h" : ", vs the previous close"})`;
      } else if (item.points) {
        text = `${signed(c.abs, 2)} percentage points since ${when(c.since, true)}`;
      } else {
        text = `${signed(c.abs, item.decimals)} (${signed(c.pct, 2)}%) since ${when(c.since, true)}`;
      }
      box.append(el("p", text, "change " + direction(c.pct !== undefined ? c.pct : c.abs)));
    }
    const chart = spark(item.history);
    if (chart) box.append(chart);
    const meta = el("p", null, "meta");
    meta.append(el("span", "Delayed", "tag"),
      `${item.daily ? "For" : "As of"} ${when(item.latest.at, item.daily)} · fetched ${ago(item.latest.fetched_at)} · `,
      link(item.source, item.page));
    box.append(meta, el("p", item.delay_en, "meta"));
    return box;
  }

  function drawGroups(groups) {
    const host = $("groups");
    host.replaceChildren();
    for (const g of groups) {
      const section = el("section", null, "group");
      section.setAttribute("aria-label", g.en);
      section.append(el("h3", `${g.en} · ${g.es}`));
      const tiles = el("div", null, "tiles");
      g.items.forEach((item) => tiles.append(tile(item)));
      section.append(tiles);
      host.append(section);
    }
  }

  function drawMoves(moves) {
    const host = $("moves");
    host.replaceChildren();
    if (!moves.length) { host.append(el("li", "Nothing recent enough to compare yet.", "meta")); return; }
    for (const m of moves) {
      const li = el("li");
      li.append(el("span", `${m.en}: `), el("span", `${signed(m.pct, 2)}%`, direction(m.pct)),
        el("span", ` (${when(m.at, false)})`, "meta"));
      host.append(li);
    }
  }

  function drawList(id, rows, empty, render) {
    const host = $(id);
    host.replaceChildren();
    if (!rows.length) { host.append(el("li", empty, "meta")); return; }
    rows.forEach((row) => host.append(render(row)));
  }

  function entry(row, dateOnly) {
    const li = el("li");
    li.append(link(row.title, row.url));
    if (row.summary && row.summary !== row.title) li.append(el("div", row.summary, "meta"));
    li.append(el("div", `${when(row.at, dateOnly)} · fetched ${ago(row.fetched_at)} · ${row.source}` +
      (row.basis === "inferred" ? " · worked out by World Watch" : ""), "meta"));
    return li;
  }

  function drawPaper(book, problem) {
    const host = $("paper");
    host.replaceChildren();
    if (problem) { host.append(el("p", "The ledger could not be read: " + problem, "problems")); return; }
    if (!book) return;
    const total = el("p", null);
    total.append(el("strong", `${grouped(book.total_mxn)} MXN`), ` of ${grouped(book.start_mxn)} play pesos `);
    if (typeof book.change_pct === "number") total.append(el("span", `(${signed(book.change_pct, 2)}%)`, direction(book.change_pct)));
    host.append(total, el("p", `Cash: ${grouped(book.cash_mxn)} MXN · ${book.trades} trades`, "meta"));
    if (!book.holdings.length) { host.append(el("p", "No holdings yet.", "meta")); return; }
    const table = el("table");
    const head = el("tr");
    ["Holding", "Qty", "Cost MXN", "Now MXN"].forEach((h) => head.append(el("th", h)));
    table.append(head);
    for (const h of book.holdings) {
      const tr = el("tr");
      tr.append(el("td", h.id), el("td", h.qty), el("td", grouped(h.cost_mxn)),
        el("td", h.value_mxn === null ? "no fresh price" : grouped(h.value_mxn)));
      table.append(tr);
    }
    host.append(table);
  }

  function drawGlossary(terms) {
    const host = $("glossary");
    host.replaceChildren();
    for (const t of terms) {
      const d = el("details");
      d.append(el("summary", `${t.en} · ${t.es}`), el("p", t.en_text), el("p", t.es_text, "meta"));
      const from = el("p", null, "meta");
      from.append("From: ", link(new URL(t.source).hostname, t.source));
      d.append(from);
      host.append(d);
    }
  }

  function draw(body) {
    state.now = body.now;
    state.terms = Object.fromEntries((body.glossary || []).map((t) => [t.id, t]));
    state.waiting = body.waiting || {};
    $("disclaimer").textContent = `${body.disclaimer_en} ${body.disclaimer_es}`;
    $("updated").textContent = "Updated " + when(body.now, false);
    $("alerts-box").hidden = !body.alerts.length;
    drawList("alerts", body.alerts, "", (r) => entry(r, true));
    drawMoves(body.moves);
    drawGroups(body.groups);
    drawList("lines", body.lines, "No peso lines.", (t) => el("li", t));
    drawList("problems", body.problems, "", (t) => el("li", "markets.txt " + t));
    drawList("calendar", body.calendar, "Nothing in the next 60 days.", (r) => {
      const li = el("li");
      li.append(link(r.en, r.url), el("div", `${when(r.day + "T00:00:00Z", true)} · ${r.note} · ${r.source}`, "meta"));
      return li;
    });
    drawList("statements", body.statements, "No statements stored yet.", (r) => entry(r, false));
    drawPaper(body.paper, body.paper_problem);
    if (!$("glossary").childElementCount) drawGlossary(body.glossary || []);
    $("status").textContent = "";
  }

  async function refresh() {
    try {
      const answer = await fetch("/api/markets", { cache: "no-store" });
      if (!answer.ok) throw new Error("HTTP " + answer.status);
      draw(await answer.json());
    } catch (err) {
      $("status").textContent = "Could not load the markets: " + err.message + " — trying again in a minute.";
    }
  }

  refresh();
  setInterval(refresh, REFRESH_MS);
})();
