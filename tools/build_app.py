# -*- coding: utf-8 -*-
"""Rakit aplikasi: src/ -> docs/ (versi GitHub Pages, dokumen lengkap) dan dist-artifact/ (pratinjau claude.ai)."""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC, DOCS, ART = ROOT / "src", ROOT / "docs", ROOT / "dist-artifact"

HEAD = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="description" content="Rekomendasi jurnal Scopus dan SINTA untuk teknik perkapalan: hidrodinamika, desain, struktur, kendali dan IoT. Bisa dipakai offline.">
<meta name="theme-color" content="#0d2a33">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="icons/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="icons/icon-192.png">
<style>[hidden]{display:none!important}:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}</style>
</head>
<body>
"""
TAIL = "\n</body>\n</html>\n"


def main():
    page = (SRC / "page.html").read_text(encoding="utf-8")
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(HEAD + page + TAIL, encoding="utf-8")
    for f in ("app.js", "config.js", "sw.js", "manifest.webmanifest"):
        shutil.copy(SRC / f, DOCS / f)
    shutil.copytree(SRC / "icons", DOCS / "icons", dirs_exist_ok=True)
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    # pratinjau artifact: konten halaman saja (kerangka dokumen ditambahkan saat publish)
    if ART.exists():
        shutil.rmtree(ART)
    (ART / "data").mkdir(parents=True)
    (ART / "index.html").write_text(page, encoding="utf-8")
    for f in ("app.js", "config.js"):
        shutil.copy(SRC / f, ART / f)
    for f in ("journals.js", "journals.json", "version.json"):
        shutil.copy(DOCS / "data" / f, ART / "data" / f)
    print("docs/ dan dist-artifact/ siap")


if __name__ == "__main__":
    main()
