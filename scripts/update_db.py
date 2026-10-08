#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pembaruan otomatis database jurnal.

Sumber data:
  * OpenAlex  - verifikasi ISSN, APC indikatif, pencarian jurnal baru
  * DOAJ      - APC jurnal open access
  * Crossref  - tanggal diterima/disetujui artikel -> waktu submit sampai diterima (penerbit yang menyetor data ini)
  * Scimago   - kuartil SJR terbaru (file CSV tahunan, opsional: data-sources/scimago.csv)

Aturan keamanan:
  * Data yang dicek manual dari situs jurnal ("Terverifikasi (situs jurnal)") TIDAK ditimpa otomatis;
    bila sumber otomatis berbeda, temuan masuk daftar "Perlu ditinjau".
  * ISSN yang namanya tidak cocok dengan OpenAlex tidak dipakai untuk memperbarui data.
  * Jurnal baru hanya diusulkan (kandidat), tidak langsung ditambahkan.
Semua perubahan masuk ke Pull Request; admin menyetujui dengan menekan "Merge".
"""
import argparse
import csv
import datetime as dt
import difflib
import json
import os
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dbtools import FIELD_LABELS, WIB, bump, finalize_files, fmt, load_db  # noqa: E402

TODAY = dt.datetime.now(WIB)
DATE = TODAY.strftime("%Y-%m-%d")
DISCOVERY_QUERIES = ["naval architecture", "ship", "shipbuilding", "marine engineering", "ocean engineering",
                     "maritime", "offshore", "marine technology", "perkapalan", "kelautan", "kemaritiman"]
MANUAL_VERIFIED = re.compile(r"^Terverifikasi \((situs|daftar|pencarian)", re.I)


# ---------------------------------------------------------------- HTTP
class Http:
    def __init__(self, email="", pause=0.15):
        self.email = email
        self.pause = pause
        self.errors = []

    def get_json(self, url, params=None):
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        ua = "KompasJurnalPerkapalan/1.0" + (f" (mailto:{self.email})" if self.email else "")
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=40) as r:
                    data = json.loads(r.read().decode("utf-8"))
                time.sleep(self.pause)
                return data
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 ** attempt * 2)
                    continue
                self.errors.append(f"{e.code} {url[:120]}")
                return None
            except Exception as e:  # jaringan, JSON rusak
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                self.errors.append(f"{type(e).__name__} {url[:120]}")
                return None


# ---------------------------------------------------------------- utilitas
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\b(the|of|and|on|for|in|jurnal|journal)\b", " ", s).split()


def similarity(a, b):
    a_full, b_full = " ".join(norm(a)), " ".join(norm(b))
    a_core = " ".join(norm(re.sub(r"\(.*?\)", " ", a)))
    return max(difflib.SequenceMatcher(None, x, b_full).ratio() for x in (a_full, a_core))


def issn_key(s):
    return re.sub(r"[^0-9X]", "", str(s).upper()).zfill(8)


def is_oa_only(j):
    acc = (j.get("access") or "").lower()
    return "oa" in acc and "hybrid" not in acc and "langganan" not in acc


def is_manual_verified(status):
    return bool(MANUAL_VERIFIED.match(status or ""))


def parse_date(s):
    s = str(s).strip()
    for f in ("%d %B %Y", "%Y-%m-%d", "%d %b %Y", "%B %d, %Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


class Updater:
    def __init__(self, db, http, fx):
        self.db, self.http, self.fx = db, http, fx
        self.items, self.review, self.candidates, self.notes = [], [], [], []
        self.by_issn = {}
        for j in db["journals"]:
            for i in j.get("issn") or []:
                self.by_issn[issn_key(i)] = j
        self.openalex = {}  # journal id -> source

    def set(self, j, key, value, source):
        if j.get(key) == value:
            return False
        self.items.append({"type": "changed", "journal": j["name"], "field": FIELD_LABELS.get(key, key),
                           "old": fmt(j.get(key)), "new": fmt(value), "source": source})
        j[key] = value
        return True

    # ------------------------------------------------ OpenAlex: verifikasi ISSN
    def openalex_verify(self):
        with_issn = [j for j in self.db["journals"] if j.get("issn")]
        issns = sorted({issn_key(i) for j in with_issn for i in j["issn"]})
        found = {}
        for k in range(0, len(issns), 40):
            chunk = [f"{x[:4]}-{x[4:]}" for x in issns[k:k + 40]]
            data = self.http.get_json("https://api.openalex.org/sources", {
                "filter": "issn:" + "|".join(chunk), "per_page": 100,
                "select": "id,display_name,issn_l,issn,is_oa,is_in_doaj,apc_usd,apc_prices,homepage_url,host_organization_name,works_count,type"})
            for src in (data or {}).get("results", []):
                for i in src.get("issn") or []:
                    found[issn_key(i)] = src
        for j in with_issn:
            src = next((found[issn_key(i)] for i in j["issn"] if issn_key(i) in found), None)
            if not src:
                continue
            sim = similarity(j["name"], src.get("display_name", ""))
            if sim < 0.55:
                self.review.append(f'**ISSN tidak cocok** - {j["name"]}: ISSN {", ".join(j["issn"])} di OpenAlex bernama '
                                   f'"{src.get("display_name")}" (kemiripan {sim:.2f}). Data jurnal ini tidak diperbarui otomatis; cek ISSN-nya.')
                continue
            self.openalex[j["id"]] = src
            j["openalex_id"] = src.get("id")
            if (j.get("issn_status") or "").startswith("Perlu verifikasi"):
                j["issn_status"] = f"Terverifikasi otomatis (OpenAlex, {DATE})"
            # APC opsional untuk jurnal hybrid (informasi)
            if not is_oa_only(j) and src.get("apc_usd"):
                if j.get("oa_optional_usd") != src["apc_usd"]:
                    self.set(j, "oa_optional_usd", src["apc_usd"], "OpenAlex (indikatif)")

    # ------------------------------------------------ OpenAlex: cari ISSN untuk jurnal yang belum punya
    def openalex_resolve(self, limit=40):
        todo = [j for j in self.db["journals"] if not j.get("issn") and j["tier"] != "PROC"][:limit]
        for j in todo:
            q = re.sub(r"\(.*?\)", " ", j["name"]).strip()
            data = self.http.get_json("https://api.openalex.org/sources", {
                "search": q, "per_page": 5, "select": "id,display_name,issn_l,issn,host_organization_name"})
            best, score = None, 0
            for src in (data or {}).get("results", []):
                s = similarity(j["name"], src.get("display_name", ""))
                if s > score:
                    best, score = src, s
            if best and score >= 0.88 and best.get("issn"):
                if any(issn_key(i) in self.by_issn for i in best["issn"]):
                    continue
                self.set(j, "issn", best["issn"], f'OpenAlex (pencocokan nama {score:.2f}) - mohon cek')
                j["issn_status"] = f"Dicocokkan otomatis (OpenAlex, {DATE}) - mohon cek"
                j["openalex_id"] = best.get("id")

    # ------------------------------------------------ DOAJ: APC jurnal open access
    def doaj_apc(self):
        for j in self.db["journals"]:
            if not j.get("issn") or not is_oa_only(j) or j["tier"] == "PROC":
                continue
            rec = None
            for i in j["issn"]:
                data = self.http.get_json("https://doaj.org/api/search/journals/" + urllib.parse.quote(f"issn:{i}"))
                res = (data or {}).get("results") or []
                if res:
                    rec = res[0].get("bibjson", {})
                    break
            if not rec:
                continue
            apc = rec.get("apc") or {}
            if apc.get("has_apc") is False:
                new_amount, new_cur = 0, "USD"
                text = "Gratis (tanpa APC, menurut DOAJ)"
            else:
                prices = apc.get("max") or []
                if not prices:
                    continue
                p = prices[0]
                new_amount, new_cur = round(float(p.get("price", 0))), (p.get("currency") or "USD").upper()
                text = f"APC {new_cur} {new_amount:,}".replace(",", ".") + " (menurut DOAJ)"
                if rec.get("waiver", {}).get("has_waiver"):
                    text += "; ada kebijakan keringanan"
            same = (j.get("fee_amount") == new_amount and (j.get("fee_currency") == new_cur or new_amount == 0))
            if same:
                continue
            old = "belum pasti" if j.get("fee_amount") is None else f'{j.get("fee_currency")} {j.get("fee_amount")}'
            if is_manual_verified(j.get("fee_status")):
                self.review.append(f'**Biaya berbeda** - {j["name"]}: database (dicek manual) {old}, DOAJ {new_cur} {new_amount}. '
                                   f'Cek halaman biaya di {j.get("url")}.')
                continue
            if new_cur not in self.fx:
                self.review.append(f'**Mata uang baru** - {j["name"]}: DOAJ mencatat {new_cur} {new_amount}; tambahkan kurs {new_cur} di fx_per_usd.')
                continue
            self.set(j, "fee_amount", new_amount, "DOAJ")
            self.set(j, "fee_currency", new_cur, "DOAJ")
            self.set(j, "fee_text", text, "DOAJ")
            j["fee_status"] = f"Terverifikasi otomatis (DOAJ, {DATE})"

    # ------------------------------------------------ OpenAlex: APC indikatif bila DOAJ tidak ada
    def openalex_apc_fallback(self):
        for j in self.db["journals"]:
            src = self.openalex.get(j["id"])
            if not src or not is_oa_only(j) or j.get("fee_amount") is not None:
                continue
            prices = src.get("apc_prices") or []
            p = next((x for x in prices if (x.get("currency") or "").upper() in self.fx), None)
            if not p:
                continue
            amt, cur = round(float(p["price"])), p["currency"].upper()
            self.set(j, "fee_amount", amt, "OpenAlex (indikatif)")
            self.set(j, "fee_currency", cur, "OpenAlex (indikatif)")
            self.set(j, "fee_text", f"APC {cur} {amt:,} (indikatif, OpenAlex)".replace(",", "."), "OpenAlex (indikatif)")
            j["fee_status"] = f"Indikatif (OpenAlex, {DATE})"

    # ------------------------------------------------ Crossref: waktu submit -> diterima
    def crossref_review_times(self, min_n=15, limit=None):
        since = (TODAY - dt.timedelta(days=550)).strftime("%Y-%m-%d")
        done = 0
        for j in self.db["journals"]:
            if not j.get("issn") or j["tier"] == "PROC":
                continue
            if limit is not None and done >= limit:
                break
            done += 1
            data = self.http.get_json(f'https://api.crossref.org/journals/{j["issn"][0]}/works', {
                "filter": f"from-pub-date:{since},type:journal-article", "rows": 200, "select": "DOI,assertion",
                **({"mailto": self.http.email} if self.http.email else {})})
            items = ((data or {}).get("message") or {}).get("items") or []
            days = []
            for it in items:
                a = {x.get("name"): x.get("value") for x in it.get("assertion") or []}
                r, c = parse_date(a.get("received", "")), parse_date(a.get("accepted", ""))
                if r and c and 0 < (c - r).days < 1200:
                    days.append((c - r).days)
            if len(days) < min_n:
                continue
            days.sort()
            q = statistics.quantiles(days, n=4)
            med = statistics.median(days)
            lo, hi = round(q[0] / 30.44, 1), round(q[2] / 30.44, 1)
            new = [max(0.3, lo), max(lo + 0.1, hi)]
            old = j.get("accept_months") or [0, 0]
            if abs(old[0] - new[0]) >= 0.5 or abs(old[1] - new[1]) >= 0.5 or not (j.get("review_status") or "").startswith("Terverifikasi"):
                self.set(j, "accept_months", new, f"Crossref (median {med:.0f} hari, n={len(days)})")
                j["review_status"] = f"Terverifikasi otomatis (Crossref: median {med:.0f} hari, kuartil {q[0]:.0f}-{q[2]:.0f} hari, n={len(days)}, {DATE})"

    # ------------------------------------------------ Scimago: kuartil SJR
    def scimago(self, path, year):
        rows = {}
        with open(path, encoding="utf-8-sig", newline="") as f:
            sample = f.read(4096)
            f.seek(0)
            delim = ";" if sample.count(";") > sample.count(",") else ","
            for r in csv.DictReader(f, delimiter=delim):
                for i in (r.get("Issn") or "").split(","):
                    if i.strip():
                        rows[issn_key(i)] = r
        if not rows:
            self.notes.append("File Scimago kosong atau formatnya tidak dikenali.")
            return
        for j in self.db["journals"]:
            if not j["tier"].startswith("Q") or not j.get("issn"):
                continue
            r = next((rows[issn_key(i)] for i in j["issn"] if issn_key(i) in rows), None)
            if not r:
                continue
            q = (r.get("SJR Best Quartile") or "").strip()
            if q not in ("Q1", "Q2", "Q3", "Q4"):
                continue
            if j.get("quartile") != q:
                self.set(j, "quartile", q, f"Scimago SJR {year}")
                self.set(j, "tier", q, f"Scimago SJR {year}")
                j["quartile_src"] = f"SJR {year} (Scimago, kuartil terbaik)"
        known = set(self.by_issn)
        for k, r in rows.items():
            if k in known:
                continue
            title = r.get("Title", "")
            if any(w in title.lower() for w in ("ship", "naval", "marine", "maritime", "ocean", "offshore", "hydro")):
                self.candidates.append({"name": title, "issn": r.get("Issn"), "detail": f'Scimago {r.get("SJR Best Quartile")}',
                                        "url": ""})

    # ------------------------------------------------ OpenAlex: kandidat jurnal baru
    def discover(self, max_candidates=20):
        names = [j["name"] for j in self.db["journals"]]
        seen = set(c["name"].lower() for c in self.candidates)
        for q in DISCOVERY_QUERIES:
            data = self.http.get_json("https://api.openalex.org/sources", {
                "search": q, "filter": "type:journal,works_count:>40", "per_page": 25,
                "select": "id,display_name,issn_l,issn,host_organization_name,works_count,homepage_url,is_oa,apc_usd"})
            for src in (data or {}).get("results", []):
                if any(issn_key(i) in self.by_issn for i in src.get("issn") or []):
                    continue
                nm = src.get("display_name", "")
                if nm.lower() in seen or any(similarity(n, nm) > 0.85 for n in names):
                    continue
                seen.add(nm.lower())
                apc = src.get("apc_usd")
                self.candidates.append({
                    "name": nm, "issn": src.get("issn_l"), "url": src.get("homepage_url") or "",
                    "detail": f'{src.get("host_organization_name") or "penerbit ?"}; {src.get("works_count")} artikel; '
                              f'{"OA" if src.get("is_oa") else "non-OA"}{f"; APC ~USD {apc}" if apc else ""}'})
            if len(self.candidates) >= max_candidates:
                break
        self.candidates = self.candidates[:max_candidates]


# ---------------------------------------------------------------- laporan
def report_md(up, db, changed, sources):
    L = [f"# Pembaruan database jurnal - {DATE}", ""]
    if changed:
        L.append(f"Versi baru: **v{db['version']}** (urutan {db['seq']}). Tekan **Merge** untuk menyetujui; "
                 "aplikasi pengguna akan menawarkan pembaruan setelah GitHub Pages selesai diperbarui.")
    else:
        L.append("Tidak ada perubahan data yang diterapkan minggu ini.")
    L += ["", f"Sumber yang dipakai: {', '.join(sources)}.", ""]
    if up.items:
        L += [f"## Perubahan yang diterapkan ({len(up.items)})", "", "| Jurnal | Data | Lama | Baru | Sumber |", "|---|---|---|---|---|"]
        for it in up.items:
            cell = lambda s: str(s).replace("|", "/")[:120]
            L.append(f"| {cell(it['journal'])} | {cell(it['field'])} | {cell(it['old'])} | {cell(it['new'])} | {cell(it['source'])} |")
        L.append("")
        L.append("Tidak setuju dengan salah satu baris? Edit `docs/data/journals.json` di cabang PR ini sebelum Merge, "
                 "atau tutup PR untuk menolak semuanya.")
        L.append("")
    if up.review:
        L += [f"## Perlu ditinjau manual ({len(up.review)})", ""] + [f"- {r}" for r in up.review] + [""]
    if up.candidates:
        L += [f"## Kandidat jurnal baru ({len(up.candidates)})", "",
              "Belum ditambahkan. Bila relevan, tambahkan ke `journals.json` (atau minta bantuan Claude).", ""]
        for c in up.candidates:
            L.append(f"- **{c['name']}** - ISSN {c.get('issn') or '?'} - {c.get('detail', '')} {c.get('url', '')}".rstrip())
        L.append("")
    if up.notes:
        L += ["## Catatan", ""] + [f"- {n}" for n in up.notes] + [""]
    if up.http.errors:
        L += [f"## Sumber yang gagal dihubungi ({len(up.http.errors)})", "",
              "Bukan masalah besar; akan dicoba lagi minggu depan.", ""] + [f"- `{e}`" for e in up.http.errors[:25]] + [""]
    return "\n".join(L)


def main(argv=None, http=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="docs/data/journals.json")
    ap.add_argument("--report", default="update_report.md")
    ap.add_argument("--scimago", help="CSV Scimago (Download data di scimagojr.com)")
    ap.add_argument("--scimago-year", default=str(TODAY.year - 1))
    ap.add_argument("--no-crossref", action="store_true")
    ap.add_argument("--crossref-limit", type=int)
    ap.add_argument("--no-discover", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Hanya buat laporan, jangan ubah database")
    a = ap.parse_args(argv)

    db = load_db(a.db)
    http = http or Http(email=os.environ.get("CONTACT_EMAIL", ""))
    up = Updater(db, http, db.get("fx_per_usd", {}))
    sources = ["OpenAlex", "DOAJ"]
    up.openalex_verify()
    up.openalex_resolve()
    up.doaj_apc()
    up.openalex_apc_fallback()
    if not a.no_crossref:
        sources.append("Crossref")
        up.crossref_review_times(limit=a.crossref_limit)
    if a.scimago and Path(a.scimago).exists():
        sources.append(f"Scimago {a.scimago_year}")
        up.scimago(a.scimago, a.scimago_year)
    if not a.no_discover:
        up.discover()

    changed = bool(up.items) and not a.dry_run
    if changed:
        n = len({i["journal"] for i in up.items})
        bump(db, up.items, f"Pembaruan otomatis: {len(up.items)} perubahan pada {n} jurnal.", sources)
        finalize_files(Path(a.db).parent, db)
    Path(a.report).write_text(report_md(up, db, changed, sources), encoding="utf-8")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"review={'true' if (up.review or up.candidates) else 'false'}\n")
            f.write(f"version={db.get('version')}\n")
    print(f"perubahan={len(up.items)} tinjauan={len(up.review)} kandidat={len(up.candidates)} galat={len(http.errors)}")
    return up


if __name__ == "__main__":
    main()
