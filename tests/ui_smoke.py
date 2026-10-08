# -*- coding: utf-8 -*-
"""Uji cepat tampilan & fungsi utama aplikasi (Playwright, Chromium).
Jalankan: python tests/ui_smoke.py <folder-yang-diserve> <folder-output-screenshot>
"""
import http.server, socketserver, sys, threading, functools, json, time
from pathlib import Path
from playwright.sync_api import sync_playwright

SERVE = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
MODE = sys.argv[3] if len(sys.argv) > 3 else "shots"


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve():
    h = functools.partial(Q, directory=str(SERVE))
    srv = socketserver.TCPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def main():
    srv, base = serve()
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, vp, scheme in [("desktop-light", (1366, 900), "light"), ("desktop-dark", (1366, 900), "dark"),
                                 ("phone-light", (390, 844), "light"), ("phone-dark", (390, 844), "dark")]:
            ctx = b.new_context(viewport={"width": vp[0], "height": vp[1]}, color_scheme=scheme)
            pg = ctx.new_page()
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(base + "index.html")
            pg.wait_for_selector(".card")
            time.sleep(0.6)
            sw = pg.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
            print(name, "horizontal-overflow:", sw, "| summary:", pg.inner_text("#res-summary")[:160])
            pg.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
            if name == "desktop-light":
                pg.click(".card [data-act=detail]")
                pg.screenshot(path=str(OUT / "desktop-detail.png"), full_page=False)
            ctx.close()
        b.close()
    srv.shutdown()
    print("console errors:", errors[:10])


if __name__ == "__main__":
    main()
