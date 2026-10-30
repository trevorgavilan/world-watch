/* World Watch Board. Everything comes from this server's read-only /api/ routes.
   Source text is data: it is only ever set with textContent, and a link is used only after
   safe() re-checks it as http(s) (D-17). globe.gl renders point labels as HTML, so they stay off.
   The layout (the globe / list split, folded lists) is remembered in this browser's localStorage. */
"use strict";

(() => {
  const TZ = "America/Mexico_City";
  const REFRESH_MS = 60 * 1000;
  const $ = (id) => document.getElementById(id);
  const SIDE_KEY = "ww.board.side";      // the list column's width, in px
  const FOLD_KEY = "ww.board.folded";    // the ids of the folded lists
  const SIDE_MIN = 260;
  const GLOBE_MIN = 300;
  const KEY_STEP = 20;

  const moment = new Intl.DateTimeFormat("en-GB", {
    timeZone: TZ, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });
  const day = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "2-digit", month: "short", year: "numeric" });

  const state = {
    globe: null, layers: [], shown: {}, points: {}, now: null,
    side: null, folded: new Set(), sources: [], detail: null,
  };

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
    const then = new Date(iso).getTime();
    const now = new Date(state.now).getTime();
    if (Number.isNaN(then) || Number.isNaN(now)) return "?";
    const minutes = Math.max(0, Math.round((now - then) / 60000));
    if (minutes < 60) return minutes + " min ago";
    if (minutes < 48 * 60) return Math.round(minutes / 60) + " h ago";
    return Math.round(minutes / 1440) + " days ago";
  }

  function status(text, isError) {
    const line = $("status");
    line.textContent = text;
    line.className = isError ? "error" : "";
  }

  async function getJson(path) {
    const response = await fetch(path, { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error(path + " answered " + response.status);
    return response.json();
  }

  /* Storage may be refused, or hold anything a user, an old version or an extension left there:
     every read is checked, and a refusal only means the layout isn't kept. */
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

  function storedSide() {
    const raw = recall(SIDE_KEY);
    return raw !== null && /^\d{1,5}$/.test(raw) ? Number(raw) : null;
  }

  function storedFolds() {
    try {
      const ids = JSON.parse(recall(FOLD_KEY));
      return new Set(Array.isArray(ids) ? ids.filter((id) => typeof id === "string") : []);
    } catch (_) {
      return new Set();
    }
  }

  /* null means "the default split": 28% of the room, never under 380 px. */
  function clampSide(px) {
    const room = $("board").clientWidth - $("divider").offsetWidth;
    const wanted = px === null ? Math.max(380, room * 0.28) : px;
    return Math.round(Math.max(SIDE_MIN, Math.min(wanted, room - GLOBE_MIN)));
  }

  function applySide() {
    const px = clampSide(state.side);
    $("board").style.setProperty("--side", px + "px");
    const divider = $("divider");
    divider.setAttribute("aria-valuenow", String(px));
    divider.setAttribute("aria-valuemin", String(SIDE_MIN));
    divider.setAttribute("aria-valuemax", String(clampSide(Infinity)));
    divider.setAttribute("aria-valuetext", "lists " + px + " pixels wide");
  }

  function setSide(px, keep) {
    state.side = clampSide(px);
    applySide();
    if (keep) remember(SIDE_KEY, String(state.side));
  }

  function makeDivider() {
    const divider = $("divider");
    let drag = null;
    divider.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      drag = { x: e.clientX, side: clampSide(state.side) };
      divider.setPointerCapture(e.pointerId);
      divider.classList.add("dragging");
      e.preventDefault();
    });
    divider.addEventListener("pointermove", (e) => {
      if (drag) setSide(drag.side + drag.x - e.clientX, false);
    });
    const end = () => {
      if (!drag) return;
      drag = null;
      divider.classList.remove("dragging");
      if (state.side !== null) remember(SIDE_KEY, String(state.side));  // a click without a move keeps the default
    };
    divider.addEventListener("pointerup", end);
    divider.addEventListener("pointercancel", end);
    divider.addEventListener("lostpointercapture", end);
    divider.addEventListener("keydown", (e) => {
      const step = { ArrowLeft: KEY_STEP, ArrowRight: -KEY_STEP, Home: Infinity, End: -Infinity }[e.key];
      if (!step) return;
      e.preventDefault();
      setSide(clampSide(state.side) + step, true);  // Home: widest lists, End: narrowest
    });
    divider.addEventListener("dblclick", () => {  // back to the default split
      state.side = null;
      applySide();
      remember(SIDE_KEY, "");
    });
    window.addEventListener("resize", applySide);
    state.side = storedSide();
    applySide();
  }

  function foldable(box, list, id) {
    const button = box.querySelector(".fold");
    button.dataset.key = "fold:" + id;
    const show = (open) => {
      list.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
    };
    show(!state.folded.has(id));
    button.addEventListener("click", () => {
      const open = list.hidden;
      if (open) state.folded.delete(id);
      else state.folded.add(id);
      show(open);
      remember(FOLD_KEY, JSON.stringify([...state.folded]));
    });
  }

  function color(weight) {
    const w = Math.min(Math.max(Number(weight) || 0, 0), 1);
    return "hsl(" + Math.round(55 - 55 * w) + ", 95%, " + Math.round(62 - 12 * w) + "%)";
  }

  function makeGlobe() {
    if (typeof Globe !== "function") {
      status("The globe library did not load.", true);
      return null;
    }
    const box = $("globe");
    const globe = new Globe(box)
      .globeImageUrl("/static/earth.jpg")
      .backgroundColor("#05070b")
      .pointLabel(null)
      .pointLat("lat")
      .pointLng("lon")
      .pointAltitude((p) => 0.005 + p.weight * 0.08)
      .pointRadius((p) => 0.35 + p.weight * 0.9)
      .pointColor((p) => color(p.weight))
      .pointsMerge(false)
      .onPointClick(pick);
    const fit = () => globe.width(box.clientWidth).height(box.clientHeight);
    new ResizeObserver(fit).observe(box);  // the window, or the divider
    fit();
    globe.pointOfView({ lat: 19.4, lng: -99.1, altitude: 2.4 });  // start over Mexico
    return globe;
  }

  function line(label, value) {
    const p = el("p", null, "meta");
    p.append(el("b", label + " "), document.createTextNode(value));
    return p;
  }

  function pick(point) {
    const body = $("picked-body");
    body.replaceChildren();
    if (!point) {
      $("picked").hidden = true;
      return;
    }
    const title = el("p", null, "title");
    title.append(link(point.title, point.url));
    body.append(
      title,
      line("Severity:", point.severity || "—"),
      line("Happened:", when(point.happened_at, false)),
      line("Fetched:", when(point.fetched_at, false) + " (" + ago(point.fetched_at) + ")"),
      line("Source:", point.source),
    );
    $("picked").hidden = false;
  }

  function drawPoints() {
    if (!state.globe) return;
    const all = [];
    for (const layer of state.layers) {
      if (state.shown[layer.id] !== false) all.push(...(state.points[layer.id] || []));
    }
    state.globe.pointsData(all);
  }

  function drawLayers() {
    const list = $("layers");
    list.replaceChildren();
    for (const layer of state.layers) {
      const box = el("input");
      box.type = "checkbox";
      box.dataset.key = "layer:" + layer.id;
      box.checked = state.shown[layer.id] !== false;
      box.addEventListener("change", () => {
        state.shown[layer.id] = box.checked;
        drawPoints();
      });
      const label = el("label");
      const count = (state.points[layer.id] || []).length;
      label.append(box, el("span", layer.en + " · " + layer.es), el("span", "(" + count + ", " + layer.source + ")", "count"));
      const item = el("li");
      item.append(label);
      list.append(item);
    }
    if (!state.layers.length) list.append(el("li", "No layers yet.", "empty"));
  }

  function sourceLine(s) {
    if (!s.last_ok_at) return s.source + " · never fetched";
    return s.source + " · fetched " + ago(s.last_ok_at) + (s.stale ? " · stale" : "");
  }

  function sourceDetail(s) {
    return (s.last_ok_at ? "last good fetch " + when(s.last_ok_at, false) : "no good fetch yet") +
      (s.last_error ? " · last error: " + s.last_error : "");
  }

  function drawDetail() {
    const box = $("fresh-detail");
    const s = state.sources.find((x) => x.source === state.detail);
    if (!s) state.detail = null;
    box.textContent = s ? sourceLine(s) + " · " + sourceDetail(s) : "";
    box.hidden = !s;
    for (const dot of $("fresh").querySelectorAll(".dot")) {
      dot.setAttribute("aria-pressed", String(dot.dataset.source === state.detail));
    }
  }

  /* One dot per source, on one row: its name and times are in the tooltip, and in a line below on click. */
  function drawFreshness(sources) {
    const list = $("fresh");
    const credits = $("credits");
    list.replaceChildren();
    credits.replaceChildren();
    const counts = { ok: 0, stale: 0, never: 0 };
    for (const s of sources) {
      const kind = s.last_ok_at ? (s.stale ? "stale" : "ok") : "never";
      counts[kind] += 1;
      const dot = el("button", null, "dot " + kind);
      dot.type = "button";
      dot.dataset.source = s.source;
      dot.dataset.key = "dot:" + s.source;
      dot.setAttribute("aria-label", sourceLine(s));
      dot.title = sourceLine(s) + "\n" + sourceDetail(s);
      dot.addEventListener("click", () => {
        state.detail = state.detail === s.source ? null : s.source;
        drawDetail();
      });
      const item = el("li");
      item.append(dot);
      list.append(item);
      if (s.credit) {
        const credit = el("li");
        credit.append(link(s.credit, s.credit_url));
        credits.append(credit);
      }
    }
    $("fresh-sum").textContent = counts.ok + " fresh · " + counts.stale + " stale · " + counts.never + " never fetched";
    state.sources = sources;
    drawDetail();
  }

  function drawPanel(spec, body) {
    const box = el("section", null, "box");
    const head = el("h2");
    const fold = el("button", spec.en + " · " + spec.es, "fold");
    fold.type = "button";
    head.append(fold);
    box.append(head);
    const list = el("ol", null, "entries");
    for (const e of body.entries) {
      const item = el("li");
      const title = el("div", null, "title");
      title.append(link(e.title, e.url));
      const happened = body.date_only ? "added " + when(e.happened_at, true) : when(e.happened_at, false);
      item.append(
        title,
        el("div", e.source + " · " + happened + " · fetched " + ago(e.fetched_at), "meta"),
        el("p", e.summary, "summary"),
      );
      list.append(item);
    }
    if (!body.entries.length) list.append(el("li", "Nothing in this window.", "empty"));
    box.append(list);
    foldable(box, list, "panel:" + spec.id);
    return box;
  }

  async function load() {
    try {
      const board = await getJson("/api/board");
      state.now = board.now;
      state.layers = board.layers;
      const layerBodies = await Promise.all(board.layers.map((l) => getJson("/api/layers/" + encodeURIComponent(l.id))));
      board.layers.forEach((l, i) => { state.points[l.id] = layerBodies[i].points; });
      const panelBodies = await Promise.all(board.panels.map((p) => getJson("/api/panels/" + encodeURIComponent(p.id))));
      const focused = document.activeElement && document.activeElement.dataset
        ? document.activeElement.dataset.key : undefined;
      $("panels").replaceChildren(...board.panels.map((p, i) => drawPanel(p, panelBodies[i])));
      drawFreshness(board.sources);
      drawLayers();
      drawPoints();
      if (focused) {  // the refresh rebuilt the dot, fold or box the keyboard was on: stay on it
        const again = [...document.querySelectorAll("[data-key]")].find((n) => n.dataset.key === focused);
        if (again) again.focus();
      }
      status("Updated " + when(board.now, false) + " · from the local store only", false);
    } catch (err) {
      status("Could not read the store: " + err.message + " (showing what was last loaded)", true);
    }
  }

  state.folded = storedFolds();
  makeDivider();
  foldable($("layers-box"), $("layers"), "layers");
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.detail) {
      state.detail = null;
      drawDetail();
    }
  });
  state.globe = makeGlobe();
  load();
  setInterval(load, REFRESH_MS);
})();
