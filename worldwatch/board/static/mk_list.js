/* The markets terminal: the starred strip across the top and the list on the left (tabs by group,
   ★ for the starred ones). A row flashes once when its number changed since the last refresh. */
"use strict";

(() => {
  const W = window.WWM;
  const { el, $ } = W;
  const SVG = "http://www.w3.org/2000/svg";
  const STARRED = "starred";
  let shownIds = [];

  function mini(history) {
    const values = (history || []).map((p) => Number(p[1])).filter(Number.isFinite).slice(-40);
    if (values.length < 2) return el("span");
    const min = Math.min(...values);
    const span = Math.max(...values) - min || 1;
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("class", "mini");
    svg.setAttribute("viewBox", "0 0 100 20");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("aria-hidden", "true");
    const line = document.createElementNS(SVG, "polyline");
    line.setAttribute("points", values.map((v, i) =>
      `${(i / (values.length - 1) * 100).toFixed(1)},${(18 - (v - min) / span * 16).toFixed(1)}`).join(" "));
    svg.append(line);
    return svg;
  }

  function star(id) {
    const b = el("button", W.starred(id) ? "★" : "☆", "star");
    b.type = "button";
    b.setAttribute("aria-pressed", String(W.starred(id)));
    b.setAttribute("aria-label", (W.starred(id) ? "Unstar " : "Star ") + (W.state.items[id] || {}).en);
    b.addEventListener("click", (e) => { e.stopPropagation(); W.toggleStar(id); });
    return b;
  }

  function row(item, state) {
    const li = el("li", null, "row");
    li.dataset.id = item.id;
    li.setAttribute("role", "option");
    li.setAttribute("aria-selected", String(state.prefs.pick === item.id));
    const value = item.latest ? W.grouped(item.latest.value) : "—";
    li.append(star(item.id), el("span", item.en, "label"), el("span", value, "value"));
    const chg = el("span", null, "chg");
    const c = W.change(item);
    chg.append(el("span", c.text, c.dir), mini(item.history));
    li.append(chg);
    li.addEventListener("click", () => W.pick(item.id));
    const before = state.prev[item.id];
    if (before !== undefined && item.latest && before !== item.latest.value) {
      li.classList.add("flash");
      setTimeout(() => li.classList.remove("flash"), 60);
    }
    return li;
  }

  function tabs(state) {
    const host = $("list-tabs");
    host.replaceChildren();
    const groups = [{ id: STARRED, en: "★ Starred" }].concat((state.body.groups || []).map((g) => ({ id: g.id, en: g.en.split(",")[0] })));
    if (!groups.some((g) => g.id === state.prefs.tab)) state.prefs.tab = groups[1] ? groups[1].id : STARRED;
    for (const g of groups) {
      const b = el("button", g.en);
      b.type = "button";
      b.setAttribute("role", "tab");
      b.dataset.tab = g.id;
      b.setAttribute("aria-selected", String(state.prefs.tab === g.id));
      b.addEventListener("click", () => W.setPref("tab", g.id));
      host.append(b);
    }
  }

  function strip(state) {
    const host = $("strip");
    host.replaceChildren();
    for (const id of state.prefs.stars) {
      const item = state.items[id];
      if (!item || !item.latest) continue;
      const li = el("li");
      const b = el("button");
      b.type = "button";
      b.dataset.id = id;
      const c = W.change(item);
      b.append(el("span", item.en, "name"), el("span", W.grouped(item.latest.value) + " ", "num"), el("span", c.text, c.dir + " num"));
      b.addEventListener("click", () => W.pick(id));
      li.append(b);
      host.append(li);
    }
  }

  function draw(state) {
    tabs(state);
    strip(state);
    const tab = state.prefs.tab;
    shownIds = tab === STARRED ? state.prefs.stars.filter((id) => state.items[id])
      : state.order.filter((id) => state.items[id].group === tab);
    const host = $("list");
    host.replaceChildren();
    if (!shownIds.length) {
      host.append(el("li", tab === STARRED ? "Star a number with ☆ to keep it here." : "Nothing in this group yet.", "empty"));
      return;
    }
    shownIds.forEach((id) => host.append(row(state.items[id], state)));
    const picked = host.querySelector('[aria-selected="true"]');
    if (picked && picked.scrollIntoView) picked.scrollIntoView({ block: "nearest" });
  }

  W.list = { shown: () => shownIds.slice() };
  W.register({ draw });
})();
