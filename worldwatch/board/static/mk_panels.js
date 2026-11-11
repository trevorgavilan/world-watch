/* The markets terminal: the picked number's header (value, change, both times, source, Delayed, the
   owner's notice, its glossary entry), countdowns, the side tabs (what moved, why, your lines), the
   bottom tabs (practice holdings and trades, calendar, glossary) and the status bar.
   A later "assistant" panel registers here the same way (the trading-assistant task, parked). */
"use strict";

(() => {
  const W = window.WWM;
  const { el, $ } = W;
  const NY = "America/New_York";
  const CDMX = "America/Mexico_City";

  // The UTC instant of a wall-clock time in a time zone (no library): guess, then correct by the zone's offset.
  function zoned(y, m, d, hh, mm, tz) {
    const guess = Date.UTC(y, m - 1, d, hh, mm);
    const shown = new Intl.DateTimeFormat("en-US", { timeZone: tz, year: "numeric", month: "numeric", day: "numeric",
      hour: "numeric", minute: "numeric", hourCycle: "h23" }).formatToParts(new Date(guess));
    const get = (t) => Number(shown.find((p) => p.type === t).value);
    const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour") % 24, get("minute"));
    return guess - (asUtc - guess);
  }

  function wallDate(ms, tz) {
    const f = new Intl.DateTimeFormat("en-US", { timeZone: tz, year: "numeric", month: "numeric", day: "numeric", weekday: "short" });
    const parts = Object.fromEntries(f.formatToParts(new Date(ms)).map((p) => [p.type, p.value]));
    return { y: Number(parts.year), m: Number(parts.month), d: Number(parts.day), weekday: parts.weekday };
  }

  // The next weekday at hh:mm in tz, at or after `from` (bank and market holidays are not counted).
  function nextWeekday(from, hh, mm, tz) {
    for (let k = 0; k < 8; k++) {
      const w = wallDate(from + k * 86400000, tz);
      if (w.weekday === "Sat" || w.weekday === "Sun") continue;
      const t = zoned(w.y, w.m, w.d, hh, mm, tz);
      if (t >= from) return t;
    }
    return null;
  }

  function span(ms) {
    const minutes = Math.max(0, Math.round(ms / 60000));
    if (minutes < 60) return minutes + " min";
    if (minutes < 48 * 60) return Math.floor(minutes / 60) + " h " + (minutes % 60) + " min";
    return Math.round(minutes / 1440) + " days";
  }

  function countdowns(state) {
    const now = new Date(state.now).getTime();
    const rows = [];
    const fix = nextWeekday(now, 12, 0, CDMX);
    if (fix) rows.push(["Next FIX (12:00 CDMX)", fix - now]);
    const open = nextWeekday(now, 9, 30, NY), close = nextWeekday(now, 16, 0, NY);
    if (open && close) rows.push(close < open ? ["NYSE closes in", close - now] : ["NYSE opens in", open - now]);
    const next = (state.body.calendar || []).find((c) => new Date(c.day + "T23:59:59Z").getTime() >= now);
    if (next) rows.push([next.en, new Date(next.day + "T12:00:00Z").getTime() - now]);
    const host = $("countdown");
    host.replaceChildren();
    for (const [label, ms] of rows) {
      const li = el("li");
      li.append(el("span", label), el("span", span(ms), "num"));
      host.append(li);
    }
    host.append(el("li", "Holidays not counted.", "meta"));
  }

  function definition(term) {
    const box = $("pick-define");
    box.replaceChildren();
    box.append(el("strong", term.en + ": "), term.en_text + " ", el("span", term.es + ": " + term.es_text, "es"), " ");
    box.append(W.link("Source: " + new URL(term.source).hostname, term.source));
  }

  function head(state) {
    const item = state.items[state.prefs.pick];
    if (!item) return;
    $("pick-name").textContent = item.en;
    $("pick-sub").textContent = item.es + " · " + (item.unit_en || "");
    const star = $("star");
    star.textContent = W.starred(item.id) ? "★" : "☆";
    star.setAttribute("aria-pressed", String(W.starred(item.id)));
    const term = state.terms[item.term];
    const termButton = $("pick-term");
    termButton.hidden = !term;
    if (term) termButton.setAttribute("aria-label", `What is “${term.en}”?`);
    const open = termButton.getAttribute("aria-expanded") === "true" && term;
    $("pick-define").hidden = !open;
    if (open) definition(term);
    const stats = $("stats");
    stats.replaceChildren();
    const add = (label, value, cls) => {
      const d = el("div");
      const dd = el("dd", null, cls);
      if (value instanceof Node) dd.append(value); else dd.textContent = value;
      d.append(el("dt", label), dd);
      stats.append(d);
    };
    if (!item.latest) {
      const why = (state.body.waiting || {})[item.source];
      add("Last", "No number yet" + (why ? ` — ${why}` : ""));
      return;
    }
    add("Last", W.grouped(item.latest.value) + " " + item.unit_en, "big");
    const c = W.change(item);
    const since = item.change ? (item.change.since === "reported" ? (item.source === "coingecko" ? "24 h, as reported" : "vs previous close, as reported")
      : "since " + W.when(item.change.since, true)) : "";
    add("Change", el("span", c.text || "—", c.dir));
    if (since) add("Over", since);
    add(item.daily ? "For" : "As of", W.when(item.latest.at, item.daily));
    add("Fetched", W.ago(item.latest.fetched_at));
    const src = el("span");
    src.append(el("span", "Delayed", "tag"), " ", W.link(item.source, item.page));
    add("Source", src);
    const notes = el("p", item.delay_en, "meta");
    if (item.history_note) notes.append(el("br"), item.history_note);
    if (item.notice) notes.append(el("br"), item.notice);
    const wide = el("div", null, "wide");
    wide.append(notes);
    stats.append(wide);
  }

  function entry(row, dateOnly) {
    const li = el("li");
    li.append(W.link(row.title, row.url));
    if (row.summary && row.summary !== row.title) li.append(el("div", row.summary, "meta"));
    li.append(el("div", `${W.when(row.at, dateOnly)} · fetched ${W.ago(row.fetched_at)} · ${row.source}` +
      (row.basis === "inferred" ? " · worked out by World Watch" : ""), "meta"));
    return li;
  }

  function list(id, rows, empty, render) {
    const host = $(id);
    host.replaceChildren();
    if (!rows.length) { if (empty) host.append(el("li", empty, "meta")); return; }
    rows.forEach((r) => host.append(render(r)));
  }

  function side(state) {
    const b = state.body;
    for (const t of document.querySelectorAll("[data-side]")) {
      t.setAttribute("aria-selected", String(t.dataset.side === state.prefs.side));
      $("side-" + t.dataset.side).hidden = t.dataset.side !== state.prefs.side;
    }
    list("moves", b.moves || [], "Nothing recent enough to compare yet.", (m) => {
      const li = el("li");
      const go = el("button", m.en);
      go.type = "button";
      go.className = "linkish";
      go.addEventListener("click", () => W.pick(m.id));
      li.append(go, " ", el("span", W.signed(m.pct, 2) + "%", W.direction(m.pct) + " num"),
        el("div", W.when(m.at, m.at.endsWith("T00:00:00Z")), "meta"));
      return li;
    });
    list("statements", b.statements || [], "No statements stored yet.", (r) => entry(r, false));
    list("alerts", b.alerts || [], "", (r) => entry(r, true));
    list("lines", b.lines || [], "No peso lines.", (t) => el("li", t));
    list("problems", b.problems || [], "", (t) => el("li", "markets.txt " + t));
  }

  function table(headers, rows) {
    const t = el("table");
    const tr = el("tr");
    headers.forEach((h) => tr.append(el("th", h)));
    t.append(tr);
    rows.forEach((cells) => {
      const r = el("tr");
      cells.forEach((c) => { const td = el("td"); if (c instanceof Node) td.append(c); else td.textContent = c; r.append(td); });
      t.append(r);
    });
    return t;
  }

  function bottom(state) {
    for (const t of document.querySelectorAll("[data-bottom]")) {
      t.setAttribute("aria-selected", String(t.dataset.bottom === state.prefs.bottom));
      $("bottom-" + t.dataset.bottom).hidden = t.dataset.bottom !== state.prefs.bottom;
    }
    const b = state.body;
    const book = b.paper;
    const holdings = $("bottom-holdings");
    holdings.replaceChildren();
    holdings.append(el("p", "Play money only: no broker, no real orders, no money moves. Trade with python -m worldwatch paper buy AMX 10.", "hint"));
    if (b.paper_problem) holdings.append(el("p", "The ledger could not be read: " + b.paper_problem, "hint"));
    if (book) {
      const total = el("p", null, "hint");
      total.append(`${W.grouped(book.total_mxn)} MXN of ${W.grouped(book.start_mxn)} play pesos `,
        el("span", typeof book.change_pct === "number" ? W.signed(book.change_pct, 2) + "%" : "", W.direction(book.change_pct || 0)),
        ` · cash ${W.grouped(book.cash_mxn)} MXN · ${book.trades} trades`);
      holdings.append(total);
      if (book.holdings.length) {
        holdings.append(table(["Holding", "Qty", "Cost MXN", "Now MXN"], book.holdings.map((h) =>
          [h.id, h.qty, W.grouped(h.cost_mxn), h.value_mxn === null ? "no fresh price" : W.grouped(h.value_mxn)])));
      }
    }
    const trades = $("bottom-trades");
    trades.replaceChildren();
    const recent = (book && book.recent) || [];
    if (!recent.length) trades.append(el("p", "No practice trades yet.", "hint"));
    else trades.append(table(["When", "By", "Side", "What", "Qty", "Price", "FIX"], recent.map((t) =>
      [W.when(t.at, false), t.by || "you", t.side, t.instrument, t.qty, `${t.price} ${t.currency}`, t.fx])));
    list("calendar", b.calendar || [], "Nothing in the next 60 days.", (r) => {
      const li = el("li");
      li.append(W.link(r.en, r.url), el("div", `${W.when(r.day + "T00:00:00Z", true)} · ${r.note} · ${r.source}`, "meta"));
      return li;
    });
    const gloss = $("bottom-glossary");
    if (!gloss.childElementCount) {
      for (const t of b.glossary || []) {
        const d = el("details");
        d.append(el("summary", `${t.en} · ${t.es}`), el("p", t.en_text), el("p", t.es_text, "meta"));
        const from = el("p", null, "meta");
        from.append("From: ", W.link(new URL(t.source).hostname, t.source));
        d.append(from);
        gloss.append(d);
      }
    }
  }

  function status(state) {
    const b = state.body;
    $("disclaimer").textContent = `${b.disclaimer_en} ${b.disclaimer_es}`;
    const dots = $("dots");
    dots.replaceChildren();
    for (const s of b.sources || []) {
      const li = el("li");
      const dot = el("span", null, s.last_ok_at ? (s.stale ? "stale" : "ok") : "never");
      dot.title = `${s.source}: ` + (s.last_ok_at ? `fetched ${W.ago(s.last_ok_at)}` : "never fetched") +
        (s.last_error ? ` — ${s.last_error}` : "");
      dot.setAttribute("role", "img");
      dot.setAttribute("aria-label", dot.title);
      li.append(dot);
      dots.append(li);
    }
    $("status").textContent = "Updated " + W.when(b.now, false) + " · information only, not advice";
  }

  function draw(state) {
    head(state);
    countdowns(state);
    side(state);
    bottom(state);
    status(state);
  }

  function init() {
    $("star").addEventListener("click", () => W.toggleStar(W.state.prefs.pick));
    $("pick-term").addEventListener("click", () => {
      const b = $("pick-term");
      b.setAttribute("aria-expanded", String(b.getAttribute("aria-expanded") !== "true"));
      W.drawAll();
    });
    for (const t of document.querySelectorAll("[data-side]")) t.addEventListener("click", () => W.setPref("side", t.dataset.side));
    for (const t of document.querySelectorAll("[data-bottom]")) t.addEventListener("click", () => W.setPref("bottom", t.dataset.bottom));
  }

  W.panels = { zoned, nextWeekday };
  W.register({ init, draw });
})();
