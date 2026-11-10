# Dashboard Performa Agen Harian (Python / Streamlit)

Port dari Google Apps Script (`Code.gs` + `Index.html`) ke Streamlit, dengan login admin/user
dan fitur input, edit, hapus data. Secara lokal data disimpan di SQLite (`data/dashboard.db`);
atur `DATABASE_URL` ke PostgreSQL untuk penyimpanan persisten di hosting.

## Menjalankan (VS Code)
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```
Saat pertama dijalankan, database dibuat otomatis dan diisi dari `REPORT_DASHBOARD_CC.xlsx`.
Pada database baru, buat password admin awal melalui environment variable `INITIAL_ADMIN_PASSWORD`
(minimal 12 karakter). Akun `admin` akan dibuat; akun tambahan dapat dibuat dari panel *Admin → Pengguna*.

PowerShell lokal:
```powershell
$env:INITIAL_ADMIN_PASSWORD = "gunakan-password-kuat-minimal-12-karakter"
streamlit run app.py
```

## Deploy ke Streamlit Community Cloud
1. Buat PostgreSQL database (misalnya Supabase) dan simpan connection URL dengan SSL.
2. Push seluruh project ke repository GitHub. `data/`, `screenshots/`, dan file secrets lokal
   diabaikan oleh `.gitignore`; workbook seed `REPORT_DASHBOARD_CC.xlsx` tetap menjadi data awal.
3. Sebelum menyalin database lokal, ganti password semua akun lokal dengan password kuat dan unik.
   Atur `DATABASE_URL` ke PostgreSQL tujuan di PowerShell, lalu jalankan:
   ```powershell
   $env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"
   python migrate_sqlite_to_postgres.py --confirm-user-passwords-changed
   ```
   Migrasi berhenti jika target sudah berisi data. Gunakan `--replace` hanya jika data tujuan
   memang boleh ditimpa. Jangan unggah `data/dashboard.db` ke repository publik.
4. Di Streamlit Community Cloud, deploy `app.py` dari repository tersebut.
5. Masukkan secrets berikut di pengaturan aplikasi Streamlit Cloud (jangan commit atau kirim
   connection URL/password lewat chat):
   ```toml
   [database]
   url = "postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"

   [app]
   initial_admin_password = "password-admin-kuat-minimal-12-karakter"
   ```
   `initial_admin_password` hanya digunakan saat tabel pengguna masih kosong. Setelah deploy,
   login dengan username `admin` dan password tersebut, lalu buat akun tambahan melalui panel
   *Admin → Pengguna*.
6. Untuk backup PostgreSQL, gunakan fitur backup dari penyedia database; export Excel aplikasi
   tetap tersedia untuk data dashboard.

## Satu halaman, semua fitur di dashboard
Tidak ada panel manual di bawah dashboard. Setelah login: **toolbar di atas dashboard**, tombolnya membuka jendela (pop-up) di atas dashboard.
- **admin**: ✏️ Edit (tabel lengkap tambah/edit/hapus + nilai harian cepat) · ➕ Tambah (form indikator baru) · 📥 Import Excel · 📤 Export/backup · ⏭ Ganti hari · 🏆 Claim · 🔤 Teks & pengaturan · ⚙️ Lainnya (pengguna, log, screenshot server, ganti password, muat ulang) · 🚪 Keluar.
- **Tombol langsung di dashboard** (Mode edit ON): ✏️ di pojok tiap kartu, ➕ Tambah indikator di tiap bar seksi, ✏️ Ubah di panel Claim/kontributor, ✏️ Ubah teks di header. *Mode edit: OFF* menyembunyikan semuanya untuk tampilan/screenshot.
- **user**: ✏️ Input nilai, 🏆 Claim (tanpa hapus), ⚙️ Lainnya (ganti password), 🚪 Keluar.

## Struktur file
- `app.py`      UI Streamlit: login + satu halaman (dashboard + panel edit)
- `logic.py`    Port logika Code.gs + hitung warna/tren/format Index.html
- `render.py`   Render HTML dashboard (CSS persis dari Index.html di `style.css`)
- `db.py`       SQLite/PostgreSQL, autentikasi (PBKDF2), CRUD, rollover hari
- `importer.py` Import dari Excel (sheet Config, Dashboard, Prakiraan)
- `migrate_sqlite_to_postgres.py` Salin database SQLite lokal ke PostgreSQL
- `shots.py`    Screenshot di server (opsional, Playwright)

## Catatan perbedaan dengan versi Google Sheet
- Rumus `=TODAY()-N` diganti token `{HARI-N}` (mis. `{HARI-1}` = kemarin), tetap otomatis berganti tiap hari.
- Pergantian hari manual: tombol *⏭ Ganti hari* di toolbar menggeser Hari Ini → Kemarin → 2 Hari Lalu.
- Config `ID Spreadsheet Sumber` / `Nama Sheet Sumber` tidak dipakai (khusus Google Sheet).
- Urutan seksi mengikuti kolom **No Seksi** (kecil di atas). Ubah angkanya di tabel Indikator untuk memindah seksi.
- "Simpan ke Drive" diganti: tombol 📸 (unduh PNG di browser) dan screenshot server ke folder `screenshots/`.

## Screenshot di server / otomatis (opsional)
```bash
pip install playwright
playwright install chromium
```
Lalu aktifkan jadwal di panel *Teks dashboard & pengaturan → Pengaturan aplikasi*.
