/* World Watch Board — the pop-up card for a picked pin: everything we hold about the item, the full
   record read from /api/items/<id>. Text is set with textContent only, and every link comes from
   board.js's link(), which re-checks it (D-17); this file never makes a link itself.
   On the map the card follows its pin through zooms and pans; on the globe it docks in a corner. */
"use strict";

window.WWPopup = (() => {
  const GAP = 14;     // px between the pin and the card
  const EDGE = 8;     // px kept clear of the stage's edges
  const TOP = 52;     // under the view buttons
  const BASIS = {
    reported: "Reported by the source",
    inferred: "Worked out by World Watch from the source's data",
  };

  function clamp(n, lo, hi) {
    return Math.max(lo, Math.min(n, Math.max(lo, hi)));
  }

  /* card: the dialog; body: where the content goes; tools: board.js's helpers. */
  function create(card, body, tools) {
    const { el, link, line, when, ago } = tools;
    let current = null;  // the picked point
    let anchor = null;   // the pin's place on the stage, or null when docked

    function where(point, detail) {
      if (!Number.isFinite(point.lat) || !Number.isFinite(point.lon)) return null;
      const country = detail && detail.country ? " · " + detail.country : "";
      return point.lat.toFixed(3) + ", " + point.lon.toFixed(3) + country;
    }

    function record(fields) {
      const box = el("details", null, "record");
      box.append(el("summary", "Every field the source sent (" + fields.length + ")"));
      const list = el("dl");
      for (const pair of fields) {
        if (!Array.isArray(pair) || pair.length !== 2) continue;
        list.append(el("dt", pair[0]), el("dd", pair[1]));
      }
      box.append(list);
      return box;
    }

    /* detail: undefined while loading, null when it could not be read, else the item's full record. */
    function draw(point, detail) {
      const title = el("p", null, "title");
      title.append(link(point.title, point.url));
      const kind = [detail && detail.kind, point.severity].filter(Boolean).join(" · ");
      const parts = [title];
      if (kind) parts.push(el("p", kind, "kind"));
      if (detail && detail.summary && detail.summary !== point.title) parts.push(el("p", detail.summary, "text"));
      parts.push(
        line("Happened:", when(point.happened_at, false)),
        line("Fetched:", when(point.fetched_at, false) + " (" + ago(point.fetched_at) + ")"),
      );
      const place = where(point, detail);
      if (place) parts.push(line("Where:", place));
      if (detail) {
        parts.push(line("Basis:", BASIS[detail.basis] || "?"), line("Licence:", detail.licence || "?"));
      }
      parts.push(line("Source:", (detail && detail.credit) || point.source));
      const links = el("p", null, "links");
      if (point.url) links.append(link("More details at the source ↗", point.url));
      if (detail && detail.credit_url) links.append(link("About this source ↗", detail.credit_url));
      if (links.childNodes.length) parts.push(links);
      if (detail === undefined) parts.push(el("p", "Reading the full record…", "meta"));
      else if (detail === null) parts.push(el("p", "The full record could not be read.", "meta"));
      else if (Array.isArray(detail.record) && detail.record.length) parts.push(record(detail.record));
      body.replaceChildren(...parts);
      position();
    }

    function position() {
      if (!current) return;
      const stage = card.parentElement;
      const W = stage.clientWidth;
      const H = stage.clientHeight;
      const w = card.offsetWidth;
      const h = card.offsetHeight;
      if (!anchor) {  // docked: the top right corner
        card.style.left = clamp(W - w - EDGE, EDGE, W) + "px";
        card.style.top = TOP + "px";
        return;
      }
      let left = anchor.x + GAP;
      if (left + w > W - EDGE) left = anchor.x - GAP - w;  // no room on the right: the pin's left
      card.style.left = clamp(left, EDGE, W - w - EDGE) + "px";
      card.style.top = clamp(anchor.y - 24, TOP, H - h - EDGE) + "px";
    }

    const api = {
      open(point) {
        current = point;
        anchor = null;
        card.hidden = false;
        card.scrollTop = 0;
        draw(point, undefined);
        tools.fetchDetail(point.id).then(
          (detail) => { if (current === point) draw(point, detail); },
          () => { if (current === point) draw(point, null); },
        );
      },
      /* x, y on the stage; seen: false while the pin is panned off the map. */
      place(x, y, seen) {
        if (!current) return;
        card.hidden = !seen;
        if (!seen) return;
        anchor = { x, y };
        position();
      },
      dock() {
        anchor = null;
        if (current) {
          card.hidden = false;
          position();
        }
      },
      close() {
        if (!current) return;
        current = null;
        card.hidden = true;
        body.replaceChildren();
        tools.onClose();
      },
      isOpen: () => current !== null,
    };
    window.WWPopup.current = api;
    return api;
  }

  return { create };
})();
