/* Kompas Jurnal Perkapalan - aplikasi rekomendasi jurnal (offline + pembaruan online).
 * Tanpa library eksternal. Data: data/journals.js (bawaan) + database tersimpan di browser.
 */
(function () {
  "use strict";

  const CFG = Object.assign({ updateBase: "data/", repo: "", issueTemplate: "laporan-perubahan.yml" }, window.KJP_CONFIG || {});
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const PAGE = 40;

  // ------------------------------------------------------------------ penyimpanan (IndexedDB -> localStorage -> memori)
  const store = (function () {
    const mem = {};
    let idbp = null;
    function idb() {
      if (idbp) return idbp;
      idbp = new Promise((res, rej) => {
        try {
          const rq = indexedDB.open("kompas-jurnal", 1);
          rq.onupgradeneeded = () => rq.result.createObjectStore("kv");
          rq.onsuccess = () => res(rq.result);
          rq.onerror = () => rej(rq.error);
        } catch (e) { rej(e); }
      });
      return idbp;
    }
    async function get(k) {
      try {
        const db = await idb();
        return await new Promise((res, rej) => {
          const rq = db.transaction("kv").objectStore("kv").get(k);
          rq.onsuccess = () => res(rq.result);
          rq.onerror = () => rej(rq.error);
        });
      } catch (e) {
        try { const v = localStorage.getItem("kjp:" + k); return v ? JSON.parse(v) : undefined; } catch (e2) { return mem[k]; }
      }
    }
    async function set(k, v) {
      try {
        const db = await idb();
        await new Promise((res, rej) => {
          const tx = db.transaction("kv", "readwrite");
          tx.objectStore("kv").put(v, k);
          tx.oncomplete = res; tx.onerror = () => rej(tx.error);
        });
        return true;
      } catch (e) {
        try { localStorage.setItem("kjp:" + k, JSON.stringify(v)); return true; } catch (e2) { mem[k] = v; return false; }
      }
    }
    async function del(k) {
      try {
        const db = await idb();
        await new Promise((res) => { const tx = db.transaction("kv", "readwrite"); tx.objectStore("kv").delete(k); tx.oncomplete = res; tx.onerror = res; });
      } catch (e) { try { localStorage.removeItem("kjp:" + k); } catch (e2) { delete mem[k]; } }
    }
    return { get, set, del };
  })();
  const prefs = {
    get(k, d) { try { const v = localStorage.getItem("kjp-pref:" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("kjp-pref:" + k, JSON.stringify(v)); } catch (e) { /* abaikan */ } },
  };

  // ------------------------------------------------------------------ state
  const S = {
    db: null, source: "bawaan", remote: null, shown: PAGE, excluded: new Set(), results: [], hiddenCount: 0,
    regex: [], persisted: null,
  };

  // ------------------------------------------------------------------ utilitas tampilan
  const nf0 = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 1 });
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function toast(msg, action) {
    const t = $("#toast"); $("#toast-text").textContent = msg;
    const b = $("#toast-btn");
    if (action) { b.hidden = false; b.textContent = action.label; b.onclick = () => { t.hidden = true; action.run(); }; } else { b.hidden = true; }
    t.hidden = false; clearTimeout(toast._t);
    toast._t = setTimeout(() => { t.hidden = true; }, action ? 12000 : 4200);
  }
  function fmtDate(iso) {
    try { return new Date(iso).toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" }); } catch (e) { return iso; }
  }
  function money(amount, cur) {
    if (cur === "IDR") return "Rp" + nf0.format(amount);
    return cur + " " + nf0.format(amount);
  }

  // ------------------------------------------------------------------ data jurnal
  function feeUSD(j) {
    if (j.fee_amount == null || !j.fee_currency) return null;
    const r = (S.db.fx_per_usd || {})[j.fee_currency];
    return r ? j.fee_amount / r : null;
  }
  function mid(j) { return (j.accept_months[0] + j.accept_months[1]) / 2; }
  function tierLabel(j) {
    switch (j.tier) {
      case "Q1": case "Q2": case "Q3": case "Q4": return "Scopus " + j.tier;
      case "Q?": return "Scopus";
      case "PROC": return "Prosiding Scopus";
      case "S?": return "SINTA ?";
      default: return j.sinta ? "SINTA " + j.sinta.slice(1) : (j.tier === "S12" ? "SINTA 1-2" : j.tier === "S34" ? "SINTA 3-4" : "SINTA 5-6");
    }
  }
  function tierClass(j) {
    if (j.tier === "Q1") return "tier q1";
    if (j.tier === "Q2") return "tier q2";
    if (j.tier.startsWith("S")) return "tier sinta";
    return "tier";
  }
  function feeLabel(j, cur) {
    if (j.tier === "PROC") return { v: "Ikut biaya konferensi", s: "" };
    if (j.fee_amount == null) return { v: "Belum pasti", s: "cek situs jurnal" };
    if (j.fee_amount === 0) {
      const hyb = /hybrid|langganan/i.test(j.access);
      return { v: hyb ? "Gratis (jalur langganan)" : "Gratis", s: hyb && j.oa_optional_usd ? "OA opsional USD " + nf0.format(j.oa_optional_usd) : "" };
    }
    const usd = feeUSD(j);
    const orig = money(j.fee_amount, j.fee_currency);
    let conv = "";
    if (usd != null) {
      if (cur === "IDR" && j.fee_currency !== "IDR") conv = "≈ Rp" + nf0.format(usd * (S.db.fx_per_usd.IDR || 16500));
      if (cur === "USD" && j.fee_currency !== "USD") conv = "≈ USD " + nf0.format(usd);
    }
    return { v: orig, s: conv };
  }
  const verified = (s) => /^Terverifikasi/i.test(s || "");

  // ------------------------------------------------------------------ kata kunci
  function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
  function buildRegex() {
    S.regex = Object.entries(S.db.taxonomy).map(([id, t]) => ({
      id, label: t.label, field: t.field,
      re: new RegExp("(^|[^a-z0-9])(" + t.terms.map((x) => escRe(x.toLowerCase())).join("|") + ")(?=[^a-z0-9]|$)", "i"),
    }));
  }
  function detect(text) {
    const s = " " + text.toLowerCase().replace(/[‐-―]/g, "-") + " ";
    return S.regex.filter((r) => r.re.test(s)).map((r) => r.id);
  }

  // ------------------------------------------------------------------ filter & skor
  const WEIGHTS = {
    balanced: { rel: 0.5, rep: 0.3, cost: 0.1, speed: 0.1 },
    rep: { rel: 0.4, rep: 0.45, cost: 0.05, speed: 0.1 },
    cheap: { rel: 0.4, rep: 0.2, cost: 0.3, speed: 0.1 },
    fast: { rel: 0.4, rep: 0.2, cost: 0.1, speed: 0.3 },
  };
  const REP = { Q1: 1, Q2: 0.8, Q3: 0.55, Q4: 0.35, "Q?": 0.5, PROC: 0.25, "S?": 0.25 };
  function repScore(j) {
    if (REP[j.tier] != null && !j.tier.startsWith("S")) return REP[j.tier];
    const lv = { S1: 0.55, S2: 0.5, S3: 0.38, S4: 0.3, S5: 0.22, S6: 0.15 }[j.sinta];
    if (lv) return lv;
    return { S12: 0.5, S34: 0.34, S56: 0.18 }[j.tier] || 0.25;
  }
  function costScore(j) {
    if (j.tier === "PROC") return 0.4;
    const u = feeUSD(j);
    if (j.fee_amount === 0) return 1;
    if (u == null) return 0.45;
    if (u <= 100) return 0.9;
    if (u <= 300) return 0.78;
    if (u <= 1000) return 0.55;
    if (u <= 2000) return 0.3;
    return 0.1;
  }
  function speedScore(j) {
    const m = mid(j);
    if (m <= 1.5) return 1; if (m <= 3) return 0.8; if (m <= 4.5) return 0.6; if (m <= 6) return 0.45; if (m <= 8) return 0.3;
    return 0.15;
  }

  function readForm() {
    const f = $("#filters");
    const fd = new FormData(f);
    return {
      q: $("#q").value,
      fields: $$("#field-chips .chip").filter((c) => c.getAttribute("aria-pressed") === "true").map((c) => c.dataset.field),
      tiers: fd.getAll("tier"),
      cost: fd.get("cost"), costMax: Number($("#cost-max").value), incUnknown: $("#inc-unknown").checked,
      wait: Number(fd.get("wait")), prio: fd.get("prio"), langId: $("#lang-id").checked, verified: $("#verified").checked,
      cur: fd.get("cur"),
    };
  }

  function compute() {
    const F = readForm();
    const tags = detect(F.q).filter((t) => !S.excluded.has(t));
    renderDetected(detect(F.q));
    const W = WEIGHTS[F.prio] || WEIGHTS.balanced;
    const tier = new Set(F.tiers);
    const out = [];
    let hidden = 0;
    for (const j of S.db.journals) {
      if (!tier.has(j.tier)) continue;
      if (F.fields.length && !j.fields.some((x) => F.fields.includes(x))) continue;
      const u = feeUSD(j);
      if (F.cost === "free" && j.fee_amount !== 0) continue;
      if (F.cost === "max") {
        if (j.fee_amount == null || j.tier === "PROC") { if (!F.incUnknown) continue; } else if (u > F.costMax) continue;
      }
      if (F.cost === "all" && !F.incUnknown && (j.fee_amount == null)) continue;
      if (F.verified && !verified(j.fee_status)) continue;
      if (F.wait && mid(j) > F.wait) continue;
      if (F.langId && !j.lang_id) continue;
      let rel, matched = [];
      if (tags.length) {
        matched = j.tags.filter((t) => tags.includes(t));
        if (!matched.length) { hidden++; continue; }
        const coverage = matched.length / tags.length;
        const precision = Math.min(1, (matched.length / j.tags.length) * 3);
        rel = 0.65 * coverage + 0.15 * precision + (j.maritime ? 0.2 : 0);
      } else {
        rel = j.maritime ? 0.75 : 0.5;
      }
      const parts = { rel, rep: repScore(j), cost: costScore(j), speed: speedScore(j) };
      const score = Math.round(100 * (W.rel * parts.rel + W.rep * parts.rep + W.cost * parts.cost + W.speed * parts.speed));
      out.push({ j, score, matched, parts });
    }
    out.sort((a, b) => b.score - a.score || b.parts.rep - a.parts.rep || a.j.name.localeCompare(b.j.name));
    S.results = out; S.hiddenCount = hidden; S.form = F; S.tags = tags;
    renderAdvSummary(F);
    savePrefs(F);
    renderResults();
  }

  // ------------------------------------------------------------------ render
  function renderAdvSummary(F) {
    const names = { H: "Hidrodinamika", D: "Desain", S: "Struktur", K: "Kendali & IoT" };
    const bits = [];
    bits.push(F.fields.length ? F.fields.map((f) => names[f]).join(", ") : "semua bidang");
    bits.push(F.tiers.length === 10 ? "semua indeksasi" : F.tiers.length + " tingkat indeksasi");
    bits.push(F.cost === "free" ? "gratis saja" : F.cost === "max" ? "biaya maks USD " + nf0.format(F.costMax) : "semua biaya");
    if (F.wait) bits.push("tunggu maks " + F.wait + " bln");
    bits.push({ balanced: "seimbang", rep: "utamakan reputasi", cheap: "utamakan hemat", fast: "utamakan cepat" }[F.prio]);
    $("#adv-sum").textContent = bits.join(" · ");
  }
  function renderDetected(all) {
    const box = $("#detected");
    if (!all.length) { box.innerHTML = '<span class="hint">Belum ada kata kunci yang dikenali.</span>'; return; }
    box.innerHTML = all.map((id) => {
      const t = S.db.taxonomy[id]; const off = S.excluded.has(id);
      return `<button type="button" class="chip${off ? " off" : ""}" data-tag="${id}" aria-pressed="${!off}" title="${off ? "Pakai lagi" : "Abaikan"}"><span class="fcode">${t.field}</span>${esc(t.label)}<span class="x" aria-hidden="true">${off ? "+" : "×"}</span></button>`;
    }).join("");
  }

  function reasons(r) {
    const j = r.j, out = [];
    r.matched.slice(0, 4).forEach((t) => out.push(`<span>${esc(S.db.taxonomy[t].label)}</span>`));
    if (j.maritime) out.push("<span>Jurnal khusus maritim</span>");
    if (j.fee_amount === 0) out.push("<span>Bisa terbit gratis</span>");
    if (mid(j) <= 2) out.push("<span>Proses cepat</span>");
    (S.db.picks[j.id] || []).slice(0, 2).forEach((p) => out.push(`<span class="pick">Pilihan kurasi: ${esc(p)}</span>`));
    return out.join("");
  }

  function card(r, i) {
    const j = r.j, F = S.form;
    const fee = feeLabel(j, F.cur);
    const m = j.accept_months, a = j.acceptance;
    const revOk = verified(j.review_status);
    const feeOk = verified(j.fee_status);
    return `<article class="card" data-id="${j.id}">
      <div class="rank">${i + 1}</div>
      <div class="card-main">
        <h3>${esc(j.name)}</h3>
        <div class="meta"><span class="${tierClass(j)}">${esc(tierLabel(j))}</span><span>${esc(j.publisher)}</span>
          <span class="fields" title="Bidang">${["H", "D", "S", "K"].map((f) => `<span class="${j.fields.includes(f) ? "on" : ""}">${f}</span>`).join("")}</span></div>
        <div class="stats">
          <div class="stat"><div class="k">Biaya</div><div class="v">${esc(fee.v)}</div><div class="s${feeOk ? " ok" : ""}">${feeOk ? "✓ terverifikasi" : esc(fee.s || (j.fee_amount == null ? "" : "pola penerbit"))}${feeOk && fee.s ? " · " + esc(fee.s) : ""}</div></div>
          <div class="stat"><div class="k">Submit sampai diterima</div><div class="v mono">${nf1.format(m[0])}-${nf1.format(m[1])} bln</div><div class="s${revOk ? " ok" : ""}">${revOk ? "✓ data jurnal" : "estimasi"}</div></div>
          <div class="stat"><div class="k">Acceptance rate</div><div class="v mono">${a[0] === a[1] ? a[0] + "%" : a[0] + "-" + a[1] + "%"}</div><div class="s${a[0] === a[1] ? " ok" : ""}">${a[0] === a[1] ? "✓ data jurnal" : "estimasi"}</div></div>
        </div>
        <div class="why">${reasons(r)}</div>
        <div class="card-actions">
          <a class="btn small" href="${esc(j.url)}" target="_blank" rel="noopener">Buka situs ↗</a>
          <button class="btn small" type="button" data-act="detail" aria-expanded="false">Detail</button>
          <button class="btn small ghost" type="button" data-act="report">Laporkan perubahan</button>
        </div>
      </div>
      <div class="score" title="Skor rekomendasi (0-100)"><b>${r.score}</b><div class="meter"><i style="width:${r.score}%"></i></div><small>skor</small></div>
      <div class="details" hidden></div>
    </article>`;
  }

  function detailHTML(j) {
    const rows = [
      ["Indeksasi", j.index], ["Kuartil Scopus", j.quartile ? `${j.quartile} (${j.quartile_src || "-"})` : null],
      ["Status SINTA", j.sinta_status], ["Penerbit", j.publisher], ["Negara", j.country], ["Bahasa naskah", j.lang],
      ["Model akses", j.access], ["Biaya (keterangan)", j.fee_text], ["Status data biaya", j.fee_status],
      ["Keputusan awal", j.first_decision], ["Status data review", j.review_status],
      ["ISSN", j.issn && j.issn.length ? j.issn.join(", ") : null],
      ["Kata kunci", j.tags.map((t) => S.db.taxonomy[t] ? S.db.taxonomy[t].label : t).join(", ")],
      ["Sumber verifikasi", j.sources], ["Catatan", j.note],
    ].filter((r) => r[1]);
    return `<dl>${rows.map((r) => `<dt>${esc(r[0])}</dt><dd>${esc(r[1])}</dd>`).join("")}</dl>`;
  }

  function renderResults() {
    const list = $("#list"), F = S.form;
    const n = S.results.length;
    const prioName = { balanced: "seimbang", rep: "reputasi", cheap: "hemat biaya", fast: "proses cepat" }[F.prio];
    $("#res-summary").innerHTML = n
      ? `<strong>${n}</strong> jurnal sesuai kriteria, diurutkan berdasarkan prioritas <strong>${prioName}</strong>.` +
        (S.tags.length ? ` Kata kunci: ${S.tags.map((t) => esc(S.db.taxonomy[t].label)).join(", ")}.` : "")
      : "Tidak ada jurnal yang memenuhi semua kriteria.";
    if (!n) {
      list.innerHTML = `<div class="empty"><p><strong>Belum ada yang cocok.</strong> Coba longgarkan batas biaya atau waktu tunggu, centang lebih banyak tingkat indeksasi, atau kurangi bidang yang dipilih.</p></div>`;
    } else {
      list.innerHTML = S.results.slice(0, S.shown).map(card).join("");
    }
    $("#btn-more").hidden = n <= S.shown;
    $("#btn-more").textContent = `Tampilkan ${Math.min(PAGE, n - S.shown)} lagi (dari ${n})`;
    const hn = $("#hidden-note");
    if (S.hiddenCount && S.tags.length) {
      hn.hidden = false;
      hn.textContent = `${S.hiddenCount} jurnal lain lolos filter tetapi tidak cocok dengan kata kunci naskah, jadi tidak ditampilkan. Kosongkan kotak kata kunci untuk melihat semuanya.`;
    } else hn.hidden = true;
  }

  // ------------------------------------------------------------------ status bar
  function renderStatus() {
    const on = navigator.onLine;
    $("#net-dot").className = "dot " + (on ? "on" : "off");
    $("#net-label").textContent = on ? "Online" : "Offline";
    const d = S.db;
    $("#db-label").textContent = `Data per ${fmtDate(d.generated)} · v${d.version} · ${d.journals.length} jurnal`;
    const seen = prefs.get("seenSeq", 0);
    $("#new-badge").hidden = !(d.seq > seen);
  }

  // ------------------------------------------------------------------ pembaruan
  function validDb(d) {
    return d && typeof d === "object" && Array.isArray(d.journals) && d.journals.length > 0 && typeof d.seq === "number" &&
      d.taxonomy && d.journals.every((j) => j.id && j.name && Array.isArray(j.tags) && Array.isArray(j.accept_months));
  }
  function updateUrl(name) { return new URL(CFG.updateBase + name, location.href).toString(); }

  async function checkUpdate(manual) {
    if (location.protocol === "file:") {
      if (manual) toast("Pembaruan hanya tersedia saat aplikasi dibuka dari alamat web (mis. GitHub Pages).");
      return;
    }
    if (!navigator.onLine) { if (manual) toast("Sedang offline. Aplikasi memakai data tersimpan."); return; }
    const btn = $("#btn-check"); btn.disabled = true; btn.textContent = "Memeriksa…";
    try {
      const r = await fetch(updateUrl("version.json") + "?t=" + Date.now(), { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const v = await r.json();
      prefs.set("lastCheck", new Date().toISOString());
      if (typeof v.seq === "number" && v.seq > S.db.seq) {
        S.remote = v;
        $("#update-text").innerHTML = `Database baru tersedia: <strong>v${esc(v.version)}</strong> (${fmtDate(v.generated)}), ${v.count} jurnal. ${esc(v.summary || "")}`;
        $("#update-banner").hidden = false;
      } else if (manual) {
        toast("Database sudah versi terbaru (v" + S.db.version + ").");
      }
    } catch (e) {
      if (manual) toast("Sumber pembaruan tidak dapat dihubungi. Aplikasi tetap memakai data tersimpan.");
    } finally {
      btn.disabled = false; btn.textContent = "Cek pembaruan";
    }
  }

  async function applyUpdate() {
    const btn = $("#btn-apply-update"); btn.disabled = true; btn.textContent = "Mengunduh…";
    try {
      const r = await fetch(updateUrl("journals.json") + "?t=" + Date.now(), { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      if (!validDb(d)) throw new Error("format");
      await adopt(d, "pembaruan online");
      $("#update-banner").hidden = true;
      toast(`Database diperbarui ke v${d.version}.`, { label: "Lihat perubahan", run: openChanges });
    } catch (e) {
      toast("Pembaruan gagal diunduh. Coba lagi nanti; data lama tetap dipakai.");
    } finally {
      btn.disabled = false; btn.textContent = "Perbarui sekarang";
    }
  }

  async function adopt(d, source) {
    const prevSeq = S.db ? S.db.seq : 0;
    S.db = d; S.source = source;
    await store.set("db", d);
    await store.set("dbSource", source);
    requestPersist();
    prefs.set("prevSeq", prevSeq);
    buildRegex(); fillDatalist(); renderStatus(); compute();
  }

  async function requestPersist() {
    try {
      if (navigator.storage && navigator.storage.persist) S.persisted = await navigator.storage.persist();
    } catch (e) { S.persisted = null; }
  }

  // ------------------------------------------------------------------ dialog: apa yang berubah
  function openChanges() {
    const seen = prefs.get("seenSeq", 0);
    const log = (S.db.changelog || []).slice().reverse();
    $("#changes-log").innerHTML = log.length ? log.map((c) => {
      const items = (c.items || []).map((it) => {
        if (it.type === "added") return `<li><span class="tag-add">Baru</span> ${esc(it.journal)}${it.detail ? " - " + esc(it.detail) : ""}</li>`;
        if (it.type === "removed") return `<li><span class="tag-del">Dihapus</span> ${esc(it.journal)}</li>`;
        if (it.type === "candidate") return `<li><span class="tag-chg">Kandidat</span> ${esc(it.journal)}${it.detail ? " - " + esc(it.detail) : ""}</li>`;
        return `<li><span class="tag-chg">${esc(it.field || "Berubah")}</span> ${esc(it.journal)}: ${esc(it.old)} → <strong>${esc(it.new)}</strong>${it.source ? ` <span class="hint">(${esc(it.source)})</span>` : ""}</li>`;
      }).join("");
      return `<div class="log-entry${c.seq > seen ? " fresh" : ""}"><h3>v${esc(c.version)} · ${esc(fmtDate(c.date))}</h3><p>${esc(c.summary || "")}</p>${items ? `<ul>${items}</ul>` : ""}</div>`;
    }).join("") : "<p>Belum ada catatan perubahan.</p>";
    prefs.set("seenSeq", S.db.seq);
    renderStatus();
    openDlg("#dlg-changes");
  }

  // ------------------------------------------------------------------ dialog: data
  async function openData() {
    const lastCheck = prefs.get("lastCheck", null);
    let persisted = S.persisted;
    try { if (navigator.storage && navigator.storage.persisted) persisted = await navigator.storage.persisted(); } catch (e) { /* abaikan */ }
    const rows = [
      ["Versi database", `v${S.db.version} (urutan ${S.db.seq})`], ["Tanggal data", fmtDate(S.db.generated)],
      ["Jumlah jurnal", S.db.journals.length], ["Asal data", S.source],
      ["Pembaruan terakhir dicek", lastCheck ? new Date(lastCheck).toLocaleString("id-ID") : "Belum pernah"],
      ["Sumber pembaruan", location.protocol === "file:" ? "Tidak tersedia (dibuka dari file lokal)" : updateUrl("version.json")],
      ["Penyimpanan permanen", persisted === true ? "Aktif" : persisted === false ? "Belum aktif (install aplikasi agar lebih awet)" : "Tidak diketahui"],
      ["Kurs", Object.entries(S.db.fx_per_usd).filter(([k]) => k !== "USD").map(([k, v]) => `1 USD = ${nf1.format(v)} ${k}`).join("; ") + ` (${S.db.fx_note || "asumsi"})`],
    ];
    $("#data-info").innerHTML = rows.map((r) => `<dt>${esc(r[0])}</dt><dd>${esc(r[1])}</dd>`).join("");
    $("#import-confirm").hidden = true; $("#reset-confirm").hidden = true;
    openDlg("#dlg-data");
  }

  async function saveFile(filename, text, mime) {
    if (window.claude && typeof window.claude.use === "function") {
      let dl = null;
      try { dl = await window.claude.use("downloads"); } catch (e) { dl = null; }
      if (!dl) { toast("Unduhan tidak tersedia di tampilan ini."); return; }
      try { await dl.save({ filename, data: text }); toast("File disiapkan: " + filename); }
      catch (e) { toast(e && e.code === "declined" ? "Penyimpanan dibatalkan." : "File tidak dapat disimpan di tampilan ini."); }
      return;
    }
    const blob = new Blob([text], { type: mime });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
    toast("File diunduh: " + filename);
  }

  function exportDb() {
    saveFile(`kompas-jurnal-v${S.db.version}.json`, JSON.stringify(S.db), "application/json");
  }

  function importDb(file) {
    const fr = new FileReader();
    fr.onload = () => {
      let d;
      try { d = JSON.parse(fr.result); } catch (e) { d = null; }
      const box = $("#import-confirm");
      if (!validDb(d)) {
        box.hidden = false;
        box.innerHTML = "<p>File ini bukan database Kompas Jurnal yang valid. Pilih file hasil <em>Ekspor database</em>.</p>";
        return;
      }
      const older = d.seq < S.db.seq;
      box.hidden = false;
      box.innerHTML = `<p>File berisi database <strong>v${esc(d.version)}</strong> (${d.journals.length} jurnal). ` +
        (older ? `Versi ini <strong>lebih lama</strong> daripada yang sedang dipakai (v${esc(S.db.version)}).` : "Versi ini sama atau lebih baru.") +
        ` Pakai database ini?</p><div class="row"><button class="btn primary" type="button" id="imp-yes">Pakai database ini</button><button class="btn" type="button" id="imp-no">Batal</button></div>`;
      $("#imp-yes").onclick = async () => { await adopt(d, "impor file"); box.hidden = true; closeDlg("#dlg-data"); toast("Database v" + d.version + " dipakai."); };
      $("#imp-no").onclick = () => { box.hidden = true; };
    };
    fr.readAsText(file);
  }

  async function resetDb() {
    await store.del("db"); await store.del("dbSource");
    S.db = window.__KJP_BUNDLED__; S.source = "bawaan";
    buildRegex(); fillDatalist(); renderStatus(); compute();
    closeDlg("#dlg-data"); toast("Kembali ke database bawaan v" + S.db.version + ".");
  }

  function exportCsv() {
    const F = S.form;
    const head = ["Peringkat", "Jurnal", "Tingkat", "Bidang", "Biaya", "Biaya (USD, kurs asumsi)", "Status biaya", "Submit-accept (bln)", "Acceptance (%)", "Skor", "Link"];
    const q = (v) => '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"';
    const rows = S.results.map((r, i) => {
      const j = r.j, u = feeUSD(j);
      return [i + 1, j.name, tierLabel(j), j.fields.join(""), feeLabel(j, F.cur).v, u == null ? "" : Math.round(u), j.fee_status,
        j.accept_months.join("-"), j.acceptance.join("-"), r.score, j.url].map(q).join(",");
    });
    saveFile("rekomendasi-jurnal.csv", "﻿" + head.map(q).join(",") + "\n" + rows.join("\n"), "text/csv");
  }

  // ------------------------------------------------------------------ dialog: laporan
  function fillDatalist() {
    $("#rp-journals").innerHTML = S.db.journals.map((j) => `<option value="${esc(j.name)}"></option>`).join("");
  }
  function openReport(j) {
    $("#rp-journal").value = j ? j.name : "";
    $("#rp-kind").selectedIndex = j ? 1 : 0;
    $("#rp-value").value = ""; $("#rp-source").value = ""; $("#rp-note").value = "";
    updateReport();
    openDlg("#dlg-report");
  }
  function reportText() {
    const j = S.db.journals.find((x) => x.name === $("#rp-journal").value.trim());
    const lines = [
      "Laporan perubahan - Kompas Jurnal Perkapalan",
      "Jurnal: " + ($("#rp-journal").value.trim() || "(belum diisi)"),
      "Data yang berubah: " + $("#rp-kind").value,
      "Nilai sekarang di database: " + (j ? `${tierLabel(j)}; biaya: ${j.fee_text}; link: ${j.url}` : "(tidak ada di database)"),
      "Nilai baru: " + ($("#rp-value").value.trim() || "-"),
      "Sumber: " + ($("#rp-source").value.trim() || "-"),
      "Catatan: " + ($("#rp-note").value.trim() || "-"),
      "Versi database: v" + S.db.version,
    ];
    return lines.join("\n");
  }
  function updateReport() {
    const txt = reportText();
    $("#rp-preview").textContent = txt;
    const gh = $("#rp-github");
    if (CFG.repo) {
      const p = new URLSearchParams({
        template: CFG.issueTemplate, title: `[Laporan] ${$("#rp-journal").value.trim() || "Jurnal"} - ${$("#rp-kind").value}`,
        jurnal: $("#rp-journal").value.trim(), jenis: $("#rp-kind").value, nilai: $("#rp-value").value.trim(),
        sumber: $("#rp-source").value.trim(), catatan: $("#rp-note").value.trim(),
      });
      gh.href = `https://github.com/${CFG.repo}/issues/new?${p.toString()}`;
      gh.hidden = false;
      $("#rp-hint").textContent = "Laporan masuk ke daftar usulan di GitHub. Setelah admin menyetujuinya, perubahan ikut pembaruan database berikutnya.";
    } else {
      gh.hidden = true;
      $("#rp-hint").textContent = "Sumber pembaruan belum dihubungkan ke GitHub. Salin laporan, lalu kirim ke admin database (atau tempel ke chat Claude).";
    }
  }
  async function copyReport() {
    const txt = reportText();
    try { await navigator.clipboard.writeText(txt); toast("Laporan disalin."); }
    catch (e) {
      const range = document.createRange(); range.selectNodeContents($("#rp-preview"));
      const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
      toast("Teks laporan sudah dipilih. Tekan Ctrl+C / Salin.");
    }
  }

  // ------------------------------------------------------------------ dialog helper
  function openDlg(sel) { const d = $(sel); if (typeof d.showModal === "function") { if (!d.open) d.showModal(); } else d.setAttribute("open", ""); }
  function closeDlg(sel) { const d = $(sel); if (typeof d.close === "function") d.close(); else d.removeAttribute("open"); }

  // ------------------------------------------------------------------ preferensi form
  const EXAMPLE = "Contoh: Optimasi bentuk lambung kapal ikan 30 GT menggunakan CFD untuk mengurangi hambatan dan konsumsi bahan bakar.";
  function savePrefs(F) {
    prefs.set("form", { q: F.q, fields: F.fields, tiers: F.tiers, cost: F.cost, costMax: F.costMax, incUnknown: F.incUnknown, wait: F.wait, prio: F.prio, langId: F.langId, verified: F.verified, cur: F.cur, excluded: Array.from(S.excluded) });
  }
  function loadPrefs() {
    const p = prefs.get("form", null);
    $("#q").value = p && typeof p.q === "string" ? p.q : EXAMPLE;
    if (!p) return;
    $$("#field-chips .chip").forEach((c) => c.setAttribute("aria-pressed", String((p.fields || []).includes(c.dataset.field))));
    $$('input[name="tier"]').forEach((c) => { c.checked = (p.tiers || []).includes(c.value); });
    const setRadio = (n, v) => { const el = $(`input[name="${n}"][value="${v}"]`); if (el) el.checked = true; };
    setRadio("cost", p.cost); setRadio("wait", p.wait); setRadio("prio", p.prio); setRadio("cur", p.cur);
    if (p.costMax != null) $("#cost-max").value = p.costMax;
    $("#inc-unknown").checked = p.incUnknown !== false; $("#lang-id").checked = !!p.langId; $("#verified").checked = !!p.verified;
    S.excluded = new Set(p.excluded || []);
  }
  function resetForm() {
    $("#filters").reset();
    $$("#field-chips .chip").forEach((c) => c.setAttribute("aria-pressed", "false"));
    $("#q").value = EXAMPLE; S.excluded = new Set();
    syncCost(); S.shown = PAGE; compute();
  }
  function syncCost() {
    const max = $('input[name="cost"]:checked').value === "max";
    $("#cost-range").hidden = !max;
    const v = Number($("#cost-max").value);
    const cur = $('input[name="cur"]:checked').value;
    $("#cost-out").textContent = cur === "IDR" ? "Rp" + nf0.format(v * ((S.db && S.db.fx_per_usd.IDR) || 16500)) + " (USD " + nf0.format(v) + ")" : "USD " + nf0.format(v);
  }

  // ------------------------------------------------------------------ service worker (hanya di hosting web biasa)
  function registerSW() {
    if (!("serviceWorker" in navigator) || location.protocol === "file:" || window.claude) return;
    navigator.serviceWorker.register("sw.js").then((reg) => {
      reg.addEventListener("updatefound", () => {
        const nw = reg.installing;
        if (!nw) return;
        nw.addEventListener("statechange", () => {
          if (nw.state === "installed" && navigator.serviceWorker.controller) {
            toast("Versi aplikasi baru siap.", { label: "Muat ulang", run: () => { nw.postMessage("skipWaiting"); } });
          }
        });
      });
    }).catch(() => { /* mode offline tidak tersedia; aplikasi tetap jalan */ });
    let reloaded = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => { if (!reloaded) { reloaded = true; location.reload(); } });
  }

  // ------------------------------------------------------------------ event
  function bind() {
    let tmr;
    $("#q").addEventListener("input", () => { clearTimeout(tmr); tmr = setTimeout(() => { S.shown = PAGE; compute(); }, 200); });
    $("#filters").addEventListener("change", (e) => { if (e.target.id === "q") return; syncCost(); S.shown = PAGE; compute(); });
    $("#filters").addEventListener("submit", (e) => e.preventDefault());
    $("#cost-max").addEventListener("input", () => { syncCost(); clearTimeout(tmr); tmr = setTimeout(compute, 120); });
    $("#field-chips").addEventListener("click", (e) => {
      const c = e.target.closest(".chip"); if (!c) return;
      c.setAttribute("aria-pressed", String(c.getAttribute("aria-pressed") !== "true")); S.shown = PAGE; compute();
    });
    $("#detected").addEventListener("click", (e) => {
      const c = e.target.closest(".chip"); if (!c) return;
      const t = c.dataset.tag; if (S.excluded.has(t)) S.excluded.delete(t); else S.excluded.add(t); compute();
    });
    $("#list").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-act]"); if (!b) return;
      const art = b.closest(".card"); const j = S.db.journals.find((x) => x.id === art.dataset.id);
      if (b.dataset.act === "detail") {
        const d = $(".details", art); const open = d.hidden;
        if (open && !d.innerHTML) d.innerHTML = detailHTML(j);
        d.hidden = !open; b.setAttribute("aria-expanded", String(open)); b.textContent = open ? "Tutup detail" : "Detail";
      } else if (b.dataset.act === "report") openReport(j);
    });
    $("#btn-more").addEventListener("click", () => { S.shown += PAGE; renderResults(); });
    $("#btn-reset").addEventListener("click", resetForm);
    $("#btn-suggest").addEventListener("click", () => openReport(null));
    $("#btn-csv").addEventListener("click", exportCsv);
    $("#btn-check").addEventListener("click", () => checkUpdate(true));
    $("#btn-changes").addEventListener("click", openChanges);
    $("#btn-data").addEventListener("click", openData);
    $("#btn-apply-update").addEventListener("click", applyUpdate);
    $("#btn-later").addEventListener("click", () => { $("#update-banner").hidden = true; });
    $("#btn-export").addEventListener("click", exportDb);
    $("#import-file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) importDb(f); e.target.value = ""; });
    $("#btn-reset-db").addEventListener("click", () => { $("#reset-confirm").hidden = false; });
    $("#btn-reset-no").addEventListener("click", () => { $("#reset-confirm").hidden = true; });
    $("#btn-reset-yes").addEventListener("click", resetDb);
    ["#rp-journal", "#rp-kind", "#rp-value", "#rp-source", "#rp-note"].forEach((s) => $(s).addEventListener("input", updateReport));
    $("#rp-copy").addEventListener("click", copyReport);
    $$("dialog [data-close]").forEach((b) => b.addEventListener("click", () => closeDlg("#" + b.closest("dialog").id)));
    $$("dialog").forEach((d) => d.addEventListener("click", (e) => { if (e.target === d) closeDlg("#" + d.id); }));
    window.addEventListener("online", () => { renderStatus(); checkUpdate(false); });
    window.addEventListener("offline", renderStatus);
  }

  // ------------------------------------------------------------------ mulai
  async function init() {
    const bundled = window.__KJP_BUNDLED__;
    let saved = null, savedSource = null;
    try { saved = await store.get("db"); savedSource = await store.get("dbSource"); } catch (e) { saved = null; }
    if (validDb(saved) && (!validDb(bundled) || saved.seq >= bundled.seq)) { S.db = saved; S.source = (savedSource || "tersimpan") + " (tersimpan di perangkat)"; }
    else if (validDb(bundled)) { S.db = bundled; S.source = "bawaan aplikasi"; }
    else { $("#res-summary").textContent = "Database tidak ditemukan. Pastikan file data/journals.js ada di samping aplikasi."; return; }
    buildRegex(); fillDatalist(); loadPrefs(); syncCost(); bind(); renderStatus();
    try { if (window.matchMedia("(max-width: 860px)").matches) $("#adv").open = false; } catch (e) { /* abaikan */ }
    compute();
    if (prefs.get("seenSeq", null) === null) prefs.set("seenSeq", S.db.seq);
    renderStatus();
    registerSW();
    checkUpdate(false);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
