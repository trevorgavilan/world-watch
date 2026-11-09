/* World Watch Board — how each layer's points look on the flat map (Trevor, 2026-11-09).
   Teardrop pins only for what matters (M5+ quakes, GDACS Orange and Red); dots, rings, triangles and
   diamonds for the rest; fires as specks that merge into counted clusters when zoomed out.
   A layer this table doesn't know gets a plain dot sized and coloured by its weight.
   Everything drawn here is the canvas's own text (numbers, counts): no source text is ever drawn. */
"use strict";

window.WWPins = (() => {
  const CDMX = { lat: 19.4326, lon: -99.1332 };
  const CDMX_RINGS_KM = [150, 400, 700, 1200];  // D-22's bands (worldwatch\collectors\near_cdmx.py)
  const PIN_MAG = 5;                            // quakes from M5 get a pin and a label
  const CLUSTER_PX = 28;                        // fires closer than this on screen merge...
  const CLUSTER_MIN = 4;                        // ...when there are at least this many
  const LEVEL = { green: "#3fb950", orange: "#f0883e", red: "#f85149" };

  function clamp01(w) {
    return Math.min(Math.max(Number(w) || 0, 0), 1);
  }

  function heat(weight) {  // yellow (small) to red (big), as on the globe
    const w = clamp01(weight);
    return "hsl(" + Math.round(55 - 55 * w) + ", 95%, " + Math.round(62 - 12 * w) + "%)";
  }

  /* "M5.4 · PAGER yellow" -> 5.4; anything else -> null. */
  function magnitude(point) {
    const found = /^M\s?(\d{1,2}(?:\.\d+)?)/.exec(typeof point.severity === "string" ? point.severity : "");
    return found ? Number(found[1]) : null;
  }

  /* GDACS: "Orange · Earthquake" -> "orange"; no known level -> null. */
  function level(point) {
    const first = (typeof point.severity === "string" ? point.severity : "").split("·")[0].trim().toLowerCase();
    return Object.prototype.hasOwnProperty.call(LEVEL, first) ? first : null;
  }

  function eonetColor(point) {
    const kind = (typeof point.severity === "string" ? point.severity : "").toLowerCase();
    if (kind.includes("wildfire")) return "#ff7b3a";
    if (kind.includes("volcan")) return "#e5534b";
    if (kind.includes("storm")) return "#b083f0";
    if (kind.includes("ice")) return "#7ee0ff";
    return "#39c5bb";
  }

  /* Each style says how one point is drawn: shape, colour, radius, and whether it is pinned. */
  const STYLES = {
    quakes: (p) => {
      const mag = magnitude(p);
      return { shape: "circle", color: heat(p.weight), r: 2.5 + p.weight * 7,
        pin: mag !== null && mag >= PIN_MAG, label: mag !== null ? "M" + mag.toFixed(1) : null };
    },
    "ssn-quakes": (p) => {
      const mag = magnitude(p);
      return { shape: "ring", color: "#7ee0ff", r: 3.5 + p.weight * 7,
        pin: mag !== null && mag >= PIN_MAG, label: mag !== null ? "M" + mag.toFixed(1) : null };
    },
    gdacs: (p) => {
      const lvl = level(p);
      return { shape: "triangle", color: lvl ? LEVEL[lvl] : "#8b98a8", r: 7,
        pin: lvl === "orange" || lvl === "red", label: null };
    },
    eonet: (p) => ({ shape: "diamond", color: eonetColor(p), r: 5, pin: false, label: null }),
    fires: (p) => ({ shape: "speck", color: "#ff8c2a", r: 1.5 + p.weight * 2.5, pin: false, label: null }),
  };

  function style(layerId, point) {
    const make = STYLES[layerId];
    if (make) return make(point);
    return { shape: "circle", color: heat(point.weight), r: 3 + clamp01(point.weight) * 5, pin: false, label: null };
  }

  function clusters(layerId) {
    return layerId === "fires";
  }

  function shape(ctx, kind, x, y, r, color) {
    ctx.beginPath();
    if (kind === "triangle") {
      ctx.moveTo(x, y - r);
      ctx.lineTo(x + r * 0.95, y + r * 0.7);
      ctx.lineTo(x - r * 0.95, y + r * 0.7);
      ctx.closePath();
    } else if (kind === "diamond") {
      ctx.moveTo(x, y - r);
      ctx.lineTo(x + r, y);
      ctx.lineTo(x, y + r);
      ctx.lineTo(x - r, y);
      ctx.closePath();
    } else {
      ctx.arc(x, y, r, 0, Math.PI * 2);
    }
    if (kind === "ring") {
      ctx.lineWidth = 2;
      ctx.strokeStyle = color;
      ctx.stroke();
      return;
    }
    ctx.globalAlpha = kind === "speck" ? 0.8 : 0.9;
    ctx.fillStyle = color;
    ctx.fill();
    ctx.globalAlpha = 1;
    if (kind !== "speck") {
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(5, 7, 11, 0.85)";
      ctx.stroke();
    }
  }

  /* A teardrop whose tip sits on (x, y); returns where its head is, for clicks. */
  function teardrop(ctx, x, y, color) {
    const r = 7;
    const h = 20;
    const cy = y - h;
    const a = Math.acos(r / h);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.arc(x, cy, r, Math.PI / 2 + a, Math.PI / 2 - a + Math.PI * 2);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "rgba(5, 7, 11, 0.9)";
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, cy, 2.6, 0, Math.PI * 2);
    ctx.fillStyle = "#05070b";
    ctx.fill();
    return { x, y: cy, r: r + 2 };
  }

  function label(ctx, text, x, y) {
    ctx.font = "600 11px system-ui, 'Segoe UI', sans-serif";
    ctx.textBaseline = "middle";
    ctx.lineWidth = 3;
    ctx.strokeStyle = "rgba(5, 7, 11, 0.9)";
    ctx.strokeText(text, x, y);
    ctx.fillStyle = "#dfe6ee";
    ctx.fillText(text, x, y);
  }

  /* Fires: one cluster per CLUSTER_PX screen cell; a cell holding fewer than CLUSTER_MIN stays specks. */
  function group(placed, merge) {
    const single = (m) => ({ ...m, members: [m.point] });
    if (!merge) return placed.map(single);
    const cells = new Map();
    for (const m of placed) {
      const key = Math.floor(m.x / CLUSTER_PX) + ":" + Math.floor(m.y / CLUSTER_PX);
      if (!cells.has(key)) cells.set(key, []);
      cells.get(key).push(m);
    }
    const out = [];
    for (const cell of cells.values()) {
      if (cell.length < CLUSTER_MIN) {
        out.push(...cell.map(single));
        continue;
      }
      const x = cell.reduce((sum, m) => sum + m.x, 0) / cell.length;
      const y = cell.reduce((sum, m) => sum + m.y, 0) / cell.length;
      out.push({ ...cell[0], x, y, members: cell.map((m) => m.point) });
    }
    return out;
  }

  /* Dark inside, orange ring: never mistaken for a filled quake dot. */
  function cluster(ctx, x, y, count) {
    const r = Math.min(7 + Math.log2(count) * 2, 18);
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(36, 14, 4, 0.82)";
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#ff8c2a";
    ctx.stroke();
    ctx.font = "700 11px system-ui, 'Segoe UI', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#ffb066";
    ctx.fillText(String(count), x, y);
    ctx.textAlign = "start";
    return r;
  }

  /* A circle `km` around a place, as lat/lon steps (a true distance, so it bends on a flat map). */
  function ring(center, km) {
    const R = 6371.0088;
    const d = km / R;
    const lat1 = center.lat * Math.PI / 180;
    const lon1 = center.lon * Math.PI / 180;
    const out = [];
    for (let deg = 0; deg <= 360; deg += 5) {
      const b = deg * Math.PI / 180;
      const lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(b));
      const lon2 = lon1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(lat1), Math.cos(d) - Math.sin(lat1) * Math.sin(lat2));
      out.push({ lat: lat2 * 180 / Math.PI, lon: lon2 * 180 / Math.PI });
    }
    return out;
  }

  /* A layer's key in the list: the same shape, on a small canvas. */
  function swatch(layerId) {
    const c = document.createElement("canvas");
    c.width = 16;
    c.height = 16;
    c.className = "swatch";
    c.setAttribute("aria-hidden", "true");
    const ctx = c.getContext("2d");
    const s = style(layerId, { weight: 0.5, severity: layerId === "gdacs" ? "Orange" : "M4.0" });
    shape(ctx, s.shape, 8, 8, Math.min(s.shape === "speck" ? 4 : s.r, 6), s.color);
    return c;
  }

  return { CDMX, CDMX_RINGS_KM, PIN_MAG, CLUSTER_PX, CLUSTER_MIN, style, clusters, shape, teardrop, label, group, cluster,
    ring, swatch, magnitude, level };
})();
