# Sumber data tambahan

## scimago.csv (opsional, setahun sekali)

Kuartil Scopus (SJR) diperbarui Scimago sekitar bulan Mei/Juni setiap tahun dan tidak tersedia lewat API.
Untuk memperbaruinya:

1. Buka https://www.scimagojr.com/journalrank.php , pilih *Subject Category* (mis. **Ocean Engineering**), atau
   biarkan semua kategori agar jurnal kendali/struktur ikut tercakup.
2. Klik **Download data** (file CSV, pemisah titik koma).
3. Ganti nama menjadi `scimago.csv` lalu unggah ke folder ini (tombol *Add file > Upload files* di GitHub).
4. Isi `scimago-year.txt` dengan tahun data (mis. `2025`).

Pembaruan otomatis berikutnya akan mencocokkan ISSN, mengusulkan perubahan kuartil, dan mendaftar jurnal
kelautan/perkapalan di file itu yang belum ada di database sebagai kandidat.
