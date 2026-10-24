"""Recon as one self-contained HTML page: one column, large type, collapsible
sections, light and dark, an EN/ES toggle. No outside requests, and a CSP that
allows only the page's own inline style and its one hashed script.
Every source string is escaped here, even though the adapters already cleaned it.
"""

from __future__ import annotations

import base64
import hashlib
from html import escape

from .recon import CREDITS, Group, Recon, Section, local, show_event, show_time

CSS = """
:root { color-scheme: light dark;
  --bg: #f7f6f2; --fg: #1d1d1b; --muted: #5d5b55; --line: #dcd9d0; --card: #ffffff;
  --accent: #1f5f8b; --warn-bg: #fff1d6; --warn-fg: #6b4300; --badge: #e9e6dd; }
@media (prefers-color-scheme: dark) { :root {
  --bg: #121212; --fg: #ecebe6; --muted: #a9a69d; --line: #2e2d2a; --card: #1b1b1a;
  --accent: #8cc4ec; --warn-bg: #3a2c0c; --warn-fg: #f5d48a; --badge: #2b2a27; } }
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 18px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 42rem; margin: 0 auto; padding: 16px 16px 48px; }
header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
h1 { font-size: 1.6rem; line-height: 1.2; margin: 8px 0 4px; }
h3 { font-size: 1rem; margin: 16px 0 6px; color: var(--muted); }
.when { color: var(--muted); margin: 0 0 12px; font-size: 0.9rem; }
#lang-toggle { min-height: 44px; min-width: 56px; font: inherit; font-weight: 600; border-radius: 10px;
  border: 1px solid var(--line); background: var(--card); color: var(--fg); cursor: pointer; }
.warn { background: var(--warn-bg); color: var(--warn-fg); border-radius: 10px; padding: 10px 12px; margin: 8px 0 16px; }
details.section { background: var(--card); border: 1px solid var(--line); border-radius: 12px; margin: 12px 0; padding: 0 14px 8px; }
details > summary { min-height: 44px; display: flex; align-items: center; cursor: pointer;
  font-weight: 650; font-size: 1.1rem; list-style-position: inside; }
details.news { border-top: 1px solid var(--line); }
details.news > summary { font-size: 1rem; color: var(--muted); }
ul { list-style: none; padding: 0; margin: 0; }
li.item { padding: 10px 0; border-top: 1px solid var(--line); }
li.item:first-child { border-top: 0; }
a { color: var(--accent); }
.title { font-weight: 550; overflow-wrap: anywhere; }
a.title { display: inline-block; min-height: 44px; padding: 2px 0; text-decoration-thickness: 1px; }
.meta { color: var(--muted); font-size: 0.85rem; overflow-wrap: anywhere; }
.badge { background: var(--badge); border-radius: 6px; padding: 0 6px; font-weight: 600; color: var(--fg); }
.summary { margin: 4px 0 0; font-size: 0.95rem; overflow-wrap: anywhere; }
.empty { color: var(--muted); padding: 6px 0; }
.stale { color: var(--warn-fg); background: var(--warn-bg); border-radius: 6px; padding: 0 6px; font-weight: 600; }
footer { color: var(--muted); font-size: 0.85rem; margin-top: 20px; overflow-wrap: anywhere; }
footer a, .warn a { display: inline-flex; align-items: center; min-height: 44px; }
html[data-lang="en"] .i18n[lang="es"], html[data-lang="es"] .i18n[lang="en"] { display: none; }
"""

SCRIPT = (
    "(function(){var root=document.documentElement,btn=document.getElementById('lang-toggle');"
    "function set(l){root.setAttribute('data-lang',l);btn.textContent=l==='en'?'ES':'EN';"
    "btn.setAttribute('aria-label',l==='en'?'Cambiar a espa\\u00f1ol':'Switch to English');"
    "var lists=document.querySelectorAll('[data-news-lang]');"
    "for(var i=0;i<lists.length;i++){lists[i].open=lists[i].getAttribute('data-news-lang')===l;}"
    "try{localStorage.setItem('ww-lang',l);}catch(e){}}"
    "var saved=null;try{saved=localStorage.getItem('ww-lang');}catch(e){}"
    "set(saved==='es'?'es':'en');"
    "btn.addEventListener('click',function(){set(root.getAttribute('data-lang')==='en'?'es':'en');});})();"
)


def _hash(script: str) -> str:
    return base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")


CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; "
    f"script-src 'sha256-{_hash(SCRIPT)}'; base-uri 'none'; form-action 'none'"
)


def t(en: str, es: str) -> str:
    return f'<span class="i18n" lang="en">{escape(en)}</span><span class="i18n" lang="es">{escape(es)}</span>'


def _item(row) -> str:
    title = escape(row["title"])
    if row["url"]:
        head = f'<a class="title" href="{escape(row["url"])}" target="_blank" rel="noopener noreferrer">{title}</a>'
    else:
        head = f'<span class="title">{title}</span>'
    meta = []
    if row["severity"]:
        meta.append(f'<span class="badge">{escape(row["severity"])}</span>')
    meta.append(escape(row["source"]))
    meta.append(f'{t("event", "evento")} {escape(show_event(row))}')
    meta.append(f'{t("fetched", "obtenido")} {escape(show_time(row["fetched_at"]))}')
    meta.append(t("reported", "reportado") if row["basis"] == "reported" else t("inferred", "inferido"))
    summary = f'<p class="summary">{escape(row["summary"])}</p>' if row["summary"] else ""
    return f'<li class="item">{head}<div class="meta">{" · ".join(meta)}</div>{summary}</li>'


def _rows(rows) -> str:
    if not rows:
        return f'<p class="empty">{t("Nothing yet.", "Nada todavía.")}</p>'
    return "<ul>" + "".join(_item(r) for r in rows) + "</ul>"


def _group(group: Group) -> str:
    if group.news_lang:
        return (f'<details class="news" data-news-lang="{group.news_lang}" open>'
                f"<summary>{t(group.en, group.es)}</summary>{_rows(group.rows)}</details>")
    return f"<h3>{t(group.en, group.es)}</h3>{_rows(group.rows)}"


def _section(section: Section) -> str:
    body = "".join(_group(g) for g in section.groups)
    return (f'<details class="section" id="{section.key}" open>'
            f"<summary>{t(section.en, section.es)}</summary>{body}</details>")


def _sources(recon: Recon) -> str:
    lines = []
    for s in recon.sources:
        when = escape(show_time(s.last_ok.strftime("%Y-%m-%dT%H:%M:%SZ"))) if s.last_ok else t("never", "nunca")
        flag = f' <span class="stale">{t("stale", "atrasada")}</span>' if s.stale else ""
        error = f'<div class="meta">{t("last error", "último error")}: {escape(s.error)}</div>' if s.error else ""
        lines.append(f'<li class="item"><span class="title">{escape(s.source)}</span>'
                     f'<div class="meta">{t("last success", "último éxito")}: {when}{flag}</div>{error}</li>')
    credits = "".join(
        f'<li><a href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(text)}</a></li>'
        for _, text, url in CREDITS
    )
    note = t("Everything on this page is reported by its source; nothing is inferred (v0 has no model).",
             "Todo en esta página lo reporta su fuente; nada es inferido (v0 no usa modelo).")
    return (f'<details class="section" id="sources" open><summary>{t("Sources", "Fuentes")}</summary>'
            f"<ul>{''.join(lines)}</ul><footer><p>{note}</p><ul>{credits}</ul></footer></details>")


def render_html(recon: Recon) -> str:
    built = local(recon.now)
    stale = [s.source for s in recon.sources if s.stale]
    warn = ""
    if stale:
        warn = (f'<p class="warn">⚠ {t("Behind or failing:", "Atrasadas o fallando:")} '
                f'{escape(", ".join(stale))} — <a href="#sources">{t("see Sources", "ver Fuentes")}</a></p>')
    sections = "".join(_section(s) for s in recon.sections)
    return f"""<!doctype html>
<html lang="en" data-lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Recon {built:%Y-%m-%d}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<header>
<div><h1>{t("Morning Recon", "Recon matutino")}</h1>
<p class="when">{built:%Y-%m-%d} · {t("built", "generado")} {built:%H:%M} {t("Mexico City time", "hora CDMX")}</p></div>
<button id="lang-toggle" type="button">ES</button>
</header>
{warn}
{sections}
{_sources(recon)}
</main>
<script>{SCRIPT}</script>
</body>
</html>
"""
