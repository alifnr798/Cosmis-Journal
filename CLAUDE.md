# CLAUDE.md

## Konversi dokumen otomatis

Setiap kali ada file PDF, DOCX, PPTX, atau XLSX yang di-upload atau ditemukan dan belum punya versi `.md`:

1. Ubah ke Markdown pakai MarkItDown: `markitdown <file> -o <nama-file>.md`
2. Simpan hasil `.md` di folder yang sama dengan file aslinya.
3. Pakai file `.md` itu untuk membaca, meringkas, atau mengolah isinya.

Kalau `markitdown` belum terpasang, pasang dulu: `pip install -q 'markitdown[all]'`
