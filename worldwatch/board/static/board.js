/* World Watch Board. Everything comes from this server's read-only /api/ routes.
   Source text is data: it is only ever set with textContent, and a link is used only after
   safe() re-checks it as http(s) (D-17). globe.gl renders point labels as HTML, so they stay off. */
"use strict";

(() => {
  const TZ = "America/Mexico_City";
  const REFRESH_MS = 60 * 1000;
  const $ = (id) => document.getElementById(id);

  const moment = new Intl.DateTimeFormat("en-GB", {
    timeZone: TZ, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });
  const day = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "2-digit", month: "short", year: "numeric" });

  const state = { globe: null, layers: [], shown: {}, points: {}, now: null };

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
    window.addEventListener("resize", fit);
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

  function drawFreshness(sources) {
    const list = $("fresh");
    const credits = $("credits");
    list.replaceChildren();
    credits.replaceChildren();
    for (const s of sources) {
      const item = el("li", null, s.last_ok_at ? (s.stale ? "stale" : "ok") : "never");
      const text = s.last_ok_at ? "fetched " + ago(s.last_ok_at) : "never fetched";
      item.append(el("b", s.source), document.createTextNode(" " + text + (s.stale && s.last_ok_at ? " · stale" : "")));
      item.title = (s.last_ok_at ? "Last good fetch " + when(s.last_ok_at, false) : "No good fetch yet") +
        (s.last_error ? " · last error: " + s.last_error : "");
      list.append(item);
      if (s.credit) {
        const credit = el("li");
        credit.append(link(s.credit, s.credit_url));
        credits.append(credit);
      }
    }
  }

  function drawPanel(spec, body) {
    const box = el("section", null, "box");
    box.append(el("h2", spec.en + " · " + spec.es));
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
      $("panels").replaceChildren(...board.panels.map((p, i) => drawPanel(p, panelBodies[i])));
      drawFreshness(board.sources);
      drawLayers();
      drawPoints();
      status("Updated " + when(board.now, false) + " · from the local store only", false);
    } catch (err) {
      status("Could not read the store: " + err.message + " (showing what was last loaded)", true);
    }
  }

  state.globe = makeGlobe();
  load();
  setInterval(load, REFRESH_MS);
})();
