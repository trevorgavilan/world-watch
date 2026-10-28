# Vendored files (D-17)

The Board loads nothing from the internet: every library and image it uses is here, at a pinned
version, with its SHA-256 in `MANIFEST.json`. `tests/test_board.py` fails if a file changes or if a
file is added without an entry.

To upgrade: download the new version from the source named in the manifest, check it against the
publisher's own hash (npm's `dist.integrity`), replace the file, update its manifest entry and
`STATIC` in `worldwatch/board/server.py`, and look at the page's network log once.
