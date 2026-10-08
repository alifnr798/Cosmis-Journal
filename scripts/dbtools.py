# -*- coding: utf-8 -*-
"""Fungsi bersama untuk merawat database jurnal (dipakai update_db.py dan finalize_db.py)."""
import datetime as dt
import hashlib
import json
from pathlib import Path

WIB = dt.timezone(dt.timedelta(hours=7))

FIELD_LABELS = {
    "name": "Nama", "tier": "Tingkat", "quartile": "Kuartil Scopus", "sinta": "SINTA", "index": "Indeksasi",
    "publisher": "Penerbit", "access": "Model akses", "fee_text": "Biaya", "fee_amount": "Nominal biaya",
    "fee_currency": "Mata uang", "fee_status": "Status data biaya", "oa_optional_usd": "OA opsional (USD)",
    "first_decision": "Keputusan awal", "accept_months": "Waktu submit-accept (bln)", "acceptance": "Acceptance rate",
    "review_status": "Status data review", "url": "Link", "issn": "ISSN", "fields": "Bidang", "tags": "Kata kunci",
    "lang": "Bahasa", "note": "Catatan", "sinta_status": "Status SINTA", "quartile_src": "Sumber kuartil",
}
IGNORE_FIELDS = {"openalex_id", "sources", "issn_status", "maritime", "lang_id", "id", "group", "country"}


def load_db(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def content_hash(db):
    core = {k: db.get(k) for k in ("journals", "taxonomy", "fx_per_usd", "groups", "picks")}
    blob = json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def fmt(v):
    if v is None or v == "" or v == []:
        return "-"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v)


def diff_journals(old_db, new_db):
    """Daftar perubahan tingkat-kolom antara dua versi database."""
    old = {j["id"]: j for j in (old_db or {}).get("journals", [])}
    new = {j["id"]: j for j in new_db.get("journals", [])}
    items = []
    for jid, j in new.items():
        if jid not in old:
            items.append({"type": "added", "journal": j["name"], "detail": f'{j.get("tier")} - {j.get("fee_text")}'})
            continue
        o = j_old = old[jid]
        for k in sorted(set(j) | set(j_old)):
            if k in IGNORE_FIELDS:
                continue
            if j.get(k) != o.get(k):
                items.append({"type": "changed", "journal": j["name"], "field": FIELD_LABELS.get(k, k),
                              "old": fmt(o.get(k)), "new": fmt(j.get(k))})
    for jid, j in old.items():
        if jid not in new:
            items.append({"type": "removed", "journal": j["name"]})
    return items


def bump(db, items, summary, sources=None, now=None):
    now = now or dt.datetime.now(WIB)
    date = now.strftime("%Y.%m.%d")
    seq = int(db.get("seq", 0)) + 1
    same_day = [c for c in db.get("changelog", []) if str(c.get("version", "")).startswith(date)]
    version = date if not same_day else f"{date}.{len(same_day) + 1}"
    db["seq"] = seq
    db["version"] = version
    db["generated"] = now.isoformat(timespec="seconds")
    entry = {"seq": seq, "version": version, "date": now.strftime("%Y-%m-%d"), "summary": summary, "items": items}
    if sources:
        entry["sources"] = sources
    db.setdefault("changelog", []).append(entry)
    db["changelog"] = db["changelog"][-60:]  # simpan riwayat 60 pembaruan terakhir
    return db


def finalize_files(data_dir, db):
    """Tulis journals.json, journals.js (database bawaan untuk mode offline/file lokal) dan version.json."""
    data_dir = Path(data_dir)
    db["hash"] = content_hash(db)
    text = json.dumps(db, ensure_ascii=False, indent=1)
    (data_dir / "journals.json").write_text(text, encoding="utf-8")
    (data_dir / "journals.js").write_text(
        "/* Database bawaan - dibuat otomatis oleh scripts/dbtools.py. Jangan diedit manual; edit journals.json. */\n"
        "window.__KJP_BUNDLED__ = " + json.dumps(db, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8")
    last = db.get("changelog", [{}])[-1]
    version = {
        "schema": db.get("schema", 1), "seq": db["seq"], "version": db["version"], "generated": db["generated"],
        "count": len(db["journals"]), "hash": db["hash"], "summary": last.get("summary", ""),
        "changes": len(last.get("items", [])),
    }
    (data_dir / "version.json").write_text(json.dumps(version, ensure_ascii=False, indent=1), encoding="utf-8")
    return version
