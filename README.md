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
(minimal 12 karakter). Akun `admin` akan dibuat; akun tambahan dapat dibuat dari menu *Pengguna*.

PowerShell lokal:
```powershell
$env:INITIAL_ADMIN_PASSWORD = "gunakan-password-kuat-minimal-12-karakter"
streamlit run app.py
```

## Deploy ke Streamlit Community Cloud
1. Buat PostgreSQL database (misalnya Supabase) dan simpan connection URL dengan SSL.
2. Push seluruh project ke repository GitHub. `data/`, `screenshots/`, dan file secrets lokal
   diabaikan oleh `.gitignore`; workbook seed `REPORT_DASHBOARD_CC.xlsx` tetap menjadi data awal.
3. Di Streamlit Community Cloud, deploy `app.py` dari repository tersebut.
4. Masukkan secrets berikut di pengaturan aplikasi Streamlit Cloud (jangan commit atau kirim
   connection URL/password lewat chat):
   ```toml
   [database]
   url = "postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"

   [app]
   initial_admin_password = "password-admin-kuat-minimal-12-karakter"
   ```
   `initial_admin_password` hanya digunakan saat tabel pengguna masih kosong. Setelah deploy,
   login dengan username `admin` dan password tersebut, lalu buat akun tambahan melalui menu
   *Pengguna*.
5. Untuk backup PostgreSQL, gunakan fitur backup dari penyedia database; export Excel aplikasi
   tetap tersedia untuk data dashboard.

Jika database lokal sudah berisi perubahan yang perlu dibawa ke hosting, ekspor/backup dulu dan
jangan unggah `data/dashboard.db` ke repository publik.

## Hak akses
| Menu                  | admin | user |
|-----------------------|:-----:|:----:|
| Dashboard             |  ✅   |  ✅  |
| Input Harian (nilai, complain platform, top kontributor) | ✅ | ✅ (tanpa hapus) |
| Kelola Indikator (tambah/edit/hapus, target, operator, logic trend) | ✅ | – |
| Teks & Pengaturan (isi sheet Config, auto-refresh, jadwal screenshot) | ✅ | – |
| Claim & Poin (total poin, tabel warna) | ✅ | – |
| Pengguna, Import/Export, Log Aktivitas | ✅ | – |
| Ganti Password        |  ✅   |  ✅  |

## Struktur file
- `app.py`      UI Streamlit: login, menu, CRUD
- `logic.py`    Port logika Code.gs + hitung warna/tren/format Index.html
- `render.py`   Render HTML dashboard (CSS persis dari Index.html di `style.css`)
- `db.py`       SQLite/PostgreSQL, autentikasi (PBKDF2), CRUD, rollover hari
- `importer.py` Import dari Excel (sheet Config, Dashboard, Prakiraan)
- `shots.py`    Screenshot di server (opsional, Playwright)

## Catatan perbedaan dengan versi Google Sheet
- Rumus `=TODAY()-N` diganti token `{HARI-N}` (mis. `{HARI-1}` = kemarin), tetap otomatis berganti tiap hari.
- Pergantian hari manual: menu *Input Harian → Pergantian hari* menggeser Hari Ini → Kemarin → 2 Hari Lalu.
- Config `ID Spreadsheet Sumber` / `Nama Sheet Sumber` tidak dipakai (khusus Google Sheet).
- Urutan seksi mengikuti kolom **No Seksi** (kecil di atas). Ubah angkanya di *Kelola Indikator* untuk memindah seksi.
- "Simpan ke Drive" diganti: tombol 📸 (unduh PNG di browser) dan screenshot server ke folder `screenshots/`.

## Screenshot di server / otomatis (opsional)
```bash
pip install playwright
playwright install chromium
```
Lalu aktifkan jadwal di menu *Teks & Pengaturan → Pengaturan aplikasi*.
