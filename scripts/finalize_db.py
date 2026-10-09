#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rapikan database setelah diedit manual (mis. lewat editor GitHub).

* Memeriksa format setiap jurnal (agar salah ketik tertangkap sebelum sampai ke pengguna).
* Bila isi berubah: menaikkan nomor versi, menulis catatan "Apa yang berubah" (dibandingkan dengan --prev),
  dan membuat ulang journals.js serta version.json.

Contoh:  python scripts/finalize_db.py --db docs/data/journals.json --prev versi_sebelumnya.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dbtools import bump, content_hash, diff_journals, finalize_files, load_db  # noqa: E402

TIERS = {"Q1", "Q2", "Q3", "Q4", "Q?", "PROC", "S12", "S34", "S56", "S?", "X"}
REQUIRED = ["id", "name", "group", "tier", "publisher", "fields", "tags", "access", "fee_text", "accept_months",
            "acceptance", "url"]


def validate(db):
    errs = []
    tax = db.get("taxonomy") or {}
    fx = db.get("fx_per_usd") or {}
    ids = set()
    for n, j in enumerate(db.get("journals") or [], 1):
        label = j.get("name") or f"jurnal ke-{n}"
        for k in REQUIRED:
            if k not in j:
                errs.append(f"{label}: kolom '{k}' tidak ada")
        if j.get("id") in ids:
            errs.append(f"{label}: id '{j.get('id')}' dipakai dua kali")
        ids.add(j.get("id"))
        if j.get("tier") not in TIERS:
            errs.append(f"{label}: tier '{j.get('tier')}' tidak dikenal (pilih salah satu: {', '.join(sorted(TIERS))})")
        if not set(j.get("fields") or []) <= set("HDSK"):
            errs.append(f"{label}: fields hanya boleh berisi H, D, S, K")
        for t in j.get("tags") or []:
            if t not in tax:
                errs.append(f"{label}: tag '{t}' tidak ada di taxonomy")
        am = j.get("accept_months")
        if not (isinstance(am, list) and len(am) == 2 and all(isinstance(x, (int, float)) for x in am) and am[0] <= am[1]):
            errs.append(f"{label}: accept_months harus [min, maks] dalam bulan")
        ac = j.get("acceptance")
        if not (isinstance(ac, list) and len(ac) == 2 and all(isinstance(x, (int, float)) for x in ac)):
            errs.append(f"{label}: acceptance harus [min, maks] dalam persen")
        if j.get("fee_amount") is not None and j.get("fee_currency") not in fx:
            errs.append(f"{label}: mata uang '{j.get('fee_currency')}' tidak ada di fx_per_usd")
        if not str(j.get("url", "")).startswith("http"):
            errs.append(f"{label}: url harus diawali http")
    if not db.get("journals"):
        errs.append("Daftar jurnal kosong")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="docs/data/journals.json")
    ap.add_argument("--prev", help="journals.json versi sebelumnya (untuk catatan perubahan)")
    ap.add_argument("--summary", default="Pembaruan manual oleh admin.")
    a = ap.parse_args(argv)
    path = Path(a.db)
    db = load_db(path)
    errs = validate(db)
    if errs:
        print("Database tidak valid:\n- " + "\n- ".join(errs[:50]))
        sys.exit(1)
    vpath = path.parent / "version.json"
    old_hash = None
    if vpath.exists():
        try:
            old_hash = json.loads(vpath.read_text(encoding="utf-8")).get("hash")
        except ValueError:
            old_hash = None
    if content_hash(db) == old_hash and (path.parent / "journals.js").exists():
        print("Tidak ada perubahan isi; versi tetap v" + str(db.get("version")))
        return False
    prev = None
    if a.prev and Path(a.prev).exists():
        try:
            prev = load_db(a.prev)
        except ValueError:
            prev = None
    items = diff_journals(prev, db) if prev and prev.get("journals") else []
    for it in items:
        it.setdefault("source", "edit manual")
    bump(db, items, a.summary)
    finalize_files(path.parent, db)
    print(f"Versi baru v{db['version']} (urutan {db['seq']}), {len(items)} perubahan tercatat.")
    return True


if __name__ == "__main__":
    main()
