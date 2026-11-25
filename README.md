# Edelweiss Prevention Intelligence — End-to-End v1.0 (Prototype lokal)

**Stack:** React + Vite + CSS clean/peach, FastAPI + Python, MySQL 8, scikit-learn K-Means K=3.

**Ditujukan untuk demonstrasi penelitian, bukan layanan diagnosis medis.** Data awal 63 kamar dan 315 penghuni merupakan data **sintetis/fiktif**. Data berisi informasi kesehatan individu memerlukan persetujuan, pembatasan akses, dan peninjauan petugas kesehatan sebelum penggunaan nyata.

## Mulai di Windows (XAMPP / phpMyAdmin)

Syarat: database `edelweiss_prevention_db` yang **sudah kamu impor sebelumnya**, Python 3.11+, Node.js 20+, MySQL aktif.

### A. Migrasi auth (sekali saja)

Di phpMyAdmin buka database `edelweiss_prevention_db` > **Import** > pilih `backend/sql/01_auth_sessions.sql` > Go. Skrip ini **tidak menghapus database**. Hasil: tabel baru `auth_sessions` (total 17 tabel bila sebelumnya 16).

**JANGAN** menjalankan ulang `Edelweiss_MySQL_Lengkap_63_Kamar_FINAL.sql` pada database berisi data yang ingin disimpan: skrip lama tersebut berisi DROP DATABASE.

### B. Jalankan backend (terminal pertama)

Buka folder `Edelweiss_End_to_End` di VS Code, lalu buka Terminal baru:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env` lalu isi `DB_HOST`, `DB_PORT`, `DB_NAME=edelweiss_prevention_db`, `DB_USER`, `DB_PASSWORD` sesuai XAMPP/MySQL kamu. Jangan unggah file `.env`.

Buat **admin pertama** (sekali saja, bila sebelumnya belum dibuat):

```powershell
.\.venv\Scripts\python.exe scripts\create_first_admin.py
```

Masukkan username, email, nama dan password minimal 12 karakter. Jika admin sudah ada dari versi login sebelumnya, **lewati** pembuatan admin.

Jalankan:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Cek `http://127.0.0.1:8000/api/health` dan `http://127.0.0.1:8000/docs`.

### C. Jalankan frontend React (terminal kedua)

Dari folder proyek utama, buka Terminal baru:

```powershell
cd frontend
npm install
npm run dev
```

Buka **http://127.0.0.1:5173** pada browser. **Login menggunakan akun admin yang dibuat sendiri.** Jangan mengisi password di chat.

Jika `npm` tidak dikenal, install Node.js LTS terlebih dahulu. Jika gagal terhubung MySQL, periksa Apache/MySQL di XAMPP dan pengaturan `.env`. Tidak perlu menyalakan Apache untuk FastAPI/React, tetapi MySQL harus aktif.

**Jangan tutup kedua terminal** selama menjalankan website. `Ctrl+C` menghentikan aplikasi, tidak menghapus file/database.

### D. Urutan demo end-to-end

1. Login sebagai Admin.
2. Beranda memuat 4 hall, 63 kamar, 315 penghuni dummy dari MySQL.
3. Peta Kamar menampilkan semua kamar; klik satu kamar untuk melihat ringkasannya.
4. Pemeriksaan Bulanan memperlihatkan kelengkapan tiap kamar.
5. Analisis K-Means > **Jalankan K-Means K=3** untuk mengolah 63 rekap yang sudah ada.
6. Analisis menampilkan centroid, Silhouette Score, dan hasil profil kamar.
7. Tindakan Pencegahan > buat tugas dan ubah statusnya (tersimpan di MySQL).
8. Laporan & Ekspor > unduh CSV rekap, kelompok, kelengkapan, dan tindakan.
9. Buat periode baru untuk menguji impor CSV dan input manual tanpa duplikasi.

#### Penting: Data awal sudah tersimpan

File `samples/import_dummy_63_kamar.csv` adalah data asli **dummy** yang sudah tersimpan di MySQL periode **2026-11**. Jika diimpor ulang ke 2026-11, sistem **benar-benar akan menolak duplikasi**. Ini benar. Untuk mendemokan impor, gunakan periode baru dengan penghuni dan tanggal yang valid, atau buat salinan **database pengujian**; jangan hapus data lama demi sekadar mencoba impor.

Untuk data baru, gunakan `samples/template_import_kosong.csv`. Kolom **harus persis sesuai template**, termasuk `resident_code`, `resident_name`, `input_source`, `room_id`, `period`, dan sebagainya. Preview menolak file yang tidak lengkap, nama tidak sesuai master, data ganda, atau periode yang terkunci. Google Forms diekspor sebagai CSV lalu disesuaikan mengikuti template. **Sinkronisasi Google API otomatis belum diimplementasikan.**

## Fitur yang terimplementasi

- Login/logout sesi HttpOnly + proteksi CSRF + hashing password Argon2id.
- Administrator dapat membuat akun petugas berdasarkan peran.
- Dashboard ringkasan, 63 kamar, 4 hall, kelengkapan dan daftar penghuni.
- Periode pemeriksaan bulanan; input pemeriksaan manual; preview & commit CSV/XLSX.
- Pencocokan kode dan nama penghuni, keanggotaan kamar, persetujuan dan deteksi duplikat.
- Verifikasi bukti kekebalan oleh akun ADMIN/PETUGAS_KESEHATAN (tidak otomatis dari form).
- Laporan kontak/dugaan kasus, pemeriksaan dan tindak lanjut khusus petugas berwenang.
- Rekap fitur per kamar (dengan versi), K-Means K=3, Silhouette Score, centroid dan hasil kelompok.
- Catatan tindak lanjut serta ekspor CSV.
- Data tersimpan di database MySQL yang sudah ada; tidak ada DROP/CREATE otomatis saat backend startup.

## Batasan penelitian

K-Means mengelompokkan kemiripan **profil indikator** (bukti kekebalan terverifikasi, intensitas interaksi dekat, jumlah penghuni), **bukan memprediksi probabilitas terinfeksi cacar air**. Tabel `cluster_assignments.risk_category` sengaja tetap `NULL` sampai interpretasi klinis tervalidasi. Frontend menampilkan `Profil 1/2/3`, bukan klaim diagnosis Rendah/Sedang/Tinggi. Laporan kasus/paparan harus diperiksa segera secara terpisah.

Pada dataset dummy, semua kamar tepat 5 orang sehingga fitur jumlah penghuni konstan; ini bukan bukti model mampu membedakan kepadatan. Model tidak divalidasi terhadap penularan nyata. Perubahan `history_verified`/`vaccine_verified` dari Google Form **diabaikan** sebagai bukti sampai diverifikasi petugas berwenang. Data demo awal sudah berisi simulasi verifikasi.

## Keamanan dan deployment

**Hanya untuk penggunaan lokal dan demonstrasi dengan data fiktif.** Penggunaan dengan data kesehatan nyata membutuhkan review keamanan, pengaturan HTTPS (COOKIE_SECURE=true), persetujuan, pemisahan hak akses lebih rinci, kebijakan retensi data, pembatasan log, backup, pengamanan server, pengujian integrasi dan evaluasi klinis. Jangan unggah database, kredensial, atau screenshot riwayat kesehatan individu ke layanan publik.

## Pengujian yang dapat dijalankan

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

Pengujian backend mencakup parsing 315 baris dummy dan perhitungan 3 cluster. Pengujian end-to-end terhadap MySQL laptop kamu perlu dilakukan secara lokal karena akses dari lingkungan pengembangan berbeda.

## Struktur folder

```
Edelweiss_End_to_End/
├── backend/
│   ├── app/ (API, sesi login, validasi CSV, K-Means)
│   ├── scripts/create_first_admin.py
│   ├── sql/01_auth_sessions.sql
│   └── requirements.txt
├── frontend/
│   ├── src/ (React, API client, CSS)
│   └── package.json
├── samples/ (CSV dummy dan template)
├── START_BACKEND.bat
└── START_FRONTEND.bat
```

## Troubleshooting singkat

- **401 Unauthorized:** belum login; masuk dari React pada port 5173.
- **403 Token CSRF:** refresh halaman atau login ulang.
- **503 login:** pastikan tabel `auth_sessions` sudah dibuat dan `.env` cocok.
- **CSV tidak bisa diimpor:** cek kode/nama penghuni, room membership, kolom header, periode, consent, dan duplikasi.
- **Port 8000 sudah digunakan:** hentikan Uvicorn lama (`Ctrl+C`), lalu nyalakan backend paket ini.
- **`npm install` gagal:** periksa Node.js dan koneksi internet/registry npm di komputermu.
