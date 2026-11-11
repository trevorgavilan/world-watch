/* World Watch — the markets terminal (/markets): the core. Everything comes from the read-only
   /api/markets and /api/markets/series/<id>. Information only, never advice.
   Source text is data: set with textContent only; a link is used only after safe() re-checks it (D-17).
   The other parts (mk_list.js, mk_chart.js, mk_panels.js) register on WWM and draw from its state.
   What this browser remembers (stars, the picked number, tabs, the range) stays in its localStorage. */
"use strict";

window.WWM = (() => {
  const TZ = "America/Mexico_City";
  const REFRESH_MS = 60 * 1000;
  const STORE_KEY = "ww.markets";
  const DEFAULT_STARS = ["usd-mxn-fix", "sp500", "bitcoin-usd", "gold", "ust-10y", "mx-target"];
  const moment = new Intl.DateTimeFormat("en-GB", {
    timeZone: TZ, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });
  const day = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", weekday: "short", day: "2-digit", month: "short", year: "numeric" });
  const parts = [];

  const state = {
    body: null, now: null, items: {}, order: [], terms: {}, prev: {},
    prefs: { stars: DEFAULT_STARS.slice(), pick: "usd-mxn-fix", tab: "peso", range: 365, view: "chart", side: "moved", bottom: "holdings" },
  };

  function load() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "{}");
      if (saved && typeof saved === "object") {
        if (Array.isArray(saved.stars)) state.prefs.stars = saved.stars.filter((s) => typeof s === "string").slice(0, 60);
        for (const k of ["pick", "tab", "view", "side", "bottom"]) if (typeof saved[k] === "string") state.prefs[k] = saved[k];
        if ([7, 30, 91, 365].includes(saved.range)) state.prefs.range = saved.range;
      }
    } catch (_) { /* no storage, or junk in it: the defaults stand */ }
  }

  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state.prefs)); } catch (_) { /* private window: fine */ }
  }

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
    const m = /^(-?)(\d+)(\.\d+)?$/.exec(String(text));
    if (!m) return String(text);
    return m[1] + m[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (m[3] || "");
  }

  function fixed(n, digits) {
    return typeof n === "number" && Number.isFinite(n) ? grouped(n.toFixed(digits)) : "—";
  }

  function signed(n, digits) {
    if (typeof n !== "number" || !Number.isFinite(n)) return "";
    return (n > 0 ? "▲ +" : n < 0 ? "▼ −" : "± ") + Math.abs(n).toFixed(digits);
  }

  function direction(n) {
    return n > 0 ? "up" : n < 0 ? "down" : "flat";
  }

  // The change as one short text and its direction: per cent, or percentage points for a rate.
  function change(item) {
    const c = item && item.change;
    if (!c) return { text: "", dir: "flat" };
    if (item.points && typeof c.abs === "number") return { text: signed(c.abs, 2) + " pp", dir: direction(c.abs) };
    if (typeof c.pct === "number") return { text: signed(c.pct, 2) + "%", dir: direction(c.pct) };
    return { text: "", dir: "flat" };
  }

  function starred(id) {
    return state.prefs.stars.includes(id);
  }

  function toggleStar(id) {
    const stars = state.prefs.stars;
    state.prefs.stars = starred(id) ? stars.filter((s) => s !== id) : stars.concat(id);
    save();
    drawAll();
  }

  function pick(id) {
    if (!state.items[id]) return;
    state.prefs.pick = id;
    save();
    drawAll();
  }

  function setPref(key, value) {
    state.prefs[key] = value;
    save();
    drawAll();
  }

  function register(part) {
    parts.push(part);
  }

  function drawAll() {
    if (!state.body) return;
    for (const part of parts) {
      try { part.draw(state); } catch (err) { $("status").textContent = "A part of the page failed to draw: " + err.message; }
    }
  }

  const $ = (id) => document.getElementById(id);

  function absorb(body) {
    state.prev = Object.fromEntries(Object.values(state.items).map((i) => [i.id, i.latest && i.latest.value]));
    state.body = body;
    state.now = body.now;
    state.terms = Object.fromEntries((body.glossary || []).map((t) => [t.id, t]));
    state.items = {};
    state.order = [];
    for (const g of body.groups || []) {
      for (const item of g.items) {
        state.items[item.id] = item;
        state.order.push(item.id);
      }
    }
    if (!state.items[state.prefs.pick] && state.order.length) state.prefs.pick = state.order[0];
  }

  async function refresh() {
    try {
      const answer = await fetch("/api/markets", { cache: "no-store" });
      if (!answer.ok) throw new Error("HTTP " + answer.status);
      absorb(await answer.json());
      drawAll();
    } catch (err) {
      $("status").textContent = "Could not load the markets: " + err.message + " — trying again in a minute.";
    }
  }

  function onKey(event) {
    const target = event.target;
    if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const ranges = { 1: 7, 2: 30, 3: 91, 4: 365 };
    if (ranges[event.key]) { setPref("range", ranges[event.key]); event.preventDefault(); return; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      const shown = (window.WWM.list && window.WWM.list.shown()) || [];
      if (!shown.length) return;
      const at = shown.indexOf(state.prefs.pick);
      const next = event.key === "ArrowDown" ? Math.min(shown.length - 1, at + 1) : Math.max(0, at - 1);
      pick(shown[at < 0 ? 0 : next]);
      event.preventDefault();
    }
  }

  function boot() {
    load();
    document.addEventListener("keydown", onKey);
    for (const part of parts) if (part.init) part.init(state);
    refresh();
    setInterval(refresh, REFRESH_MS);
  }

  document.addEventListener("DOMContentLoaded", boot);

  return { state, el, safe, link, when, ago, grouped, fixed, signed, direction, change, starred, toggleStar, pick,
    setPref, register, drawAll, save, $ };
})();
