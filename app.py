"""
Dashboard Performa Agen Harian - J&T Express (versi Python / Streamlit)

Jalankan:   streamlit run app.py
Login awal admin dibuat dari Streamlit Secret `app.initial_admin_password`.

Satu halaman: toolbar + dashboard; semua fitur edit/tambah/import terbuka sebagai dialog.
  admin : tabel indikator lengkap (tambah/edit/hapus), claim, teks, pengguna, import/export, log
  user  : ubah nilai harian & claim, ganti password sendiri (tidak bisa menghapus data)
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
    html = render.page_html(d, with_tools=True, editable=bool(st.session_state.get('edit_mode', True)),
                            menu=menu_items(), user=f"{me()['username']} ({me()['role']})")
    if hasattr(st, 'iframe'):                       # Streamlit baru: tinggi mengikuti isi
        st.iframe(html, height='content')
    else:                                           # Streamlit lama
        components.html(html, height=render.estimate_height_px(d), scrolling=True)


def page_dashboard():
    sec = int(db.get_setting('refresh_sec', '120') or 0)
    st.fragment(_dashboard_view, run_every=sec if sec > 0 else None)()


# ---------------------------------------------------------------------------------------
# Panel edit (satu pintu, di bawah dashboard)
# ---------------------------------------------------------------------------------------
def section_values():
    """Grid nilai harian (untuk user; admin memakai grid lengkap di section_indikator)."""
    st.caption('Ubah angka langsung di tabel lalu klik Simpan. Kosongkan sel bila tidak ada data '
               '(satuan % ditulis apa adanya, mis. 92.4 untuk 92,4%).')
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


def section_claim_inputs():
    st.markdown('**Jumlah Complain Platform (hari ini)**')
    cur = db.get_setting('complain_platform', '')
    val = st.number_input('Complain Platform', min_value=0, step=1, label_visibility='collapsed',
                          value=int(float(cur)) if cur not in ('', None) else 0)
    c_a, c_b, _ = st.columns([1, 2, 4])
    if c_a.button('💾 Simpan', key='sv_plat', type='primary'):
        db.set_setting('complain_platform', int(val))
        db.log_action(me()['username'], 'complain_platform', str(int(val)))
        flash('Complain Platform tersimpan.')
        st.rerun()
    if c_b.button('Kosongkan (sembunyikan di kartu)', key='clr_plat'):
        db.set_setting('complain_platform', '')
        flash('Complain Platform dikosongkan.')
        st.rerun()
    st.markdown('**Top Kontributor Claim** — dashboard menampilkan 3 nominal terbesar per jenis.')
    crud_editor('kontributor', {
        'jenis': st.column_config.SelectboxColumn('Jenis', options=['Kategori', 'DP'], required=True),
        'nama': 'Nama', 'sub': 'Keterangan / PIC',
        'nominal': st.column_config.NumberColumn('Nominal (Rp)', format='%d')}, 'ed_kon', is_admin(), 'Kontributor')


# ---------------------------------------------------------------------------------------
# Halaman admin
# ---------------------------------------------------------------------------------------
LOGIC_OPTS = ['Naik H, Turun M', 'Naik M, Turun H', 'TRUE', 'FALSE']


def section_indikator():
    st.caption('Edit sel langsung · **tambah** = isi baris kosong paling bawah · **hapus** = centang baris lalu ikon tempat sampah · '
               'lalu **Simpan perubahan**. Seksi diurutkan menurut "No Seksi". Operator kosong = tanpa target. '
               'Ket. Hari Sebelumnya boleh pakai {HARI-2}.')
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


def section_card(row_id):
    """Form edit satu indikator (dibuka dengan klik kartu di dashboard)."""
    df = db.read_df('SELECT * FROM indikator WHERE id=?', (int(row_id),))
    if df.empty:
        st.warning('Indikator tidak ditemukan (mungkin sudah dihapus).')
        return
    r = df.iloc[0].to_dict()
    nv = lambda k: None if (r.get(k) is None or pd.isna(r.get(k))) else float(r[k])
    tx = lambda k: '' if (r.get(k) is None or (isinstance(r.get(k), float) and pd.isna(r.get(k)))) else str(r[k])
    admin = is_admin()
    st.caption(f'**{tx("judul_seksi")}** · {tx("indikator")}')
    num = lambda lbl, k, col: col.number_input(lbl, value=nv(k), placeholder='kosong', format='%.2f', key=f'cd_{row_id}_{k}')
    with st.form(f'f_card_{row_id}'):
        v = {}
        if admin:
            c1, c2, c3 = st.columns([1, 2, 2])
            v['no_seksi'] = c1.number_input('No Seksi', value=int(nv('no_seksi') or 1), step=1, format='%d', key=f'cd_{row_id}_no')
            v['judul_seksi'] = c2.text_input('Judul Seksi', tx('judul_seksi'))
            v['judul_seksi_cn'] = c3.text_input('Judul Seksi (CN)', tx('judul_seksi_cn'))
            c1, c2 = st.columns(2)
            v['indikator'] = c1.text_input('Indikator', tx('indikator'))
            v['keterangan'] = c2.text_input('Keterangan', tx('keterangan'))
            c1, c2, c3, c4 = st.columns(4)
            v['ikon'] = c1.text_input('Ikon', tx('ikon'))
            sat = ['%', 'num', 'rp']
            v['satuan'] = c2.selectbox('Satuan', sat, index=sat.index(tx('satuan')) if tx('satuan') in sat else 0)
            ops = ['(tanpa target)', '>=', '<=']
            op = c3.selectbox('Operator target', ops, index=ops.index(tx('operator')) if tx('operator') in ops else 0)
            v['operator'] = None if op.startswith('(') else op
            v['tampil'] = c4.selectbox('Tampil', ['Ya', 'Tidak'], index=1 if tx('tampil') == 'Tidak' else 0)
            c1, c2 = st.columns(2)
            v['target'] = num('Target', 'target', c1)
            v['target2'] = num('Target 2', 'target2', c2)
        c1, c2, c3 = st.columns(3)
        v['hari_ini'] = num('Hari Ini', 'hari_ini', c1)
        v['hari_ini2'] = num('Hari Ini 2', 'hari_ini2', c2)
        v['bulan_ini'] = num('Bulan Ini', 'bulan_ini', c3)
        c1, c2 = st.columns(2)
        v['hari_sebelumnya'] = num('Hari Sebelumnya', 'hari_sebelumnya', c1)
        v['dua_hari_lalu'] = num('2 Hari Lalu', 'dua_hari_lalu', c2)
        if admin:
            c1, c2, c3 = st.columns([1, 1, 2])
            col0 = tx('warna_garis')
            v['warna_garis'] = c1.color_picker('Warna garis', col0 if len(col0) == 7 and col0.startswith('#') else '#2f6fe0')
            lo = LOGIC_OPTS
            v['logic_trend'] = c2.selectbox('Logic Trend', lo, index=lo.index(tx('logic_trend')) if tx('logic_trend') in lo else 0)
            v['ket_hari_sebelumnya'] = c3.text_input('Ket. Hari Sebelumnya', tx('ket_hari_sebelumnya'))
        if st.form_submit_button('💾 Simpan', type='primary'):
            try:
                if admin:
                    db.update_row('indikator', row_id, v)
                else:
                    db.update_row('indikator', row_id, v, only=['hari_ini', 'hari_ini2', 'bulan_ini',
                                                                 'hari_sebelumnya', 'dua_hari_lalu'])
            except ValueError as e:
                st.error(str(e))
            else:
                db.log_action(me()['username'], 'indikator_ubah', f'{tx("judul_seksi")} / {tx("indikator")}')
                flash(f'Indikator "{tx("indikator")}" tersimpan.')
                st.rerun()
    if admin:
        with st.expander('🗑 Hapus indikator ini'):
            if st.checkbox('Saya yakin ingin menghapus', key=f'cd_del_ck_{row_id}') and st.button('Hapus', key=f'cd_del_{row_id}'):
                db.delete_row('indikator', row_id)
                db.log_action(me()['username'], 'indikator_hapus', f'{tx("judul_seksi")} / {tx("indikator")}')
                flash(f'Indikator "{tx("indikator")}" dihapus.')
                st.rerun()


def section_rollover():
    st.write('Memindahkan **Hari Ini → Hari Sebelumnya → 2 Hari Lalu** untuk semua indikator, lalu mengosongkan Hari Ini.')
    if st.checkbox('Saya yakin ingin menggeser nilai hari', key='ck_roll') and st.button('Geser sekarang', type='primary'):
        db.rollover_day()
        db.log_action(me()['username'], 'rollover', 'geser hari')
        flash('Nilai hari sudah digeser. Isi nilai Hari Ini yang baru.')
        st.rerun()


def section_tambah():
    """Form tambah indikator baru (tanpa perlu mengisi baris kosong di tabel)."""
    ind = db.read('indikator')
    secs = (ind[['no_seksi', 'judul_seksi', 'judul_seksi_cn']].drop_duplicates('judul_seksi')
            .sort_values('no_seksi').to_dict('records')) if len(ind) else []
    NEW = '➕ Seksi baru…'
    opts = [f"{int(x['no_seksi'])}. {x['judul_seksi']}" for x in secs] + [NEW]
    pre = st.session_state.get('tambah_sec')
    idx = next((i for i, x in enumerate(secs) if int(x['no_seksi']) == pre), 0)
    pick = st.selectbox('Seksi', opts, index=idx)
    if pick == NEW:
        c1, c2, c3 = st.columns([1, 2, 2])
        no_seksi = c1.number_input('No Seksi', min_value=1, step=1, value=int(ind['no_seksi'].max() + 1) if len(ind) else 1)
        judul = c2.text_input('Judul Seksi')
        judul_cn = c3.text_input('Judul Seksi (CN)')
    else:
        x = secs[[f"{int(y['no_seksi'])}. {y['judul_seksi']}" for y in secs].index(pick)]
        no_seksi, judul, judul_cn = int(x['no_seksi']), x['judul_seksi'], x['judul_seksi_cn']
    with st.form('f_tambah', clear_on_submit=True):
        c1, c2 = st.columns(2)
        nama = c1.text_input('Indikator *')
        ket = c2.text_input('Keterangan')
        c1, c2, c3, c4 = st.columns(4)
        ikon = c1.text_input('Ikon (emoji)')
        satuan = c2.selectbox('Satuan', ['%', 'num', 'rp'])
        operator = c3.selectbox('Operator target', ['(tanpa target)', '>=', '<='])
        tampil = c4.selectbox('Tampil', ['Ya', 'Tidak'])
        nn = lambda lbl, col: col.number_input(lbl, value=None, placeholder='kosong', format='%.2f')
        c1, c2, c3 = st.columns(3)
        target, target2, bulan = nn('Target', c1), nn('Target 2', c2), nn('Bulan Ini', c3)
        c1, c2, c3, c4 = st.columns(4)
        hi, hi2, hs, dl = nn('Hari Ini', c1), nn('Hari Ini 2', c2), nn('Hari Sebelumnya', c3), nn('2 Hari Lalu', c4)
        c1, c2, c3 = st.columns([1, 1, 2])
        warna = c1.color_picker('Warna garis', '#2f6fe0')
        logic_t = c2.selectbox('Logic Trend', LOGIC_OPTS)
        ket_prev = c3.text_input('Ket. Hari Sebelumnya', placeholder='mis. {HARI-1}')
        if st.form_submit_button('➕ Tambah indikator', type='primary'):
            try:
                db.insert_row('indikator', {
                    'no_seksi': no_seksi, 'judul_seksi': judul, 'judul_seksi_cn': judul_cn, 'indikator': nama,
                    'keterangan': ket, 'ket_hari_sebelumnya': ket_prev, 'ikon': ikon,
                    'operator': None if operator.startswith('(') else operator, 'target': target, 'hari_ini': hi,
                    'bulan_ini': bulan, 'hari_sebelumnya': hs, 'dua_hari_lalu': dl, 'warna_garis': warna,
                    'satuan': satuan, 'target2': target2, 'hari_ini2': hi2, 'tampil': tampil, 'logic_trend': logic_t})
            except ValueError as e:
                st.error(str(e))
            else:
                db.log_action(me()['username'], 'indikator_tambah', f'{judul} / {nama}')
                flash(f'Indikator "{nama}" ditambahkan ke seksi {judul}.')
                st.rerun()


def page_config():
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


def section_export():
    c1, c2 = st.columns(2)
    c1.download_button('⬇️ Unduh data (.xlsx)', _export_xlsx(), f'export_dashboard_{datetime.now():%Y%m%d_%H%M}.xlsx',
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', use_container_width=True)
    if db.is_sqlite():
        with open(db.DB_PATH, 'rb') as f:
            c2.download_button('⬇️ Backup database (.db)', f.read(), f'backup_dashboard_{datetime.now():%Y%m%d_%H%M}.db',
                               use_container_width=True)
    else:
        c2.info('Database PostgreSQL dicadangkan melalui penyedia database. Gunakan export Excel untuk salinan data dashboard.')


def section_import():
    st.caption('Format sama dengan `REPORT_DASHBOARD_CC.xlsx` (sheet Config, Dashboard, Prakiraan).')
    up = st.file_uploader('Pilih file .xlsx', type=['xlsx'])
    st.warning('Import **menimpa** seluruh Config, Indikator, Kontributor, dan Tier poin. Pengguna tidak terpengaruh. '
               'Unduh backup (Export) dulu bila perlu.')
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
    st.markdown('**Log aktivitas**')
    st.dataframe(db.read_df('SELECT waktu AS Waktu, username AS Pengguna, aksi AS Aksi, detail AS Detail '
                            'FROM log ORDER BY id DESC LIMIT 300'), hide_index=True)


def page_password():
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
# Satu halaman: toolbar di atas dashboard; setiap fitur terbuka sebagai jendela (dialog) di atas dashboard
# ---------------------------------------------------------------------------------------
@st.dialog('✏️ Edit data dashboard', width='large')
def dlg_edit():
    if is_admin():
        t1, t2 = st.tabs(['Semua kolom (tambah / edit / hapus)', 'Nilai harian (cepat)'])
        with t1:
            section_indikator()
        with t2:
            section_values()
    else:
        section_values()


@st.dialog('➕ Tambah indikator', width='large')
def dlg_tambah():
    section_tambah()


@st.dialog('✏️ Edit indikator', width='large')
def dlg_card(row_id):
    section_card(row_id)


@st.dialog('🏆 Edit Prakiraan Claim', width='large')
def dlg_claim_card(row_id):
    t1, t2 = st.tabs(['Nilai kartu', 'Kontributor, poin & warna'])
    with t1:
        section_card(row_id)
    with t2:
        section_claim_inputs()
        if is_admin():
            st.divider()
            page_claim()


@st.dialog('📥 Import dari Excel', width='large')
def dlg_import():
    section_import()


@st.dialog('📤 Export / backup', width='large')
def dlg_export():
    section_export()


@st.dialog('⏭ Pergantian hari')
def dlg_rollover():
    section_rollover()


@st.dialog('🏆 Claim: Complain Platform, Top Kontributor, Total Point & warna', width='large')
def dlg_claim():
    section_claim_inputs()
    if is_admin():
        st.divider()
        page_claim()


@st.dialog('🔤 Teks dashboard & pengaturan', width='large')
def dlg_teks():
    page_config()


@st.dialog('👥 Pengguna', width='large')
def dlg_users():
    page_users()


@st.dialog('📜 Log aktivitas', width='large')
def dlg_log():
    page_log()


@st.dialog('🔑 Ganti password saya')
def dlg_password():
    page_password()


def do_screenshot():
    try:
        with st.spinner('Mengambil screenshot…'):
            path = shots.save_screenshot(render.page_html(db.load_dashboard(), with_tools=False))
        db.log_action(me()['username'], 'screenshot', os.path.basename(path))
        flash(f'Screenshot tersimpan: {path}')
    except Exception as e:  # noqa: BLE001
        flash(str(e), 'error')


_CSS = """<style>
.st-key-hidden_edit_btns{position:absolute;left:-9999px;top:0;width:1px;height:1px;overflow:hidden}
.block-container{padding-top:1rem;padding-bottom:1rem}
div[data-testid="stHorizontalBlock"] button{white-space:nowrap}
</style>"""


def menu_items():
    """Menu yang tampil DI DALAM dashboard (bar edit). (key tombol tersembunyi, label)."""
    if is_admin():
        return [('act_edit', '✏️ Edit'), ('act_tambah', '➕ Tambah'), ('act_import', '📥 Import'), ('act_export', '📤 Export'),
                ('act_rollover', '⏭ Ganti hari'), ('act_claim', '🏆 Claim'), ('act_teks', '🔤 Teks'),
                ('act_users', '👥 Pengguna'), ('act_log', '📜 Log'), ('act_pw', '🔑 Password'), ('act_out', '🚪 Keluar')]
    return [('act_edit', '✏️ Input nilai'), ('act_claim', '🏆 Claim'), ('act_pw', '🔑 Password'), ('act_out', '🚪 Keluar')]


def hidden_edit_buttons():
    """Tombol tak terlihat (di luar layar); dipicu oleh klik di dalam dashboard: bar edit & kartu."""
    import logic as L
    actions = {'act_edit': dlg_edit, 'act_tambah': dlg_tambah, 'act_import': dlg_import, 'act_export': dlg_export,
               'act_rollover': dlg_rollover, 'act_claim': dlg_claim, 'act_teks': dlg_teks, 'act_users': dlg_users,
               'act_log': dlg_log, 'act_pw': dlg_password}
    rows = db.read_df('SELECT id, indikator FROM indikator')
    with st.container(key='hidden_edit_btns'):
        for key, _ in menu_items():
            if not st.button(key, key=key):
                continue
            if key == 'act_out':
                db.log_action(me()['username'], 'logout', '')
                st.session_state.clear()
                st.rerun()
            if key == 'act_tambah':
                st.session_state.pop('tambah_sec', None)
            actions[key]()
        if st.button('toggle', key='act_toggle'):
            st.session_state['edit_mode'] = not st.session_state.get('edit_mode', True)
            st.rerun()
        for rid, name in zip(rows['id'], rows['indikator']):
            if st.button('e', key=f'card_edit_{int(rid)}'):
                (dlg_claim_card if L.style_of(name) == 'claim' else dlg_card)(int(rid))
        if is_admin() and st.button('h', key='hdr_edit'):
            dlg_teks()
        if is_admin():
            for no in sorted({int(n) for n in db.read_df('SELECT DISTINCT no_seksi FROM indikator')['no_seksi'].dropna()}):
                if st.button('s', key=f'sec_add_{no}'):
                    st.session_state['tambah_sec'] = no
                    dlg_tambah()


def main():
    if 'user' not in st.session_state:
        login_view()
        return
    st.session_state.setdefault('edit_mode', True)
    st.markdown(_CSS, unsafe_allow_html=True)
    show_flash()
    hidden_edit_buttons()
    page_dashboard()


main()
