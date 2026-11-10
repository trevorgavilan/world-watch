/* The Board's Middle East live viewer: one stream at a time, arrows to step through them, and a
   button that opens the console (/live) with several at once in a new tab (Trevor, 2026-11-09).
   It lives outside the lists the Board rebuilds every minute, so a refresh never reloads the player:
   update() only swaps the list, and the frame changes only when the stream on screen does.
   Nothing reaches YouTube until "Play" is pressed (D-24); after that the arrows switch streams. */
"use strict";

window.WWViewer = (() => {
  const KEY = "ww.board.live";  // the stream last on screen, kept in this browser

  function remember(value) {
    try {
      localStorage.setItem(KEY, value);
    } catch (_) { /* not kept */ }
  }

  function recall() {
    try {
      return localStorage.getItem(KEY);
    } catch (_) {
      return null;
    }
  }

  function create(ids, meta) {
    const $ = (id) => document.getElementById(id);
    const box = $(ids.box);
    const stage = $(ids.stage);
    const P = window.WWPlayer;
    const v = { entries: [], current: recall(), playing: false, shownId: null };

    function at() {
      const i = v.entries.findIndex((e) => e.id === v.current);
      return i >= 0 ? i : 0;
    }

    function entry() {
      return v.entries.length ? v.entries[at()] : null;
    }

    function cover() {  // before the first play: text only, nothing fetched from outside
      const play = document.createElement("button");
      play.type = "button";
      play.className = "live-play";
      play.dataset.key = "live:play";
      play.textContent = "▶ Play";
      play.addEventListener("click", () => {
        v.playing = true;
        v.shownId = null;
        draw(true);
      });
      const note = document.createElement("p");
      note.className = "live-note";
      note.textContent = "Plays from YouTube (privacy-enhanced mode): Google sees your address and what you watch.";
      stage.replaceChildren(play, note);
    }

    function draw(autoplay) {
      const e = entry();
      box.hidden = !e;
      if (!e) {
        stage.replaceChildren();
        v.shownId = null;
        return;
      }
      v.current = e.id;
      $(ids.count).textContent = (at() + 1) + " / " + v.entries.length;
      const title = $(ids.title);
      title.replaceChildren();
      const href = P.watchUrl(e);
      const a = document.createElement(href ? "a" : "span");
      a.textContent = e.title;
      if (href) {
        a.href = P.watchUrl(e);
        a.rel = "noopener noreferrer";
        a.target = "_blank";
      }
      title.append(a);
      $(ids.meta).textContent = meta(e);
      if (!v.playing) {
        if (v.shownId !== "cover") cover();
        v.shownId = "cover";
        return;
      }
      if (v.shownId === e.id) return;  // the same stream: keep its frame playing
      const f = P.frame(e, autoplay);
      stage.replaceChildren(...(f ? [f] : []));
      v.shownId = e.id;
    }

    function step(by) {
      if (!v.entries.length) return;
      const n = v.entries.length;
      v.current = v.entries[(at() + by + n) % n].id;
      remember(v.current);
      draw(true);
    }

    function show(id) {
      if (!v.entries.some((e) => e.id === id)) return;
      v.current = id;
      remember(id);
      draw(true);
    }

    function update(entries) {
      v.entries = P.order(entries);
      draw(false);  // a refresh never starts a stream by itself
    }

    function openConsole() {
      const e = entry();
      window.open("/live" + (e ? "#" + encodeURIComponent(e.id) : ""), "_blank", "noopener");
    }

    $(ids.prev).addEventListener("click", () => step(-1));
    $(ids.next).addEventListener("click", () => step(1));
    $(ids.console).addEventListener("click", openConsole);
    box.addEventListener("keydown", (e) => {
      if (e.target && e.target.tagName === "IFRAME") return;
      if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "ArrowRight") step(1);
    });
    const api = { update, show, step, state: v };
    window.WWViewer.current = api;  // for the browser tests, as WWMap.current
    return api;
  }

  return { create, current: null };
})();
