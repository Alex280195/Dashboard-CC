"""
Dashboard Performa Agen Harian - J&T Express (versi Python / Streamlit)

Jalankan:   streamlit run app.py
Login awal admin dibuat dari Streamlit Secret `app.initial_admin_password`.

Hak akses
  admin : semua menu (kelola indikator, teks, claim & poin, pengguna, import/export, log) + hapus data
  user  : lihat dashboard, input / ubah nilai harian, ganti password sendiri (tidak bisa menghapus data)
"""
import io
import os
import threading
import time
from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import db
import importer
import render
import shots

st.set_page_config(page_title='Dashboard Performa Agen Harian', page_icon='📊', layout='wide')
db.init()


# ---------------------------------------------------------------------------------------
# Screenshot otomatis terjadwal (thread latar; butuh Playwright, diatur di menu Teks & Pengaturan)
# ---------------------------------------------------------------------------------------
@st.cache_resource
def start_scheduler():
    def loop():
        last = ''
        while True:
            try:
                if db.get_setting('auto_enabled', '0') == '1':
                    now = datetime.now()
                    hm = now.strftime('%H:%M')
                    times = [t.strip() for t in db.get_setting('auto_times', '').split(',') if t.strip()]
                    key = now.strftime('%Y%m%d') + hm
                    if hm in times and key != last:
                        last = key
                        path = shots.save_screenshot(render.page_html(db.load_dashboard(), with_tools=False))
                        db.log_action('sistem', 'auto_screenshot', os.path.basename(path))
            except Exception as e:  # noqa: BLE001
                db.log_action('sistem', 'auto_screenshot_gagal', str(e)[:300])
            time.sleep(20)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


start_scheduler()


# ---------------------------------------------------------------------------------------
# Util UI
# ---------------------------------------------------------------------------------------
def me():
    return st.session_state['user']


def is_admin():
    return me()['role'] == 'admin'


def flash(msg, kind='success'):
    st.session_state['_flash'] = (kind, msg)


def show_flash():
    f = st.session_state.pop('_flash', None)
    if f:
        {'success': st.success, 'error': st.error, 'warning': st.warning}.get(f[0], st.info)(f[1])


def crud_editor(table, column_config, key, allow_delete, label):
    """Tabel yang bisa diedit langsung: ubah sel, tambah baris (baris kosong di bawah), hapus baris (centang lalu ikon tempat sampah)."""
    df = db.read(table)
    column_config = dict(column_config)
    column_config['id'] = st.column_config.NumberColumn('ID', disabled=True, format='%d')
    edited = st.data_editor(df, num_rows='dynamic', hide_index=True,
                            column_config=column_config, key=key)
    if not allow_delete:
        st.caption('Anda dapat menambah dan mengubah data. Penghapusan hanya bisa dilakukan admin.')
    if st.button('💾 Simpan perubahan', key=key + '_save', type='primary'):
        try:
            a, u, d = db.apply_changes(table, df, edited, allow_delete=allow_delete)
        except (ValueError, PermissionError) as e:
            st.error(str(e))
            return
        if a + u + d == 0:
            st.info('Tidak ada perubahan.')
            return
        db.log_action(me()['username'], f'{table}_simpan', f'{label}: +{a} ~{u} -{d}')
        flash(f'{label} tersimpan: {a} ditambah, {u} diubah, {d} dihapus.')
        st.rerun()


# ---------------------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------------------
def login_view():
    _, mid, _ = st.columns([1, 1.1, 1])
    with mid:
        st.markdown('### 📊 Dashboard Performa Agen Harian')
        st.caption('J&T Express · Agen Bandung — silakan login')
        if st.session_state.get('_fail', 0) >= 5 and time.time() < st.session_state.get('_lock', 0):
            st.error('Terlalu banyak percobaan gagal. Coba lagi dalam beberapa menit.')
            return
        with st.form('login'):
            u = st.text_input('Username')
            p = st.text_input('Password', type='password')
            ok = st.form_submit_button('Masuk', type='primary')
        if ok:
            user = db.verify_login(u, p)
            if user:
                st.session_state['user'] = user
                st.session_state['_fail'] = 0
                db.log_action(user['username'], 'login', '')
                st.rerun()
            else:
                st.session_state['_fail'] = st.session_state.get('_fail', 0) + 1
                if st.session_state['_fail'] >= 5:
                    st.session_state['_lock'] = time.time() + 300
                db.log_action((u or '?').strip()[:40], 'login_gagal', '')
                st.error('Username / password salah, atau akun nonaktif.')


# ---------------------------------------------------------------------------------------
# Halaman: Dashboard
# ---------------------------------------------------------------------------------------
def _dashboard_view():
    d = db.load_dashboard()
    html = render.page_html(d, with_tools=True)
    if hasattr(st, 'iframe'):                       # Streamlit baru: tinggi mengikuti isi
        st.iframe(html, height='content')
    else:                                           # Streamlit lama
        components.html(html, height=render.estimate_height_px(d), scrolling=True)


def page_dashboard():
    c1, c2, c3 = st.columns([1, 1.6, 4])
    if c1.button('🔄 Muat ulang'):
        st.rerun()
    if c2.button('📁 Simpan screenshot ke server'):
        try:
            with st.spinner('Mengambil screenshot…'):
                path = shots.save_screenshot(render.page_html(db.load_dashboard(), with_tools=False))
            db.log_action(me()['username'], 'screenshot', os.path.basename(path))
            st.success(f'Tersimpan: {path}')
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    c3.caption('Tombol 📸 di pojok kanan bawah dashboard = unduh PNG lewat browser.')
    sec = int(db.get_setting('refresh_sec', '120') or 0)
    st.fragment(_dashboard_view, run_every=sec if sec > 0 else None)()


# ---------------------------------------------------------------------------------------
# Halaman: Input harian (admin & user)
# ---------------------------------------------------------------------------------------
def page_input():
    st.subheader('✏️ Input Harian')
    t1, t2, t3 = st.tabs(['Nilai Indikator', 'Complain Platform', 'Top Kontributor Claim'])

    with t1:
        st.caption('Ubah angka langsung di tabel lalu klik Simpan. Kosongkan sel bila tidak ada data '
                   '(angka satuan % ditulis apa adanya, mis. 92.4 untuk 92,4%).')
        df = db.read_df('SELECT id, no_seksi, judul_seksi, indikator, satuan, hari_ini, bulan_ini, hari_sebelumnya, '
                        'dua_hari_lalu, hari_ini2 FROM indikator ORDER BY no_seksi, id')
        nc = lambda t, **k: st.column_config.NumberColumn(t, format='%.2f', **k)
        edited = st.data_editor(
            df, hide_index=True, num_rows='fixed', key='ed_daily',
            disabled=['id', 'no_seksi', 'judul_seksi', 'indikator', 'satuan'],
            column_config={'id': st.column_config.NumberColumn('ID', format='%d'),
                           'no_seksi': st.column_config.NumberColumn('No', format='%d'),
                           'judul_seksi': 'Seksi', 'indikator': 'Indikator', 'satuan': 'Satuan',
                           'hari_ini': nc('Hari Ini'), 'bulan_ini': nc('Bulan Ini'), 'hari_sebelumnya': nc('Hari Sebelumnya'),
                           'dua_hari_lalu': nc('2 Hari Lalu'), 'hari_ini2': nc('Hari Ini 2')})
        if st.button('💾 Simpan nilai harian', type='primary'):
            n = db.update_daily_values(df, edited)
            if n:
                db.log_action(me()['username'], 'input_harian', f'{n} indikator diperbarui')
                flash(f'{n} indikator diperbarui.')
                st.rerun()
            st.info('Tidak ada perubahan.')
        if is_admin():
            with st.expander('⏭ Pergantian hari (geser nilai)'):
                st.write('Memindahkan **Hari Ini → Hari Sebelumnya → 2 Hari Lalu** untuk semua indikator, '
                         'lalu mengosongkan Hari Ini. Lakukan sekali saat memulai hari baru.')
                if st.checkbox('Saya yakin ingin menggeser nilai hari', key='ck_roll') and st.button('Geser sekarang'):
                    db.rollover_day()
                    db.log_action(me()['username'], 'rollover', 'geser hari')
                    flash('Nilai hari sudah digeser. Isi nilai Hari Ini yang baru.')
                    st.rerun()

    with t2:
        cur = db.get_setting('complain_platform', '')
        val = st.number_input('Jumlah Complain Platform (hari ini)', min_value=0, step=1,
                              value=int(float(cur)) if cur not in ('', None) else 0)
        c_a, c_b = st.columns([1, 4])
        if c_a.button('💾 Simpan', key='sv_plat', type='primary'):
            db.set_setting('complain_platform', int(val))
            db.log_action(me()['username'], 'complain_platform', str(int(val)))
            flash('Complain Platform tersimpan.')
            st.rerun()
        if c_b.button('Kosongkan (sembunyikan di kartu)', key='clr_plat'):
            db.set_setting('complain_platform', '')
            flash('Complain Platform dikosongkan.')
            st.rerun()

    with t3:
        st.caption('Dashboard menampilkan 3 nominal terbesar untuk tiap jenis (Kategori / DP).')
        crud_editor('kontributor', {
            'jenis': st.column_config.SelectboxColumn('Jenis', options=['Kategori', 'DP'], required=True),
            'nama': 'Nama', 'sub': 'Keterangan / PIC',
            'nominal': st.column_config.NumberColumn('Nominal (Rp)', format='%d')}, 'ed_kon', is_admin(), 'Kontributor')


# ---------------------------------------------------------------------------------------
# Halaman admin
# ---------------------------------------------------------------------------------------
LOGIC_OPTS = ['Naik H, Turun M', 'Naik M, Turun H', 'TRUE', 'FALSE']


def page_indikator():
    st.subheader('🛠 Kelola Indikator')
    st.caption('Edit sel langsung · tambah baris baru di baris paling bawah · hapus: centang baris lalu klik ikon tempat sampah · '
               'lalu **Simpan perubahan**. Seksi diurutkan menurut "No Seksi".')
    with st.expander('➕ Tambah indikator lewat formulir'):
        with st.form('f_add_ind', clear_on_submit=True):
            a, b, c = st.columns(3)
            no = a.number_input('No Seksi', min_value=1, step=1, value=1)
            sec = b.text_input('Judul Seksi (mis. HOTLINE)')
            sec_cn = c.text_input('Judul Seksi (CN)')
            a, b, c = st.columns(3)
            nm = a.text_input('Indikator')
            ket = b.text_input('Keterangan')
            ik = c.text_input('Ikon (emoji)', value='📊')
            a, b, c, d_ = st.columns(4)
            op = a.selectbox('Operator', ['', '>=', '<='])
            tgt = b.number_input('Target', value=None, placeholder='kosong = tanpa target')
            sat = c.selectbox('Satuan', ['%', 'num', 'rp'])
            logic_ = d_.selectbox('Logic Trend', LOGIC_OPTS)
            a, b = st.columns(2)
            warna = a.color_picker('Warna garis', '#2f80ed')
            prev = b.text_input('Keterangan hari sebelumnya', value='{HARI-2}', help='{HARI-N} = tanggal N hari lalu, otomatis')
            if st.form_submit_button('Tambah', type='primary'):
                try:
                    db.insert_row('indikator', {'no_seksi': no, 'judul_seksi': sec, 'judul_seksi_cn': sec_cn, 'indikator': nm,
                                                'keterangan': ket, 'ket_hari_sebelumnya': prev, 'ikon': ik, 'operator': op,
                                                'target': tgt, 'satuan': sat, 'warna_garis': warna, 'tampil': 'Ya',
                                                'logic_trend': logic_})
                    db.log_action(me()['username'], 'indikator_tambah', nm)
                    flash(f'Indikator "{nm}" ditambahkan.')
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    num = lambda t, f='%.2f': st.column_config.NumberColumn(t, format=f)
    crud_editor('indikator', {
        'no_seksi': num('No Seksi', '%d'), 'judul_seksi': 'Judul Seksi', 'judul_seksi_cn': 'Judul Seksi (CN)',
        'indikator': 'Indikator', 'keterangan': 'Keterangan', 'ket_hari_sebelumnya': 'Ket. Hari Sebelumnya',
        'ikon': 'Ikon', 'operator': st.column_config.SelectboxColumn('Operator', options=['>=', '<=']),
        'target': num('Target'), 'hari_ini': num('Hari Ini'), 'bulan_ini': num('Bulan Ini'),
        'hari_sebelumnya': num('Hari Sebelumnya'), 'dua_hari_lalu': num('2 Hari Lalu'), 'warna_garis': 'Warna Garis',
        'satuan': st.column_config.SelectboxColumn('Satuan', options=['%', 'num', 'rp']), 'target2': num('Target 2'),
        'hari_ini2': num('Hari Ini 2'), 'tampil': st.column_config.SelectboxColumn('Tampil', options=['Ya', 'Tidak']),
        'logic_trend': st.column_config.SelectboxColumn('Logic Trend', options=LOGIC_OPTS)}, 'ed_ind', True, 'Indikator')


def page_config():
    st.subheader('⚙️ Teks & Pengaturan')
    t1, t2 = st.tabs(['Teks dashboard (Config)', 'Pengaturan aplikasi'])
    with t1:
        st.caption('Kolom **Isi** dipakai dashboard; untuk baris berawalan Label / Judul / Sub Judul / Teks, kolom **Ganti Isi** '
                   '(bila terisi) menggantikan Isi. Tanggal memakai token `{HARI-1}` = kemarin (otomatis).')
        crud_editor('config', {'nama': 'Nama', 'isi': 'Isi', 'ganti_isi': 'Ganti Isi (opsional)', 'catatan': 'Catatan'},
                    'ed_cfg', True, 'Config')
    with t2:
        with st.form('f_set'):
            sec = st.number_input('Auto-refresh dashboard (detik, 0 = mati)', min_value=0, step=30,
                                  value=int(db.get_setting('refresh_sec', '120') or 0))
            auto = st.checkbox('Aktifkan screenshot otomatis di server (butuh Playwright)',
                               value=db.get_setting('auto_enabled', '0') == '1')
            times = st.text_input('Jam screenshot otomatis (HH:MM dipisah koma)', value=db.get_setting('auto_times', '08:00,12:00,16:00'))
            if st.form_submit_button('💾 Simpan pengaturan', type='primary'):
                db.set_setting('refresh_sec', int(sec))
                db.set_setting('auto_enabled', '1' if auto else '0')
                db.set_setting('auto_times', times)
                db.log_action(me()['username'], 'pengaturan', f'refresh={sec}, auto={auto}, jam={times}')
                flash('Pengaturan tersimpan.')
                st.rerun()
        st.caption(f'Screenshot tersimpan di folder: {shots.SHOT_DIR}')


def page_claim():
    st.subheader('🏆 Claim & Poin')
    cur = db.get_setting('total_poin', '')
    c1, c2 = st.columns([1, 3])
    tp = c1.number_input('Total Point', step=0.5, value=float(cur) if cur not in ('', None) else None, placeholder='kosong')
    if c1.button('💾 Simpan Total Point', type='primary'):
        db.set_setting('total_poin', '' if tp is None else tp)
        db.log_action(me()['username'], 'total_poin', str(tp))
        flash('Total Point tersimpan.')
        st.rerun()
    st.markdown('**Tabel acuan warna & poin** — warna kartu Prakiraan Claim = tier dengan batas nominal terkecil yang masih ≥ nominal hari ini '
                '(di atas Target → merah).')
    crud_editor('poin_tier', {'label': 'Label', 'nominal': st.column_config.NumberColumn('Batas Nominal (Rp)', format='%d'),
                              'poin': st.column_config.NumberColumn('Poin', format='%.1f'), 'warna': 'Warna (#RRGGBB)'},
                'ed_tier', True, 'Tier poin')


def page_users():
    st.subheader('👤 Pengguna')
    users = db.list_users()
    st.dataframe(pd.DataFrame(users).rename(columns={'username': 'Username', 'role': 'Role', 'aktif': 'Aktif', 'dibuat': 'Dibuat'}),
                 hide_index=True)
    t1, t2 = st.tabs(['Tambah pengguna', 'Ubah / hapus'])
    with t1:
        with st.form('f_user_add', clear_on_submit=True):
            a, b, c = st.columns(3)
            un, pw, rl = a.text_input('Username'), b.text_input('Password (min. 6)', type='password'), c.selectbox('Role', ['user', 'admin'])
            if st.form_submit_button('Tambah', type='primary'):
                try:
                    db.add_user(un, pw, rl)
                    db.log_action(me()['username'], 'user_tambah', f'{un} ({rl})')
                    flash(f'Pengguna "{un}" dibuat.')
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    with t2:
        names = [u['username'] for u in users]
        sel = st.selectbox('Pilih pengguna', names)
        cur = next(u for u in users if u['username'] == sel)
        with st.form('f_user_edit'):
            a, b = st.columns(2)
            rl = a.selectbox('Role', ['user', 'admin'], index=0 if cur['role'] == 'user' else 1)
            ak = b.checkbox('Aktif', value=bool(cur['aktif']))
            npw = st.text_input('Password baru (kosongkan jika tidak diganti)', type='password')
            if st.form_submit_button('💾 Simpan', type='primary'):
                try:
                    if sel == me()['username'] and (rl != 'admin' or not ak):
                        raise ValueError('Anda tidak bisa menurunkan / menonaktifkan akun sendiri.')
                    db.update_user(sel, rl, ak)
                    if npw:
                        db.set_password(sel, npw)
                    db.log_action(me()['username'], 'user_ubah', f'{sel}: role={rl}, aktif={ak}, pw={"ganti" if npw else "-"}')
                    flash(f'Pengguna "{sel}" diperbarui.')
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        if sel != me()['username']:
            if st.checkbox(f'Saya yakin menghapus "{sel}"', key='ck_deluser') and st.button('🗑 Hapus pengguna'):
                try:
                    db.delete_user(sel)
                    db.log_action(me()['username'], 'user_hapus', sel)
                    flash(f'Pengguna "{sel}" dihapus.')
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


def _export_xlsx():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        for tbl, sheet in (('config', 'Config'), ('indikator', 'Dashboard'), ('kontributor', 'Kontributor'), ('poin_tier', 'Poin Claim')):
            db.read(tbl).drop(columns='id').to_excel(w, sheet_name=sheet, index=False)
    return buf.getvalue()


def page_io():
    st.subheader('📥 Import / Export')
    st.markdown('**Export**')
    c1, c2 = st.columns(2)
    c1.download_button('⬇️ Unduh data (.xlsx)', _export_xlsx(), f'export_dashboard_{datetime.now():%Y%m%d_%H%M}.xlsx',
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if db.is_sqlite():
        with open(db.DB_PATH, 'rb') as f:
            c2.download_button('⬇️ Backup database (.db)', f.read(), f'backup_dashboard_{datetime.now():%Y%m%d_%H%M}.db')
    else:
        c2.info('Database PostgreSQL dicadangkan melalui penyedia database. Gunakan export Excel untuk salinan data dashboard.')
    st.divider()
    st.markdown('**Import dari Excel** (format sama dengan `REPORT_DASHBOARD_CC.xlsx`: sheet Config, Dashboard, Prakiraan)')
    up = st.file_uploader('Pilih file .xlsx', type=['xlsx'])
    st.warning('Import **menimpa** seluruh Config, Indikator, Kontributor, dan Tier poin. Pengguna tidak terpengaruh. '
               'Unduh backup dulu bila perlu.')
    if up and st.checkbox('Saya mengerti, timpa data yang ada') and st.button('Import sekarang', type='primary'):
        try:
            with db.conn() as c:
                res = importer.import_xlsx(up, c, replace=True)
            db.log_action(me()['username'], 'import_xlsx', f'{up.name}: {res}')
            flash(f'Import selesai: {res["indikator"]} indikator, {res["config"]} config, '
                  f'{res["kontributor"]} kontributor, {res["tier"]} tier.')
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f'Import gagal: {e}')


def page_log():
    st.subheader('🕘 Log Aktivitas')
    st.dataframe(db.read_df('SELECT waktu AS Waktu, username AS Pengguna, aksi AS Aksi, detail AS Detail '
                            'FROM log ORDER BY id DESC LIMIT 300'), hide_index=True)


def page_password():
    st.subheader('🔑 Ganti Password')
    with st.form('f_pw'):
        old = st.text_input('Password lama', type='password')
        new = st.text_input('Password baru (min. 6)', type='password')
        new2 = st.text_input('Ulangi password baru', type='password')
        if st.form_submit_button('Simpan', type='primary'):
            if not db.verify_login(me()['username'], old):
                st.error('Password lama salah.')
            elif new != new2:
                st.error('Konfirmasi password tidak sama.')
            else:
                try:
                    db.set_password(me()['username'], new)
                    db.log_action(me()['username'], 'ganti_password', '')
                    st.success('Password berhasil diganti.')
                except ValueError as e:
                    st.error(str(e))


# ---------------------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------------------
PAGES_USER = {'📊 Dashboard': page_dashboard, '✏️ Input Harian': page_input, '🔑 Ganti Password': page_password}
PAGES_ADMIN = {'📊 Dashboard': page_dashboard, '✏️ Input Harian': page_input, '🛠 Kelola Indikator': page_indikator,
               '⚙️ Teks & Pengaturan': page_config, '🏆 Claim & Poin': page_claim, '👤 Pengguna': page_users,
               '📥 Import / Export': page_io, '🕘 Log Aktivitas': page_log, '🔑 Ganti Password': page_password}


def main():
    if 'user' not in st.session_state:
        login_view()
        return
    pages = PAGES_ADMIN if is_admin() else PAGES_USER
    with st.sidebar:
        st.markdown('### 📊 Dashboard Agen')
        st.caption(f'Masuk sebagai **{me()["username"]}** ({me()["role"]})')
        choice = st.radio('Menu', list(pages), label_visibility='collapsed')
        if st.button('🚪 Keluar'):
            db.log_action(me()['username'], 'logout', '')
            st.session_state.clear()
            st.rerun()
    show_flash()
    pages[choice]()


main()
