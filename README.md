# Kompas Jurnal Perkapalan

Aplikasi web untuk mencari jurnal Scopus dan SINTA yang cocok dengan naskah teknik perkapalan
(hidrodinamika, desain & produksi, struktur, kendali & IoT). Tetap bisa dipakai tanpa internet.
Saat online, aplikasi memeriksa dan mengunduh database terbaru.

- **Database awal:** 200 jurnal (140 Scopus, 56 SINTA, 4 prosiding), per 8 Oktober 2026.
- **Pembaruan otomatis:** setiap Senin, GitHub menarik data dari OpenAlex, DOAJ, Crossref, dan Scimago (opsional),
  lalu mengajukan perubahan sebagai *Pull Request*. Perubahan baru dipakai setelah Anda menyetujuinya.
- **Biaya hosting:** Rp0 (GitHub Pages + GitHub Actions gratis untuk repo publik).

---

## 1. Coba langsung tanpa GitHub

Buka `docs/index.html` di browser (klik dua kali). Aplikasi jalan dengan database bawaan.
Pada mode ini tombol *Cek pembaruan* tidak berfungsi karena aplikasi dibuka sebagai file lokal, bukan dari alamat web.

## 2. Pasang di GitHub Pages (sekali saja, ±15 menit)

1. Buat akun di https://github.com lalu klik **New repository**. Beri nama, misalnya `kompas-jurnal`,
   pilih **Public**, lalu klik **Create repository**.
2. Unggah isi folder ini lewat **uploading an existing file**. Folder `.github` ikut diunggah; kalau
   tersembunyi di komputer Anda, tampilkan file tersembunyi dulu, atau pakai aplikasi GitHub Desktop.
3. **Settings → Pages**: Source = *Deploy from a branch*, Branch = `main`, folder = `/docs`, lalu **Save**.
   Beberapa menit kemudian aplikasi bisa dibuka di `https://NAMA-ANDA.github.io/kompas-jurnal/`.
4. **Settings → Actions → General → Workflow permissions**: pilih *Read and write permissions* dan centang
   *Allow GitHub Actions to create and approve pull requests*, lalu **Save**.
5. (Disarankan) **Settings → Secrets and variables → Actions → Variables → New repository variable**:
   nama `CONTACT_EMAIL`, isi email Anda. OpenAlex dan Crossref melayani lebih cepat bila ada email kontak.
6. Edit `docs/config.js` (ikon pensil): isi `repo: "NAMA-ANDA/kompas-jurnal"`. Tombol **Kirim lewat GitHub**
   di formulir laporan akan aktif.
7. Uji pembaruan pertama: **Actions → Pembaruan otomatis database → Run workflow**.

## 3. Memasang aplikasi di HP atau laptop

Buka alamat GitHub Pages tadi:
- **Android/Chrome:** menu ⋮ → *Install app* / *Tambahkan ke layar utama*.
- **iPhone/Safari:** tombol Bagikan → *Add to Home Screen*.
- **Laptop/Chrome/Edge:** ikon install di kolom alamat.

Setelah sekali dibuka saat online, aplikasi bisa dipakai offline. Data hasil pembaruan disimpan di perangkat
dan tetap dipakai saat dibuka berikutnya. Gunakan **Data → Ekspor database** untuk cadangan atau memindahkan
data ke perangkat lain.

## 4. Cara kerja pembaruan

```
Senin 08:17 WIB   GitHub Actions menjalankan scripts/update_db.py
                  ├─ OpenAlex : cek ISSN, cari ISSN yang belum ada, APC indikatif, kandidat jurnal baru
                  ├─ DOAJ     : APC jurnal open access
                  ├─ Crossref : median waktu submit→diterima (untuk penerbit yang menyetor tanggalnya, mis. Springer)
                  └─ Scimago  : kuartil SJR (bila data-sources/scimago.csv tersedia)
                        │
                        ▼
                  Pull Request "Pembaruan database jurnal v…" berisi tabel perubahan,
                  daftar "Perlu ditinjau", dan kandidat jurnal baru
                        │  Anda klik Merge (= setuju)
                        ▼
                  GitHub Pages memperbarui docs/data/  (±1-2 menit)
                        │
                        ▼
                  Aplikasi pengguna yang online menampilkan banner "Database baru tersedia" → Perbarui
```

Aturan pengamannya:
- **Data yang dicek manual dari situs jurnal tidak ditimpa otomatis.** Kalau DOAJ atau OpenAlex berbeda,
  temuannya masuk bagian *Perlu ditinjau*.
- **ISSN yang namanya tidak cocok dengan OpenAlex diabaikan dan dilaporkan.**
- **Jurnal baru hanya diusulkan.** Anda yang memutuskan untuk menambahkannya.
- **Bila tidak ada perubahan data tetapi ada temuan,** GitHub membuat *Issue* tinjauan, bukan Pull Request.

## 5. Perubahan manual (SINTA, jurnal baru, koreksi)

Peringkat SINTA tidak tersedia lewat API, jadi diperbarui manual:

1. Buka `docs/data/journals.json` di GitHub, klik ikon pensil, ubah kolom yang perlu, lalu **Commit changes**.
2. Workflow **Rapikan database setelah edit manual** otomatis berjalan. Ia memeriksa format, menaikkan versi,
   mencatat perubahan di *Apa yang berubah*, dan membuat ulang `journals.js` dan `version.json`.
   Kalau ada salah ketik, workflow gagal dan menjelaskan baris yang salah di tab **Actions**.

Laporan dari pengguna masuk sebagai *Issue* lewat tombol **Laporkan perubahan** di aplikasi.

### Kolom penting tiap jurnal

| Kolom | Isi |
|---|---|
| `tier` | `Q1` `Q2` `Q3` `Q4` `Q?` (Scopus), `S12` `S34` `S56` `S?` (SINTA), `PROC` (prosiding) |
| `sinta` | `S1`–`S6` atau `null` |
| `fields` | gabungan `H` (hidrodinamika), `D` (desain/produksi), `S` (struktur), `K` (kendali & IoT) |
| `tags` | kata kunci dari daftar `taxonomy` di bagian atas file |
| `fee_amount`, `fee_currency` | biaya wajib (0 = gratis, `null` = belum pasti); mata uang harus ada di `fx_per_usd` |
| `fee_status` | mulai dengan `Terverifikasi (situs jurnal)` bila dicek manual, supaya tidak ditimpa otomatis |
| `accept_months` | `[min, maks]` bulan dari submit sampai diterima |
| `acceptance` | `[min, maks]` persen; nilai sama (mis. `[14, 14]`) ditampilkan sebagai data resmi |
| `issn` | daftar ISSN; dipakai untuk mencocokkan data otomatis |

Kurs ada di `fx_per_usd` (1 USD = … mata uang lain); ubah bila perlu.

## 6. Kuartil Scopus tahunan

Lihat `data-sources/README.md`. Unduh CSV dari scimagojr.com setahun sekali, unggah sebagai
`data-sources/scimago.csv`, dan pembaruan berikutnya akan mengusulkan perubahan kuartil.

## 7. Batasan yang perlu diketahui

- **Acceptance rate** hampir tidak pernah dipublikasikan penerbit. Kecuali yang ditandai "data jurnal", angkanya estimasi.
- **Waktu tunggu** baru dihitung otomatis untuk penerbit yang menyetor tanggal diterima ke Crossref. Selebihnya estimasi.
- **APC dari OpenAlex** bersifat indikatif. Untuk jurnal hybrid, angka itu adalah biaya opsional open access, bukan biaya wajib.
- **SINTA dan kuartil berubah setiap tahun.** Cek ulang di sinta.kemdiktisaintek.go.id dan Scopus sebelum submit.

## 8. Untuk pengembang

| Path | Fungsi |
|---|---|
| `docs/` | Aplikasi yang di-hosting (`index.html`, `app.js`, `sw.js`, `config.js`, `data/`) |
| `src/` | Sumber `page.html` dan `app.js`. Jalankan `python tools/build_app.py` untuk menyalinnya ke `docs/` |
| `scripts/update_db.py` | Pembaruan otomatis (`--dry-run` untuk laporan saja) |
| `scripts/finalize_db.py` | Validasi + versi + changelog setelah edit manual |
| `scripts/dbtools.py` | Fungsi bersama (hash, diff, bump versi, tulis `journals.js` dan `version.json`) |
| `tests/` | `test_update.py` (logika pembaruan, tanpa internet), `ui_flow.py` dan `ui_smoke.py` (uji browser, Playwright) |

Setiap kali mengubah `index.html` atau `app.js`, naikkan nomor `SHELL` di `docs/sw.js` (mis. `kjp-shell-v2`).
Dengan begitu, aplikasi yang sudah terpasang menampilkan tombol *Muat ulang* untuk versi baru.
