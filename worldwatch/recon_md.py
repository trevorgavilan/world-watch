"""Recon's Markdown twin — the same content, bilingual headings, plain text that
reads in any editor. Source text is escaped so a headline can't fake a link.
"""

from __future__ import annotations

import re

from .item import clean_url
from .recon import CREDITS, Recon, local, show_event, show_time

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|<>~])")


def md_escape(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", text)


def md_url(url: str) -> str:
    return url.replace("\\", "%5C").replace("(", "%28").replace(")", "%29").replace(" ", "%20").replace("<", "%3C").replace(">", "%3E")


def _line(row) -> str:
    title = md_escape(row["title"])
    url = clean_url(row["url"])  # checked again here: the page must not trust the store
    head = f"[{title}]({md_url(url)})" if url else title
    meta = [row["severity"]] if row["severity"] else []
    meta += [row["source"], f"event {show_event(row)}",
             f"fetched {show_time(row['fetched_at'])}", row["basis"]]
    line = f"- {head}  \n  {md_escape(' · '.join(meta))}"
    if row["summary"]:
        line += f"  \n  {md_escape(row['summary'])}"
    return line


def render_md(recon: Recon) -> str:
    built = local(recon.now)
    out = [f"# Morning Recon · Recon matutino — {built:%Y-%m-%d}", "",
           f"Built {built:%H:%M} Mexico City time · generado {built:%H:%M} hora CDMX", ""]
    stale = [s.source for s in recon.sources if s.stale]
    if stale:
        out += [f"> ⚠ Behind or failing (stale): {', '.join(stale)}", ""]
    for section in recon.sections:
        out += [f"## {section.en} · {section.es}", ""]
        for group in section.groups:
            out += [f"### {group.en} · {group.es}", ""]
            out += [_line(r) for r in group.rows] or ["_Nothing yet · Nada todavía._"]
            out.append("")
    out += ["## Sources · Fuentes", ""]
    for s in recon.sources:
        when = show_time(s.last_ok.strftime("%Y-%m-%dT%H:%M:%SZ")) if s.last_ok else "never"
        line = f"- {s.source}: last success {when}" + (" — **stale**" if s.stale else "")
        if s.error:
            line += f" — last error: {md_escape(s.error)}"
        out.append(line)
    out += ["", "Everything here is reported by its source; nothing is inferred (v0 has no model).", ""]
    out += [f"- [{md_escape(text)}]({url})" for _, text, url in CREDITS]
    return "\n".join(out) + "\n"
