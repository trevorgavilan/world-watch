/* The Middle East live streams' player, shared by the Board's viewer (viewer.js) and the console (live.js).
   D-24: a stream plays only in YouTube's privacy-enhanced player (youtube-nocookie.com), in a sandboxed
   frame of another origin — its scripts can't reach this page, and it can't navigate it. The page CSP
   frames that one origin and nothing else. A frame is made only after a click. The embed address is
   built here from a strict match of the stream's YouTube link, never taken from the data as is. */
"use strict";

window.WWPlayer = (() => {
  const ORIGIN = "https://www.youtube-nocookie.com";
  const VIDEO = /^https:\/\/www\.youtube\.com\/watch\?v=([A-Za-z0-9_-]{11})$/;
  const CHANNEL = /^https:\/\/www\.youtube\.com\/channel\/(UC[A-Za-z0-9_-]{22})\/live$/;
  const SANDBOX = "allow-scripts allow-same-origin allow-presentation allow-popups allow-popups-to-escape-sandbox";

  /* The player address for a stream, or null when its link is not one of the two YouTube shapes. */
  function embedUrl(entry, autoplay) {
    const url = entry && typeof entry.url === "string" ? entry.url : "";
    const play = "autoplay=" + (autoplay ? "1" : "0") + "&mute=1&playsinline=1&rel=0";
    let m = VIDEO.exec(url);
    if (m) return ORIGIN + "/embed/" + m[1] + "?" + play;
    m = CHANNEL.exec(url);
    if (m) return ORIGIN + "/embed/live_stream?channel=" + m[1] + "&" + play;
    return null;
  }

  /* YouTube needs to be told which site embeds it (the Board sends no Referer otherwise): the
     frame alone sends this server's origin (127.0.0.1 and the port), and nothing more. */
  function frame(entry, autoplay) {
    const src = embedUrl(entry, autoplay);
    if (!src) return null;
    const f = document.createElement("iframe");
    f.className = "player";
    f.title = String(entry.title || "Live stream");
    f.setAttribute("sandbox", SANDBOX);
    f.setAttribute("allow", "autoplay; encrypted-media; picture-in-picture; fullscreen");
    f.setAttribute("allowfullscreen", "");
    f.referrerPolicy = "strict-origin";
    f.loading = "eager";
    f.src = src;
    return f;
  }

  /* The stream's YouTube link, only when it is one of the two shapes above: the one link the viewer
     and the console ever set. */
  function watchUrl(entry) {
    const url = entry && typeof entry.url === "string" ? entry.url : "";
    return VIDEO.test(url) || CHANNEL.test(url) ? url : null;
  }

  /* The kind is the item's severity: "cam" or "news", with " · not verified" when we can't vouch for it. */
  function isCam(entry) {
    return !!entry && typeof entry.severity === "string" && entry.severity.startsWith("cam");
  }

  function isVerified(entry) {
    return !!entry && (entry.severity === "cam" || entry.severity === "news");
  }

  function kindText(entry) {
    return (isCam(entry) ? "Live cam" : "Live news") + (isVerified(entry) ? "" : " · NOT VERIFIED");
  }

  /* Official streams first (cams, then news), then the not verified ones; each by name. Streams with no
     playable link are left out. */
  function rank(e) {
    return (isVerified(e) ? 0 : 2) + (isCam(e) ? 0 : 1);
  }

  function order(entries) {
    return (Array.isArray(entries) ? entries : [])
      .filter((e) => e && typeof e.id === "string" && embedUrl(e, false))
      .slice()
      .sort((a, b) => rank(a) - rank(b) || String(a.title).localeCompare(String(b.title)));
  }

  /* "Live cam · Western Wall Heritage Foundation · Jerusalem." — the owner line is the summary's head. */
  function owner(entry) {
    const summary = typeof entry.summary === "string" ? entry.summary : "";
    const cut = summary.indexOf(". ");
    return cut > 0 ? summary.slice(0, cut) : summary.replace(/\.$/, "");
  }

  return { ORIGIN, SANDBOX, embedUrl, watchUrl, frame, isCam, isVerified, kindText, order, owner };
})();
