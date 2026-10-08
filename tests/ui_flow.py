# -*- coding: utf-8 -*-
"""Uji alur lengkap di browser: rekomendasi, filter, offline (service worker), pembaruan, ekspor/impor, laporan.
Jalankan: python tests/ui_flow.py <folder-screenshot>
"""
import functools, http.server, json, shutil, socketserver, sys, tempfile, threading, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from dbtools import bump, finalize_files  # noqa: E402

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
SITE = Path(tempfile.mkdtemp()) / "site"
shutil.copytree(ROOT / "docs", SITE)


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(SITE)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}/"
results = []


def ok(c, m):
    results.append((bool(c), m))
    print(("LULUS " if c else "GAGAL ") + m)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1366, "height": 900}, accept_downloads=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE)
    pg.wait_for_selector(".card")

    # --- rekomendasi kendali & IoT
    pg.fill("#q", "Sistem kendali autopilot USV berbasis IoT dengan sensor GPS untuk monitoring kapal")
    time.sleep(0.6)
    chips = pg.locator("#detected .chip").all_inner_texts()
    ok(any("Autopilot" in c for c in chips) and any("IoT" in c for c in chips) and any("otonom" in c.lower() for c in chips),
       "kata kunci Indonesia terdeteksi: " + "; ".join(c.replace("×", "").strip() for c in chips))
    top = pg.locator(".card h3").all_inner_texts()[:5]
    print("   5 teratas:", top)
    ok(any("Oceanic" in t or "Ocean Engineering" == t or "Navigation" in t or "JMSE" in t for t in top), "jurnal kendali maritim muncul di 5 teratas")

    # --- filter gratis + waktu tunggu 4 bulan
    pg.click("text=Gratis saja")
    pg.click("label:has(input[name=wait][value='4'])")
    time.sleep(0.4)
    fees = pg.locator(".card .stat:nth-child(1) .v").all_inner_texts()
    ok(fees and all(f.startswith("Gratis") for f in fees), f"filter gratis: {len(fees)} kartu semuanya gratis")
    waits = pg.locator(".card .stat:nth-child(2) .v").all_inner_texts()
    ok(all(sum(float(x.replace(",", ".")) for x in w.replace(" bln", "").split("-")) / 2 <= 4 for w in waits), "filter waktu tunggu <= 4 bulan dihormati")
    pg.click("#btn-reset")
    time.sleep(0.3)

    # --- detail & laporan
    pg.click(".card >> nth=0 >> [data-act=detail]")
    ok(pg.locator(".card >> nth=0 >> .details dl").is_visible(), "detail jurnal terbuka")
    pg.click(".card >> nth=0 >> [data-act=report]")
    prev = pg.inner_text("#rp-preview")
    ok("Jurnal:" in prev and "Versi database" in prev, "formulir laporan terisi otomatis")
    ok(pg.locator("#rp-github").is_hidden(), "tombol GitHub tersembunyi selama repo belum diatur")
    pg.click("#dlg-report [data-close]")

    # --- service worker & offline
    pg.evaluate("navigator.serviceWorker.ready.then(() => true)")
    pg.reload(); pg.wait_for_selector(".card")
    ok(pg.evaluate("!!navigator.serviceWorker.controller"), "service worker aktif (mode offline siap)")
    ctx.set_offline(True)
    pg.reload(); pg.wait_for_selector(".card", timeout=8000)
    ok(pg.inner_text("#net-label") == "Offline" and pg.locator(".card").count() > 0, "aplikasi tetap jalan saat offline")
    ctx.set_offline(False)

    # --- terbitkan database baru di server (simulasi pembaruan mingguan)
    dbp = SITE / "data" / "journals.json"
    db = json.loads(dbp.read_text(encoding="utf-8"))
    j = next(x for x in db["journals"] if x["name"] == "Indonesian Journal of Maritime Technology (ISMATECH)")
    old_sinta = j["sinta"]; j["sinta"] = "S2"; j["tier"] = "S12"; j["index"] = "SINTA 2"
    bump(db, [{"type": "changed", "journal": j["name"], "field": "SINTA", "old": old_sinta, "new": "S2", "source": "uji"}],
         "Uji pembaruan: ISMATECH naik ke SINTA 2.")
    finalize_files(SITE / "data", db)
    new_ver = db["version"]

    pg.reload(); pg.wait_for_selector(".card")
    pg.wait_for_selector("#update-banner:not([hidden])", timeout=8000)
    ok(True, "banner 'Database baru tersedia' muncul otomatis")
    pg.screenshot(path=str(OUT / "update-banner.png"))
    pg.click("#btn-apply-update")
    pg.wait_for_function(f"document.querySelector('#db-label').textContent.includes('{new_ver}')", timeout=8000)
    ok(True, f"setelah klik Perbarui, aplikasi memakai v{new_ver}")
    pg.click("#btn-changes")
    ok("ISMATECH naik ke SINTA 2" in pg.inner_text("#changes-log"), "dialog 'Apa yang berubah' menampilkan perubahan baru")
    pg.screenshot(path=str(OUT / "changes.png"))
    pg.click("#dlg-changes [data-close]")

    ctx.set_offline(True)
    pg.reload(); pg.wait_for_selector(".card", timeout=8000)
    ok(new_ver in pg.inner_text("#db-label"), "setelah ditutup & dibuka offline, data terbaru tetap dipakai")
    ctx.set_offline(False)

    # --- ekspor / impor / CSV
    pg.click("#btn-data")
    with pg.expect_download() as d:
        pg.click("#btn-export")
    path = OUT / "export.json"
    d.value.save_as(str(path))
    ok(json.loads(path.read_text(encoding="utf-8"))["version"] == new_ver, "ekspor database menghasilkan file versi terbaru")
    pg.set_input_files("#import-file", str(ROOT / "docs" / "data" / "journals.json"))
    pg.wait_for_selector("#import-confirm:not([hidden])")
    ok("lebih lama" in pg.inner_text("#import-confirm"), "impor versi lama memberi peringatan")
    pg.click("#imp-yes")
    time.sleep(0.4)
    ok("v2026.10.08 " in pg.inner_text("#db-label") + " ", "impor file database berhasil dipakai")
    with pg.expect_download() as d2:
        pg.click("#btn-csv")
    csvp = OUT / "hasil.csv"; d2.value.save_as(str(csvp))
    ok(csvp.read_text(encoding="utf-8-sig").startswith('"Peringkat","Jurnal"'), "unduh hasil CSV berfungsi")
    ok(not errs, "tidak ada error JavaScript: " + "; ".join(errs[:3]))

    # --- tampilan HP gelap dengan filter terbuka
    m = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark")
    mp = m.new_page(); mp.goto(BASE); mp.wait_for_selector(".card")
    mp.click("#adv summary"); time.sleep(0.2)
    mp.locator("#adv").screenshot(path=str(OUT / "phone-filters.png"))
    mp.locator(".card >> nth=0").screenshot(path=str(OUT / "phone-card.png"))
    ok(not mp.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"), "tidak ada scroll horizontal di HP")
    b.close()

srv.shutdown()
print(f"{sum(r for r, _ in results)}/{len(results)} lulus")
