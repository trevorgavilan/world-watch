/* World Watch Board — the flat world map: the vendored blue-marble image (equirectangular, D-17: no
   tiles from the internet), darkened, on one canvas, with each layer's points drawn by WWPins.
   Wheel or the +/- buttons zoom, dragging pans, a click on a pin selects it, a click on a fire cluster
   zooms into it. The hover tip is set with textContent only. */
"use strict";

window.WWMap = (() => {
  const P = window.WWPins;
  const MAX_ZOOM = 48;          // times the whole-world scale
  const SPLIT_ZOOM = 24;        // from here on, fires never merge
  const KEY_PAN = 60;           // px per arrow key
  const MOVE_PX = 4;            // a press that moves less is a click
  const AREAS = {
    world: { west: -180, east: 180, south: -90, north: 90 },
    mexico: { west: -118.5, east: -86, south: 14, north: 33 },
  };

  function valid(p) {
    return Number.isFinite(p.lat) && Number.isFinite(p.lon) && Math.abs(p.lat) <= 90 && Math.abs(p.lon) <= 180;
  }

  function create(box, onPick) {
    const canvas = document.createElement("canvas");
    canvas.className = "map-canvas";
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", "Flat world map. Arrow keys pan, + and - zoom, 0 shows the whole world.");
    const tip = document.createElement("div");
    tip.className = "tip";
    tip.hidden = true;
    box.append(canvas, tip);
    const ctx = canvas.getContext("2d");

    const v = { s: 1, ox: 0, oy: 0, w: 0, h: 0, dpr: 1 };  // px per degree; where lon -180 / lat 90 sits on screen
    let layers = [];      // [{ id, points }] in the order to draw, shown ones only
    let alerts = [];      // the near-CDMX panel's entries
    let marks = [];       // what the last frame drew, for hover and click, top-most last
    let base = null;
    let queued = false;
    let drag = null;
    let fitted = false;
    let pointer = null;   // where the mouse rests, so the tip follows a zoom or a refresh

    const toX = (lon) => v.ox + (lon + 180) * v.s;
    const toY = (lat) => v.oy + (90 - lat) * v.s;
    const lonAt = (x) => (x - v.ox) / v.s - 180;
    const latAt = (y) => 90 - (y - v.oy) / v.s;
    const minScale = () => Math.min(v.w / 360, v.h / 180);

    function clamp() {
      v.s = Math.min(Math.max(v.s, minScale()), minScale() * MAX_ZOOM);
      const W = 360 * v.s;
      const H = 180 * v.s;
      v.ox = W <= v.w ? (v.w - W) / 2 : Math.min(0, Math.max(v.w - W, v.ox));
      v.oy = H <= v.h ? (v.h - H) / 2 : Math.min(0, Math.max(v.h - H, v.oy));
    }

    function centre(lon, lat, s) {
      v.s = s;
      v.ox = v.w / 2 - (lon + 180) * s;
      v.oy = v.h / 2 - (90 - lat) * s;
      clamp();
      redraw();
    }

    function show(name) {
      const a = AREAS[name];
      if (!a || !v.w) return;
      centre((a.west + a.east) / 2, (a.south + a.north) / 2,
        Math.min(v.w / (a.east - a.west), v.h / (a.north - a.south)));
    }

    function zoomAt(factor, x, y) {
      const lon = lonAt(x);
      const lat = latAt(y);
      v.s *= factor;
      clamp();
      v.ox = x - (lon + 180) * v.s;
      v.oy = y - (90 - lat) * v.s;
      clamp();
      redraw();
    }

    function resize() {
      const w = box.clientWidth;
      const h = box.clientHeight;
      if (!w || !h) return;  // hidden behind the globe
      const keep = fitted ? { lon: lonAt(v.w / 2), lat: latAt(v.h / 2), zoom: v.s / minScale() } : null;
      v.dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(w * v.dpr);
      canvas.height = Math.round(h * v.dpr);
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      v.w = w;
      v.h = h;
      if (keep) {
        centre(keep.lon, keep.lat, keep.zoom * minScale());
      } else {
        fitted = true;
        show("world");
      }
      draw();  // now, not next frame: setting the size just blanked the canvas
    }

    /* A move to a screen with another scaling changes no size, so the observer never hears of it. */
    function watchScaling() {
      const query = window.matchMedia("(resolution: " + (window.devicePixelRatio || 1) + "dppx)");
      query.addEventListener("change", () => {
        resize();
        watchScaling();
      }, { once: true });
    }

    function drawBase() {
      ctx.fillStyle = "#05070b";
      ctx.fillRect(0, 0, v.w, v.h);
      const x0 = toX(-180);
      const y0 = toY(90);
      const W = 360 * v.s;
      const H = 180 * v.s;
      const ix0 = Math.max(0, x0);
      const iy0 = Math.max(0, y0);
      const ix1 = Math.min(v.w, x0 + W);
      const iy1 = Math.min(v.h, y0 + H);
      if (base && ix1 > ix0 && iy1 > iy0) {
        const kx = base.width / W;
        const ky = base.height / H;
        ctx.drawImage(base, (ix0 - x0) * kx, (iy0 - y0) * ky, (ix1 - ix0) * kx, (iy1 - iy0) * ky,
          ix0, iy0, ix1 - ix0, iy1 - iy0);
      } else {
        ctx.fillStyle = "#0b1622";
        ctx.fillRect(x0, y0, W, H);
      }
      ctx.lineWidth = 1;
      for (let lon = -150; lon <= 150; lon += 30) {
        ctx.strokeStyle = lon === 0 ? "rgba(223, 230, 238, 0.14)" : "rgba(223, 230, 238, 0.07)";
        ctx.beginPath();
        ctx.moveTo(toX(lon), y0);
        ctx.lineTo(toX(lon), y0 + H);
        ctx.stroke();
      }
      for (let lat = -60; lat <= 60; lat += 30) {
        ctx.strokeStyle = lat === 0 ? "rgba(223, 230, 238, 0.14)" : "rgba(223, 230, 238, 0.07)";
        ctx.beginPath();
        ctx.moveTo(x0, toY(lat));
        ctx.lineTo(x0 + W, toY(lat));
        ctx.stroke();
      }
    }

    function drawRings() {
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      for (const km of P.CDMX_RINGS_KM) {
        const pts = P.ring(P.CDMX, km);
        ctx.strokeStyle = alerts.length ? "rgba(248, 81, 73, 0.45)" : "rgba(223, 230, 238, 0.28)";
        ctx.beginPath();
        pts.forEach((p, i) => (i ? ctx.lineTo(toX(p.lon), toY(p.lat)) : ctx.moveTo(toX(p.lon), toY(p.lat))));
        ctx.stroke();
        const top = pts[0];
        if (toY(P.CDMX.lat) - toY(top.lat) > 28) {
          ctx.font = "10px system-ui, 'Segoe UI', sans-serif";
          ctx.fillStyle = "rgba(223, 230, 238, 0.55)";
          ctx.textAlign = "center";
          ctx.fillText(km + " km", toX(top.lon), toY(top.lat) - 3);
          ctx.textAlign = "start";
        }
      }
      ctx.setLineDash([]);
    }

    function drawCdmx() {
      const x = toX(P.CDMX.lon);
      const y = toY(P.CDMX.lat);
      const on = alerts.length > 0;
      P.shape(ctx, "diamond", x, y, on ? 7 : 5, on ? "#f85149" : "#dfe6ee");
      P.label(ctx, on ? "CDMX · " + alerts.length + (alerts.length === 1 ? " alert" : " alerts") : "CDMX", x + 9, y);
      marks.push({ kind: "cdmx", layer: "near-cdmx", x, y, r: 9, point: on ? alerts[0] : null, n: alerts.length });
    }

    function draw() {
      queued = false;
      if (!v.w) return;
      if ((window.devicePixelRatio || 1) !== v.dpr) {  // the scaling changed under us: size the canvas again
        resize();
        return;
      }
      ctx.setTransform(v.dpr, 0, 0, v.dpr, 0, 0);
      drawBase();
      marks = [];
      drawRings();
      const pins = [];
      const margin = 30;
      const merge = v.s < minScale() * SPLIT_ZOOM;
      for (const layer of layers) {
        const placed = [];
        for (const point of layer.points) {
          if (!valid(point)) continue;
          const x = toX(point.lon);
          const y = toY(point.lat);
          if (x < -margin || y < -margin || x > v.w + margin || y > v.h + margin) continue;
          placed.push({ x, y, point, style: P.style(layer.id, point) });
        }
        placed.sort((a, b) => (a.point.weight || 0) - (b.point.weight || 0));  // the biggest on top
        for (const m of P.group(placed, merge && P.clusters(layer.id))) {
          if (m.members.length > 1) {
            const r = P.cluster(ctx, m.x, m.y, m.members.length);
            marks.push({ kind: "cluster", layer: layer.id, x: m.x, y: m.y, r, n: m.members.length, members: m.members });
            continue;
          }
          P.shape(ctx, m.style.shape, m.x, m.y, m.style.r, m.style.color);
          marks.push({ kind: m.style.shape, layer: layer.id, x: m.x, y: m.y, r: Math.max(m.style.r, 4), point: m.point });
          if (m.style.pin) pins.push({ ...m, layer: layer.id });
        }
      }
      drawCdmx();
      for (const m of pins) {
        const head = P.teardrop(ctx, m.x, m.y, m.style.color);
        if (m.style.label) P.label(ctx, m.style.label, head.x + 10, head.y);
        marks.push({ kind: "pin", layer: m.layer, x: head.x, y: head.y, r: head.r, point: m.point,
          label: m.style.label });
      }
      if (pointer && !drag) showTip(hit(pointer.x, pointer.y), pointer.x, pointer.y);
    }

    function redraw() {
      if (queued) return;
      queued = true;
      requestAnimationFrame(draw);
    }

    function hit(x, y) {
      for (let i = marks.length - 1; i >= 0; i -= 1) {
        const m = marks[i];
        if ((m.x - x) ** 2 + (m.y - y) ** 2 <= (m.r + 3) ** 2) return m;
      }
      return null;
    }

    function tipText(m) {
      if (m.kind === "cluster") return m.n + " fire detections here: click to zoom in";
      if (m.kind === "cdmx") {
        return m.n ? "CDMX: " + m.n + " quake alert(s) in the near-CDMX list. Latest: " + m.point.title
          : "CDMX: no quake alert in the near-CDMX list. Rings: 150, 400, 700, 1,200 km";
      }
      return m.point.title + (m.point.severity ? " · " + m.point.severity : "");
    }

    function showTip(m, x, y) {
      if (!m) {
        tip.hidden = true;
        canvas.classList.remove("over");
        return;
      }
      tip.textContent = tipText(m);
      tip.hidden = false;
      canvas.classList.add("over");
      const left = Math.min(x + 14, v.w - tip.offsetWidth - 4);
      tip.style.left = Math.max(4, left) + "px";
      tip.style.top = Math.max(4, y + 14 + tip.offsetHeight > v.h ? y - tip.offsetHeight - 10 : y + 14) + "px";
    }

    function click(m) {
      if (!m) return;
      if (m.kind === "cluster") {
        centre(lonAt(m.x), latAt(m.y), v.s * 4);
        return;
      }
      if (m.point) onPick(m.point);
    }

    function where(e) {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }

    canvas.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      const p = where(e);
      drag = { x: p.x, y: p.y, ox: v.ox, oy: v.oy, moved: false };
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", (e) => {
      const p = where(e);
      pointer = p;
      if (!drag) {
        showTip(hit(p.x, p.y), p.x, p.y);
        return;
      }
      if (Math.abs(p.x - drag.x) + Math.abs(p.y - drag.y) > MOVE_PX) drag.moved = true;
      if (!drag.moved) return;
      showTip(null);
      canvas.classList.add("dragging");
      v.ox = drag.ox + p.x - drag.x;
      v.oy = drag.oy + p.y - drag.y;
      clamp();
      redraw();
    });
    const end = (e) => {
      if (!drag) return;
      const wasClick = !drag.moved && e.type === "pointerup";
      drag = null;
      canvas.classList.remove("dragging");
      if (wasClick) {
        const p = where(e);
        click(hit(p.x, p.y));
      }
    };
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);
    canvas.addEventListener("lostpointercapture", end);  // never left panning on a plain mouse move
    canvas.addEventListener("pointerleave", () => {
      pointer = null;
      if (!drag) showTip(null);
    });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      if (!e.deltaY) return;  // a sideways swipe is not a zoom
      const p = where(e);
      const px = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;  // lines, not pixels
      zoomAt(Math.min(Math.max(Math.pow(1.25, -px / 100), 0.5), 2), p.x, p.y);  // a notch is 1.25x; a pinch is gentle
    }, { passive: false });
    canvas.addEventListener("dblclick", (e) => {
      const p = where(e);
      zoomAt(2, p.x, p.y);
    });
    canvas.addEventListener("keydown", (e) => {
      const pan = { ArrowLeft: [KEY_PAN, 0], ArrowRight: [-KEY_PAN, 0], ArrowUp: [0, KEY_PAN], ArrowDown: [0, -KEY_PAN] }[e.key];
      if (pan) {
        v.ox += pan[0];
        v.oy += pan[1];
        clamp();
        redraw();
      } else if (e.key === "+" || e.key === "=") {
        zoomAt(1.5, v.w / 2, v.h / 2);
      } else if (e.key === "-") {
        zoomAt(1 / 1.5, v.w / 2, v.h / 2);
      } else if (e.key === "0" || e.key === "Home") {
        show("world");
      } else {
        return;
      }
      e.preventDefault();
    });

    /* Its own function, so the decoded image is let go once its dimmed copy is made. */
    function loadBase() {
      const img = new Image();
      img.addEventListener("load", () => {
        const c = document.createElement("canvas");
        c.width = img.naturalWidth;
        c.height = img.naturalHeight;
        const g = c.getContext("2d");
        g.filter = "brightness(0.62) saturate(0.75)";  // dimmed, so the pins carry the colour
        g.drawImage(img, 0, 0);
        base = c;
        canvas.dataset.base = "loaded";
        redraw();
      });
      img.src = "/static/earth.jpg";
    }

    loadBase();
    new ResizeObserver(resize).observe(box);  // the window, the divider, or coming back from the globe
    watchScaling();
    resize();

    const api = {
      setLayers(list) {
        layers = list.map((l) => ({ id: l.id, points: Array.isArray(l.points) ? l.points : [] }));
        redraw();
      },
      setAlerts(list) {
        alerts = Array.isArray(list) ? list : [];
        redraw();
      },
      show,
      zoom(factor) {
        zoomAt(factor, v.w / 2, v.h / 2);
      },
      /* For the tests and for debugging: what the last frame drew, and where a place lands. */
      marks: () => marks.map((m) => ({ kind: m.kind, layer: m.layer, x: m.x, y: m.y, n: typeof m.n === "number" ? m.n : 1,
        id: m.point ? m.point.id : null, label: m.label || null })),
      at: (lat, lon) => ({ x: toX(lon), y: toY(lat) }),
      view: () => ({ s: v.s, min: minScale(), max: minScale() * MAX_ZOOM, w: v.w, h: v.h }),
    };
    window.WWMap.current = api;
    return api;
  }

  return { create, AREAS, MAX_ZOOM, SPLIT_ZOOM };
})();
