# -*- coding: utf-8 -*-
"""Uji logika pembaruan dengan respons tiruan (tanpa internet). Jalankan: python tests/test_update.py"""
import json, shutil, sys, tempfile, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import update_db  # noqa: E402
import finalize_db  # noqa: E402


class FakeHttp:
    email = ""

    def __init__(self):
        self.errors = []
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append((url, params))
        p = params or {}
        if url.startswith("https://api.openalex.org/sources"):
            if "filter" in p and p["filter"].startswith("issn:"):
                return {"results": [
                    {"id": "S1", "display_name": "Ocean Engineering", "issn": ["0029-8018", "1873-5258"], "apc_usd": 4030},
                    {"id": "S2", "display_name": "Polish Maritime Research", "issn": ["1233-2585", "2083-7429"]},
                    {"id": "S3", "display_name": "Totally Different Journal", "issn": ["1001-6058"]},
                    {"id": "S4", "display_name": "Journal of Ocean Engineering and Science", "issn": ["2468-0133"],
                     "apc_prices": [{"price": 1990, "currency": "USD"}]},
                    {"id": "S5", "display_name": "Journal of Marine Science and Technology", "issn": ["0948-4280", "1437-8213"]},
                ]}
            if "search" in p:
                if p["search"] == "ocean engineering":
                    return {"results": [{"id": "S9", "display_name": "Marine Robotics Letters", "issn": ["1234-5679"],
                                         "issn_l": "1234-5679", "works_count": 120, "is_oa": True, "apc_usd": 900,
                                         "host_organization_name": "Contoh Press"}]}
                return {"results": []}
        if url.startswith("https://doaj.org/api/search/journals/"):
            q = urllib.parse.unquote(url.rsplit("/", 1)[1])
            table = {
                "issn:1233-2585": {"apc": {"has_apc": True, "max": [{"price": 600, "currency": "EUR"}]}},
                "issn:2468-0133": {"apc": {"has_apc": True, "max": [{"price": 2000, "currency": "USD"}]}},
                "issn:1848-3305": {"apc": {"has_apc": False}},
                "issn:1829-8370": {"apc": {"has_apc": False}},
            }
            if q in table:
                return {"results": [{"bibjson": table[q]}]}
            return {"results": []}
        if url.startswith("https://api.crossref.org/journals/0948-4280/works"):
            items = []
            for k in range(30):
                rec = 150 + k * 4
                items.append({"DOI": f"10.1/x{k}", "assertion": [
                    {"name": "received", "value": "1 January 2025"},
                    {"name": "accepted", "value": (__import__("datetime").date(2025, 1, 1) + __import__("datetime").timedelta(days=rec)).strftime("%d %B %Y")}]})
            return {"message": {"items": items}}
        if url.startswith("https://api.crossref.org/"):
            return {"message": {"items": []}}
        return None


def by_name(db, name):
    return next(j for j in db["journals"] if j["name"] == name)


def main():
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "docs" / "data", tmp / "data")
    dbp = tmp / "data" / "journals.json"
    sc = tmp / "scimago.csv"
    sc.write_text("Rank;Sourceid;Title;Type;Issn;SJR;SJR Best Quartile\n"
                  "1;1;Ocean Engineering;journal;00298018, 18735258;1,2;Q1\n"
                  "2;2;Ships and Offshore Structures;journal;17445302, 1754212X;0,6;Q1\n"
                  "3;3;Marine Hull Dynamics Review;journal;99999999;0,4;Q2\n", encoding="utf-8")
    before = json.loads(dbp.read_text(encoding="utf-8"))
    up = update_db.main(["--db", str(dbp), "--report", str(tmp / "r.md"), "--scimago", str(sc), "--scimago-year", "2025"],
                        http=FakeHttp())
    after = json.loads(dbp.read_text(encoding="utf-8"))
    ver = json.loads((tmp / "data" / "version.json").read_text(encoding="utf-8"))
    js = (tmp / "data" / "journals.js").read_text(encoding="utf-8")
    report = (tmp / "r.md").read_text(encoding="utf-8")

    checks = []
    def ok(cond, msg):
        checks.append((bool(cond), msg))

    ok(after["seq"] == before["seq"] + 1, "nomor urut versi naik satu")
    ok(ver["seq"] == after["seq"] and ver["hash"] == after["hash"], "version.json ikut diperbarui")
    ok(f'"seq":{after["seq"]}' in js, "journals.js (database bawaan) ikut diperbarui")
    ok(after["changelog"][-1]["items"], "catatan 'Apa yang berubah' terisi")
    joes = by_name(after, "Journal of Ocean Engineering and Science")
    ok(joes["fee_amount"] == 2000 and joes["fee_currency"] == "USD" and "DOAJ" in joes["fee_status"], "APC dari DOAJ diterapkan untuk jurnal OA yang biayanya belum pasti")
    toms = by_name(after, "Transactions on Maritime Science (ToMS)")
    ok(toms["fee_amount"] == 0, "DOAJ 'tanpa APC' diterapkan")
    pmr = by_name(after, "Polish Maritime Research")
    ok(pmr["fee_amount"] == 500 and pmr["fee_currency"] == "EUR", "biaya hasil cek manual situs TIDAK ditimpa DOAJ")
    ok(any("Polish Maritime Research" in r for r in up.review), "konflik biaya masuk daftar tinjauan")
    ok(any("Journal of Hydrodynamics" in r and "ISSN tidak cocok" in r for r in up.review), "ISSN yang namanya tidak cocok ditandai")
    hyd = by_name(after, "Journal of Hydrodynamics")
    ok(hyd["openalex_id"] is None, "jurnal dengan ISSN tidak cocok tidak diperbarui")
    jst = by_name(after, "Journal of Marine Science and Technology (JASNAOE)")
    ok("Crossref" in jst["review_status"] and 5.5 <= jst["accept_months"][0] <= 6.5, f"waktu review dihitung dari Crossref ({jst['accept_months']})")
    sos = by_name(after, "Ships and Offshore Structures")
    ok(sos["tier"] == "Q1" and sos["quartile"] == "Q1" and "2025" in sos["quartile_src"], "kuartil Scimago diterapkan")
    ok(any(c["name"] == "Marine Hull Dynamics Review" for c in up.candidates), "jurnal baru dari Scimago diusulkan sebagai kandidat")
    ok(any(c["name"] == "Marine Robotics Letters" for c in up.candidates), "jurnal baru dari OpenAlex diusulkan sebagai kandidat")
    ok(not any(j["name"] == "Marine Robotics Letters" for j in after["journals"]), "kandidat tidak langsung ditambahkan")
    ok(by_name(after, "Ocean Engineering")["issn_status"].startswith("Resurchify"), "status ISSN yang sudah bersumber tidak diubah")
    ok("## Perubahan yang diterapkan" in report and "## Perlu ditinjau manual" in report and "## Kandidat jurnal baru" in report, "laporan PR lengkap")

    # edit manual -> finalize
    prev = tmp / "prev.json"
    shutil.copy(dbp, prev)
    d = json.loads(dbp.read_text(encoding="utf-8"))
    by_name(d, "Jurnal Teknik Perkapalan (Undip)")["sinta"] = "S4"
    by_name(d, "Jurnal Teknik Perkapalan (Undip)")["tier"] = "S34"
    dbp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    finalize_db.main(["--db", str(dbp), "--prev", str(prev), "--summary", "Uji edit manual"])
    d2 = json.loads(dbp.read_text(encoding="utf-8"))
    last = d2["changelog"][-1]
    ok(d2["seq"] == after["seq"] + 1 and any(i.get("field") == "SINTA" and i.get("new") == "S4" for i in last["items"]), "edit manual tercatat otomatis di changelog")
    ok(finalize_db.main(["--db", str(dbp)]) is False, "finalize kedua tanpa perubahan tidak menaikkan versi")
    # validasi menangkap salah ketik
    bad = json.loads(dbp.read_text(encoding="utf-8"))
    bad["journals"][0]["tier"] = "Q5"
    ok(any("tier 'Q5'" in e for e in finalize_db.validate(bad)), "validasi menangkap tier yang salah")

    for passed, msg in checks:
        print(("LULUS " if passed else "GAGAL ") + msg)
    print(f"{sum(p for p, _ in checks)}/{len(checks)} lulus")
    print("--- cuplikan laporan ---")
    print(report[:1800])
    return all(p for p, _ in checks)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
