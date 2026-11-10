"""
db.py - Penyimpanan SQLite (pengganti Google Sheet), autentikasi pengguna, dan operasi CRUD.
"""
import hashlib
import hmac
import math
import os
import re
import secrets
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache

import pandas as pd
import streamlit as st
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import IntegrityError
from streamlit.errors import StreamlitSecretNotFoundError

import logic as L

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('DASHBOARD_DB', os.path.join(_DIR, 'data', 'dashboard.db'))
SEED_XLSX = os.path.join(_DIR, 'REPORT_DASHBOARD_CC.xlsx')
_QMARK = re.compile(r'\?')

IND_COLS = ['no_seksi', 'judul_seksi', 'judul_seksi_cn', 'indikator', 'keterangan', 'ket_hari_sebelumnya', 'ikon',
            'operator', 'target', 'hari_ini', 'bulan_ini', 'hari_sebelumnya', 'dua_hari_lalu', 'warna_garis',
            'satuan', 'target2', 'hari_ini2', 'tampil', 'logic_trend']
NUM_COLS = {'no_seksi', 'target', 'hari_ini', 'bulan_ini', 'hari_sebelumnya', 'dua_hari_lalu', 'target2', 'hari_ini2',
            'nominal', 'poin'}
COLS = {
    'indikator': IND_COLS,
    'config': ['nama', 'isi', 'ganti_isi', 'catatan'],
    'kontributor': ['jenis', 'nama', 'sub', 'nominal'],
    'poin_tier': ['label', 'nominal', 'poin', 'warna'],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  username TEXT PRIMARY KEY, salt TEXT NOT NULL, pw_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','user')), aktif INTEGER NOT NULL DEFAULT 1, dibuat TEXT);
CREATE TABLE IF NOT EXISTS config(
  id INTEGER PRIMARY KEY AUTOINCREMENT, nama TEXT UNIQUE NOT NULL, isi TEXT, ganti_isi TEXT, catatan TEXT);
CREATE TABLE IF NOT EXISTS indikator(
  id INTEGER PRIMARY KEY AUTOINCREMENT, no_seksi REAL, judul_seksi TEXT, judul_seksi_cn TEXT, indikator TEXT,
  keterangan TEXT, ket_hari_sebelumnya TEXT, ikon TEXT, operator TEXT, target REAL, hari_ini REAL, bulan_ini REAL,
  hari_sebelumnya REAL, dua_hari_lalu REAL, warna_garis TEXT, satuan TEXT, target2 REAL, hari_ini2 REAL,
  tampil TEXT DEFAULT 'Ya', logic_trend TEXT);
CREATE TABLE IF NOT EXISTS kontributor(
  id INTEGER PRIMARY KEY AUTOINCREMENT, jenis TEXT, nama TEXT, sub TEXT, nominal REAL);
CREATE TABLE IF NOT EXISTS poin_tier(
  id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT, nominal REAL, poin REAL, warna TEXT);
CREATE TABLE IF NOT EXISTS pengaturan(kunci TEXT PRIMARY KEY, nilai TEXT);
CREATE TABLE IF NOT EXISTS log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, waktu TEXT, username TEXT, aksi TEXT, detail TEXT);
"""

DEFAULT_SETTINGS = {'refresh_sec': '120', 'auto_enabled': '0', 'auto_times': '08:00,12:00,16:00',
                    'total_poin': '', 'complain_platform': ''}


def _secret(section, key):
    try:
        return st.secrets[section][key]
    except (StreamlitSecretNotFoundError, KeyError):
        return None


@lru_cache(maxsize=1)
def _engine():
    url = os.environ.get('DATABASE_URL') or _secret('database', 'url')
    if not url:
        directory = os.path.dirname(DB_PATH)
        if directory:
            os.makedirs(directory, exist_ok=True)
        return create_engine(URL.create('sqlite', database=DB_PATH), connect_args={'check_same_thread': False})
    if url.startswith('postgres://'):
        url = 'postgresql+psycopg://' + url[len('postgres://'):]
    elif url.startswith('postgresql://'):
        url = 'postgresql+psycopg://' + url[len('postgresql://'):]
    return create_engine(url, pool_pre_ping=True)


class _Row:
    def __init__(self, row):
        self._mapping = row._mapping
        self._values = tuple(row)

    def __getitem__(self, key):
        return self._values[key] if isinstance(key, int) else self._mapping[key]

    def __iter__(self):
        return iter(self._mapping)

    def __len__(self):
        return len(self._mapping)

    def keys(self):
        return self._mapping.keys()


class _Result:
    def __init__(self, result):
        self._result = result

    def fetchone(self):
        row = self._result.fetchone()
        return _Row(row) if row is not None else None

    def fetchall(self):
        return [_Row(row) for row in self._result.fetchall()]

    def keys(self):
        return self._result.keys()

    def __iter__(self):
        return iter(self.fetchall())


class _Connection:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, params=()):
        params = {} if params is None else params
        if isinstance(params, dict):
            statement = text(sql)
        else:
            values = tuple(params)
            for index in range(len(values)):
                sql = _QMARK.sub(f':p{index}', sql, count=1)
            statement = text(sql)
            params = {f'p{index}': value for index, value in enumerate(values)}
        return _Result(self._connection.execute(statement, params))

    def executescript(self, script):
        for statement in script.split(';'):
            if statement.strip():
                self._connection.exec_driver_sql(statement)


@contextmanager
def conn():
    with _engine().begin() as connection:
        yield _Connection(connection)


def is_sqlite():
    return _engine().dialect.name == 'sqlite'


# ---------------------------------------------------------------------------------------
# Inisialisasi
# ---------------------------------------------------------------------------------------
def init(seed=True, create_admin=True):
    with conn() as c:
        schema = SCHEMA.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'BIGSERIAL PRIMARY KEY') \
            if _engine().dialect.name == 'postgresql' else SCHEMA
        c.executescript(schema)
        if seed or create_admin:
            for k, v in DEFAULT_SETTINGS.items():
                c.execute('INSERT INTO pengaturan(kunci,nilai) VALUES(?,?) ON CONFLICT(kunci) DO NOTHING', (k, v))
        if create_admin and c.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
            password = os.environ.get('INITIAL_ADMIN_PASSWORD') or _secret('app', 'initial_admin_password')
            if not password or len(password) < 12:
                raise RuntimeError('Set INITIAL_ADMIN_PASSWORD (at least 12 characters) before initializing an empty database.')
            _insert_user(c, 'admin', password, 'admin')
        if seed:
            empty = (c.execute('SELECT COUNT(*) FROM indikator').fetchone()[0] == 0
                     and c.execute('SELECT COUNT(*) FROM config').fetchone()[0] == 0)
            if empty and os.path.exists(SEED_XLSX):
                import importer
                importer.import_xlsx(SEED_XLSX, c, replace=True)
                c.execute('INSERT INTO log(waktu,username,aksi,detail) VALUES(?,?,?,?)',
                          (_now(), 'sistem', 'seed', 'Data awal diimpor dari ' + os.path.basename(SEED_XLSX)))


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ---------------------------------------------------------------------------------------
# Pengguna & autentikasi
# ---------------------------------------------------------------------------------------
def _hash(pw, salt_hex):
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), bytes.fromhex(salt_hex), 200_000).hex()


def _insert_user(c, username, pw, role):
    salt = secrets.token_hex(16)
    c.execute('INSERT INTO users(username,salt,pw_hash,role,aktif,dibuat) VALUES(?,?,?,?,1,?)',
              (username, salt, _hash(pw, salt), role, _now()))


def verify_login(username, password):
    """Mengembalikan {'username','role'} bila valid, selain itu None."""
    with conn() as c:
        r = c.execute('SELECT * FROM users WHERE username=?', ((username or '').strip(),)).fetchone()
    if not r or not r['aktif']:
        return None
    if hmac.compare_digest(_hash(password or '', r['salt']), r['pw_hash']):
        return {'username': r['username'], 'role': r['role']}
    return None


def list_users():
    with conn() as c:
        return [dict(r) for r in c.execute('SELECT username, role, aktif, dibuat FROM users ORDER BY role, username')]


def add_user(username, pw, role):
    username = (username or '').strip()
    if not username or len(pw or '') < 6:
        raise ValueError('Username wajib diisi dan password minimal 6 karakter.')
    if role not in ('admin', 'user'):
        raise ValueError('Role tidak valid.')
    try:
        with conn() as c:
            _insert_user(c, username, pw, role)
    except IntegrityError:
        raise ValueError(f'Username "{username}" sudah ada.')


def set_password(username, pw):
    if len(pw or '') < 6:
        raise ValueError('Password minimal 6 karakter.')
    salt = secrets.token_hex(16)
    with conn() as c:
        c.execute('UPDATE users SET salt=?, pw_hash=? WHERE username=?', (salt, _hash(pw, salt), username))


def update_user(username, role, aktif):
    with conn() as c:
        others = c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND aktif=1 AND username<>?", (username,)).fetchone()[0]
        if others == 0 and not (role == 'admin' and aktif):
            raise ValueError('Harus tersisa minimal satu admin aktif.')
        c.execute('UPDATE users SET role=?, aktif=? WHERE username=?', (role, 1 if aktif else 0, username))


def delete_user(username):
    with conn() as c:
        others = c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND aktif=1 AND username<>?", (username,)).fetchone()[0]
        if others == 0:
            raise ValueError('Harus tersisa minimal satu admin aktif.')
        c.execute('DELETE FROM users WHERE username=?', (username,))


# ---------------------------------------------------------------------------------------
# Pengaturan & log
# ---------------------------------------------------------------------------------------
def get_setting(k, default=''):
    with conn() as c:
        r = c.execute('SELECT nilai FROM pengaturan WHERE kunci=?', (k,)).fetchone()
    return r['nilai'] if r and r['nilai'] is not None else default


def set_setting(k, v):
    with conn() as c:
        c.execute('INSERT INTO pengaturan(kunci,nilai) VALUES(?,?) ON CONFLICT(kunci) DO UPDATE SET nilai=excluded.nilai',
                  (k, '' if v is None else str(v)))


def log_action(username, aksi, detail=''):
    with conn() as c:
        c.execute('INSERT INTO log(waktu,username,aksi,detail) VALUES(?,?,?,?)', (_now(), username, aksi, detail))


# ---------------------------------------------------------------------------------------
# Baca tabel
# ---------------------------------------------------------------------------------------
def read_df(sql, params=()):
    with conn() as c:
        result = c.execute(sql, params)
        return pd.DataFrame([dict(row) for row in result], columns=result.keys())


def read(table):
    order = 'no_seksi, id' if table == 'indikator' else 'id'
    return read_df(f'SELECT * FROM {table} ORDER BY {order}')


def load_dashboard():
    """Data siap render (setara getDashboardData() di Code.gs)."""
    with conn() as c:
        rows = lambda t: [dict(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY id')]
        settings = {r['kunci']: r['nilai'] for r in c.execute('SELECT * FROM pengaturan')}
        return L.build_dashboard(rows('config'), rows('indikator'), rows('kontributor'), rows('poin_tier'), settings)


# ---------------------------------------------------------------------------------------
# CRUD generik: terapkan hasil st.data_editor (tambah / ubah / hapus)
# ---------------------------------------------------------------------------------------
def _clean(v, col):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if col in NUM_COLS:
        return float(v)
    s = str(v).strip()
    return s or None


def _same(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)
    return a == b


def _validate(table, vals):
    if table == 'indikator':
        if vals['no_seksi'] is None or not vals['judul_seksi'] or not vals['indikator']:
            raise ValueError('No Seksi, Judul Seksi, dan Indikator wajib diisi.')
        if vals['operator'] not in (None, '>=', '<='):
            raise ValueError(f'Operator "{vals["operator"]}" tidak valid (gunakan >= atau <=).')
        if vals['satuan'] not in ('%', 'num', 'rp'):
            raise ValueError(f'Satuan "{vals["satuan"]}" tidak valid (gunakan %, num, atau rp).')
        if vals['tampil'] not in ('Ya', 'Tidak'):
            raise ValueError('Kolom Tampil harus Ya atau Tidak.')
    elif table == 'config':
        if not vals['nama']:
            raise ValueError('Nama pengaturan wajib diisi.')
    elif table == 'kontributor':
        if (vals['jenis'] or '').lower() not in ('kategori', 'dp') or not vals['nama'] or vals['nominal'] is None:
            raise ValueError('Kontributor: Jenis (Kategori/DP), Nama, dan Nominal wajib diisi.')
    elif table == 'poin_tier':
        if not vals['label'] or vals['nominal'] is None or not (vals['warna'] or '').startswith('#') or len(vals['warna']) != 7:
            raise ValueError('Tier: Label, Nominal, dan Warna (#RRGGBB) wajib diisi.')


def apply_changes(table, orig, edited, allow_delete=True):
    """Bandingkan DataFrame asli vs hasil edit lalu tulis ke DB. Mengembalikan (tambah, ubah, hapus)."""
    cols = COLS[table]
    orig = orig.set_index('id', drop=False)
    edited = edited.reset_index(drop=True)
    kept = {int(i) for i in edited['id'].dropna()}
    removed = [int(i) for i in orig.index if int(i) not in kept]
    if removed and not allow_delete:
        raise PermissionError('Hanya admin yang boleh menghapus data.')
    new_rows, upd = [], []
    for _, r in edited.iterrows():
        vals = {c: _clean(r.get(c), c) for c in cols}
        if table == 'indikator':
            vals['satuan'] = vals['satuan'] or '%'
            vals['tampil'] = vals['tampil'] or 'Ya'
        if pd.isna(r['id']):
            if all(v is None for v in vals.values()):
                continue
            _validate(table, vals)
            new_rows.append(vals)
        else:
            old = orig.loc[int(r['id'])]
            if any(not _same(_clean(old[c], c), vals[c]) for c in cols):
                _validate(table, vals)
                upd.append((int(r['id']), vals))
    try:
        with conn() as c:
            for i in removed:
                c.execute(f'DELETE FROM {table} WHERE id=?', (i,))
            for i, v in upd:
                c.execute(f'UPDATE {table} SET ' + ','.join(f'{k}=?' for k in cols) + ' WHERE id=?',
                          [v[k] for k in cols] + [i])
            for v in new_rows:
                c.execute(f'INSERT INTO {table}({",".join(cols)}) VALUES({",".join("?" * len(cols))})', [v[k] for k in cols])
    except IntegrityError as e:
        raise ValueError('Data duplikat / tidak valid: ' + str(e))
    return len(new_rows), len(upd), len(removed)


def insert_row(table, vals):
    cols = COLS[table]
    vals = {c: _clean(vals.get(c), c) for c in cols}
    if table == 'indikator':
        vals['satuan'] = vals['satuan'] or '%'
        vals['tampil'] = vals['tampil'] or 'Ya'
    _validate(table, vals)
    try:
        with conn() as c:
            c.execute(f'INSERT INTO {table}({",".join(cols)}) VALUES({",".join("?" * len(cols))})', [vals[k] for k in cols])
    except IntegrityError as e:
        raise ValueError('Data duplikat / tidak valid: ' + str(e))


def update_daily_values(orig, edited):
    """Simpan perubahan nilai harian (hanya kolom nilai). Mengembalikan jumlah baris yang berubah."""
    fields = ['hari_ini', 'bulan_ini', 'hari_sebelumnya', 'dua_hari_lalu', 'hari_ini2']
    orig = orig.set_index('id')
    n = 0
    with conn() as c:
        for _, r in edited.iterrows():
            i = int(r['id'])
            vals = {f: _clean(r[f], f) for f in fields}
            if any(not _same(_clean(orig.loc[i, f], f), vals[f]) for f in fields):
                c.execute('UPDATE indikator SET ' + ','.join(f'{f}=?' for f in fields) + ' WHERE id=?',
                          [vals[f] for f in fields] + [i])
                n += 1
    return n


def rollover_day():
    """Hari baru: Hari Ini -> Hari Sebelumnya -> 2 Hari Lalu, Hari Ini dikosongkan."""
    with conn() as c:
        c.execute('UPDATE indikator SET dua_hari_lalu=hari_sebelumnya, hari_sebelumnya=hari_ini, hari_ini=NULL, hari_ini2=NULL')


def update_row(table, row_id, vals, only=None):
    """Ubah satu baris. only = daftar kolom yang diubah (mis. nilai harian saja untuk role user)."""
    cols = COLS[table]
    vals = {c: _clean(vals.get(c), c) for c in cols}
    if table == 'indikator':
        vals['satuan'] = vals['satuan'] or '%'
        vals['tampil'] = vals['tampil'] or 'Ya'
    if only is None:
        _validate(table, vals)
    use = [c for c in cols if (only is None or c in only)]
    try:
        with conn() as c:
            c.execute(f'UPDATE {table} SET ' + ','.join(f'{k}=?' for k in use) + ' WHERE id=?',
                      [vals[k] for k in use] + [int(row_id)])
    except IntegrityError as e:
        raise ValueError('Data duplikat / tidak valid: ' + str(e))


def delete_row(table, row_id):
    with conn() as c:
        c.execute(f'DELETE FROM {table} WHERE id=?', (int(row_id),))
