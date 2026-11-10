/* The Middle East live console (/live): several streams at once, opened from the Board's viewer.
   The list comes from this server's read-only /api/panels/live-cams and live-news; each tile plays one stream through
   player.js (D-24). The address's #<id> puts that stream first. Tiles can be changed with their
   picker; the layout and the picks are kept in this browser. A refresh of the list (every 10 min)
   only changes the pickers' options: a playing frame is never reloaded by it.
   Source text is set with textContent only. */
"use strict";

(() => {
  const P = window.WWPlayer;
  const REFRESH_MS = 10 * 60 * 1000;
  const PANELS = ["live-cams", "live-news"];
  const LAYOUTS = [1, 4, 6, 9];
  const LAYOUT_KEY = "ww.live.layout";
  const TILES_KEY = "ww.live.tiles";
  const $ = (id) => document.getElementById(id);
  const moment = new Intl.DateTimeFormat("en-GB", {
    timeZone: "America/Mexico_City", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });
  const v = { entries: [], layout: 4, picks: [], now: null };

  function remember(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (_) { /* not kept */ }
  }

  function recall(key) {
    try {
      return localStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }

  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (cls) node.className = cls;
    return node;
  }

  function storedLayout() {
    const n = Number(recall(LAYOUT_KEY));
    return LAYOUTS.includes(n) ? n : 4;
  }

  function storedPicks() {
    try {
      const ids = JSON.parse(recall(TILES_KEY));
      return Array.isArray(ids) ? ids.filter((id) => typeof id === "string").slice(0, 9) : [];
    } catch (_) {
      return [];
    }
  }

  function wanted() {
    const raw = decodeURIComponent(location.hash.slice(1));
    return /^[0-9a-f]{1,80}$/.test(raw) ? raw : null;
  }

  /* The streams for n tiles: the asked-for one first, then the kept picks, then the rest in order. */
  function fill(n) {
    const known = new Set(v.entries.map((e) => e.id));
    const out = [];
    for (const id of [wanted(), ...v.picks, ...v.entries.map((e) => e.id)]) {
      if (id && known.has(id) && !out.includes(id)) out.push(id);
      if (out.length === n) break;
    }
    return out;
  }

  function byId(id) {
    return v.entries.find((e) => e.id === id) || null;
  }

  function caption(tile, e) {
    const cap = tile.querySelector(".cap");
    cap.replaceChildren();
    const href = P.watchUrl(e);
    const a = el(href ? "a" : "span", e.title);
    if (href) {
      a.href = P.watchUrl(e);
      a.rel = "noopener noreferrer";
      a.target = "_blank";
    }
    cap.append(a, el("span", " · " + (P.isCam(e) ? "Live cam" : "Live news") + " · " + P.owner(e), "who"));
  }

  function options(select, current) {
    const groups = [["Cams", v.entries.filter(P.isCam)], ["News", v.entries.filter((e) => !P.isCam(e))]];
    select.replaceChildren();
    for (const [label, list] of groups) {
      if (!list.length) continue;
      const group = document.createElement("optgroup");
      group.label = label;
      for (const e of list) {
        const opt = el("option", e.title);
        opt.value = e.id;
        opt.selected = e.id === current;
        group.append(opt);
      }
      select.append(group);
    }
  }

  function play(tile, id, autoplay) {
    const e = byId(id);
    if (!e) return;
    tile.dataset.stream = id;
    const f = P.frame(e, autoplay);
    tile.querySelector(".screen").replaceChildren(...(f ? [f] : []));
    caption(tile, e);
  }

  function keepPicks() {
    v.picks = [...$("grid").querySelectorAll(".tile")].map((t) => t.dataset.stream).filter(Boolean);
    remember(TILES_KEY, JSON.stringify(v.picks));
  }

  function tile(id, n) {
    const t = el("section", null, "tile");
    const select = el("select");
    select.setAttribute("aria-label", "Stream in tile " + (n + 1));
    options(select, id);
    select.addEventListener("change", () => {
      play(t, select.value, true);
      keepPicks();
    });
    t.append(select, el("div", null, "screen"), el("p", null, "cap"));
    play(t, id, n === 0);  // one autoplaying player at a time (YouTube's rule): the first, muted
    return t;
  }

  function build() {
    const ids = fill(v.layout);
    $("grid").dataset.layout = String(v.layout);
    $("grid").replaceChildren(...ids.map((id, n) => tile(id, n)));
    for (const b of document.querySelectorAll("[data-layout]")) {
      b.setAttribute("aria-pressed", String(Number(b.dataset.layout) === v.layout));
    }
    if (!ids.length) $("grid").append(el("p", "No stream has been checked yet: run World Watch once.", "empty"));
    keepPicks();
  }

  function checkedLine() {
    const times = v.entries.map((e) => new Date(e.fetched_at).getTime()).filter(Number.isFinite);
    if (!times.length) return "";
    return "List checked " + moment.format(new Date(Math.max(...times))) + " CDMX";
  }

  async function load(first) {
    try {
      const bodies = await Promise.all(PANELS.map(async (id) => {
        const response = await fetch("/api/panels/" + id, { cache: "no-store", credentials: "same-origin" });
        if (!response.ok) throw new Error("the " + id + " list answered " + response.status);
        return response.json();
      }));
      v.entries = P.order(bodies.flatMap((body) => body.entries));
      $("checked").textContent = checkedLine();
      if (first) {
        build();
      } else {
        for (const t of $("grid").querySelectorAll(".tile")) options(t.querySelector("select"), t.dataset.stream);
      }
      $("status").textContent = "";
    } catch (err) {
      $("status").textContent = "Could not read the list: " + err.message;
      if (first) setTimeout(() => load(true), 3000);
    }
  }

  for (const b of document.querySelectorAll("[data-layout]")) {
    b.addEventListener("click", () => {
      v.layout = Number(b.dataset.layout);
      remember(LAYOUT_KEY, String(v.layout));
      build();
    });
  }
  v.layout = storedLayout();
  v.picks = storedPicks();
  load(true);
  setInterval(() => load(false), REFRESH_MS);
  window.WWLive = { state: v, refresh: () => load(false) };  // refresh: for the browser tests
})();
