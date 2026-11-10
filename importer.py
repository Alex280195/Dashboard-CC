"""
importer.py - Membaca REPORT_DASHBOARD_CC.xlsx (sheet Config, Dashboard, Prakiraan) dan memuatnya ke SQLite.
Logikanya mengikuti Code.gs: pemetaan kolom lewat judul, konversi % pecahan, kontributor, tabel poin, complain platform.
Rumus =TODAY()-N diubah menjadi token {HARI-N} supaya tanggal tetap dinamis.
"""
import datetime as dt
import io
import re

from openpyxl import load_workbook

import logic as L

SKIP_CONFIG_KEYS = {'ID Spreadsheet Sumber', 'Nama Sheet Sumber'}   # khusus Google Sheet, tidak dipakai di Python

COL_NAMES = {
    'no': ['no seksi'], 'sec': ['judul seksi'], 'zh': ['judul seksi (cn)'], 'name': ['indikator'], 'sub': ['keterangan'],
    'prev': ['keterangan hari sebelumnya'], 'icon': ['ikon'], 'op': ['operator'], 'target': ['target'],
    'today': ['hari ini'], 'mtd': ['bulan ini'], 'yest': ['hari sebelumnya'], 'day2': ['2 hari lalu'],
    'color': ['warna garis'], 'unit': ['satuan'], 'target2': ['target 2'], 'today2': ['hari ini 2'],
    'show': ['tampil'], 'logic': ['logic trend', 'kolom warna'],
}
ORDER = ['no', 'sec', 'zh', 'name', 'sub', 'prev', 'icon', 'op', 'target', 'today', 'mtd', 'yest', 'day2', 'color',
         'unit', 'target2', 'today2', 'show', 'logic']


def map_cols(hdr):
    col = {}
    for i, h in enumerate(hdr):
        s = re.sub(r'\s+', ' ', str(h or '')).strip().lower()
        for k, names in COL_NAMES.items():
            if k not in col and s in names:
                col[k] = i
    for i, k in enumerate(ORDER):
        col.setdefault(k, i)
    return col


_TEXT_F = re.compile(r'=\s*TEXT\(\s*TODAY\(\)\s*(?:-\s*(\d+))?\s*,\s*"DD MMMM YYYY"\s*\)', re.I)
_PREFIX_F = re.compile(r'=\s*"(.*)"\s*&\s*TEXT\(\s*TODAY\(\)\s*(?:-\s*(\d+))?\s*,\s*"DD MMMM YYYY"\s*\)', re.I)
_TODAY_F = re.compile(r'=\s*TODAY\(\)\s*(?:-\s*(\d+))?', re.I)


def formula_to_text(raw, cached):
    """Rumus tanggal -> token {HARI-N}; selain itu pakai nilai cache."""
    if isinstance(raw, str) and raw.startswith('='):
        m = _TEXT_F.fullmatch(raw)
        if m:
            return '{HARI-%d}' % int(m.group(1) or 0)
        m = _PREFIX_F.fullmatch(raw)
        if m:
            return m.group(1) + '{HARI-%d}' % int(m.group(2) or 0)
        m = _TODAY_F.fullmatch(raw)
        if m:
            return '{HARI-%d}' % int(m.group(1) or 0)
    if isinstance(cached, (dt.datetime, dt.date)):
        d = cached.date() if isinstance(cached, dt.datetime) else cached
        return f"{d.day:02d} {L.BULAN[d.month - 1]} {d.year}"
    if isinstance(cached, float) and cached == int(cached):
        return str(int(cached))
    return '' if cached is None else str(cached)


def _is_formula(v):
    return (isinstance(v, str) and v.startswith('=')) or (v is not None and v.__class__.__name__ == 'ArrayFormula')


def import_xlsx(src, c, replace=True):
    """src: path atau file-like. c: koneksi database aktif. Mengembalikan ringkasan jumlah baris."""
    if hasattr(src, 'read'):
        if hasattr(src, 'seek'):
            src.seek(0)
        data = src.read()
    else:
        with open(src, 'rb') as f:
            data = f.read()
    wbv = load_workbook(io.BytesIO(data), data_only=True)
    wbf = load_workbook(io.BytesIO(data), data_only=False)
    for need in ('Config', 'Dashboard'):
        if need not in wbv.sheetnames:
            raise ValueError(f'Sheet "{need}" tidak ditemukan di file Excel.')

    if replace:
        for t in ('config', 'indikator', 'kontributor', 'poin_tier'):
            c.execute(f'DELETE FROM {t}')

    # ---------------- Config ----------------
    wsv, wsf = wbv['Config'], wbf['Config']
    cfg, n_cfg = {}, 0
    for r in range(2, wsv.max_row + 1):
        key = wsv.cell(r, 1).value
        if key in (None, ''):
            continue
        key = str(key).strip()
        if key in SKIP_CONFIG_KEYS:
            continue
        isi = formula_to_text(wsf.cell(r, 2).value, wsv.cell(r, 2).value)
        c_raw, c_val = wsf.cell(r, 3).value, wsv.cell(r, 3).value
        ganti = '' if (_is_formula(c_raw) or isinstance(c_val, (dt.datetime, dt.date)) or c_val is None) else str(c_val)
        note = wsv.cell(r, 4).value
        cfg[key] = isi
        c.execute('INSERT INTO config(nama,isi,ganti_isi,catatan) VALUES(?,?,?,?) '
                  'ON CONFLICT(nama) DO UPDATE SET isi=excluded.isi, ganti_isi=excluded.ganti_isi, catatan=excluded.catatan',
                  (key, isi, ganti, '' if note is None else str(note)))
        n_cfg += 1
    mode = str(cfg.get('Persen Berupa Pecahan') or 'Auto').strip().lower()

    # ---------------- Dashboard (indikator) ----------------
    wsv, wsf = wbv['Dashboard'], wbf['Dashboard']
    rows = list(wsv.iter_rows(min_row=1))
    col = map_cols([x.value for x in rows[0]])
    n_ind = 0
    for ri, cells in enumerate(rows[1:], start=2):
        def cell(k):
            i = col.get(k)
            return cells[i] if i is not None and i < len(cells) else None

        def val(k):
            x = cell(k)
            return None if x is None else x.value

        if val('no') in (None, '') or val('name') in (None, ''):
            continue
        unit = str(val('unit') or '%').strip().lower()

        def num(k):
            x = cell(k)
            return None if x is None else L.to_num(x.value, unit, x.number_format, mode)

        def txt(k, raw_col=True):
            i = col.get(k)
            raw = wsf.cell(ri, i + 1).value if (raw_col and i is not None) else None
            return formula_to_text(raw, val(k))

        op = str(val('op') or '').strip()
        c.execute(
            'INSERT INTO indikator(no_seksi,judul_seksi,judul_seksi_cn,indikator,keterangan,ket_hari_sebelumnya,ikon,'
            'operator,target,hari_ini,bulan_ini,hari_sebelumnya,dua_hari_lalu,warna_garis,satuan,target2,hari_ini2,'
            'tampil,logic_trend) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (float(val('no')), str(val('sec') or ''), str(val('zh') or ''), str(val('name')).strip(), txt('sub'),
             txt('prev'), str(val('icon') or ''), op if op in ('<=', '>=') else None, num('target'), num('today'),
             num('mtd'), num('yest'), num('day2'), str(val('color') or '#2f80ed'), unit, num('target2'), num('today2'),
             'Tidak' if str(val('show') or '').strip().lower() == 'tidak' else 'Ya', str(val('logic') or '')))
        n_ind += 1

    # ---------------- Prakiraan: kontributor, tabel poin, complain platform ----------------
    n_kon = n_tier = 0
    c.execute("INSERT INTO pengaturan(kunci,nilai) VALUES('total_poin','') "
              "ON CONFLICT(kunci) DO UPDATE SET nilai=excluded.nilai")
    c.execute("INSERT INTO pengaturan(kunci,nilai) VALUES('complain_platform','') "
              "ON CONFLICT(kunci) DO UPDATE SET nilai=excluded.nilai")
    if 'Prakiraan' in wbv.sheetnames:
        ps = wbv['Prakiraan']
        grid = [list(r) for r in ps.iter_rows(min_row=1, max_row=min(ps.max_row, 1000), max_col=16, values_only=True)]
        pad = lambda r, i: r[i] if i < len(r) else None

        # Top Kontributor: blok paling atas saja
        kons = {'Kategori': [], 'DP': []}
        for i, r in enumerate(grid):
            if i > 0 and str(pad(r, 0) or '').upper().startswith('PRAKIRAAN CLAIM'):
                break
            l1, l2 = str(pad(r, 8) or '').lower(), str(pad(r, 12) or '').lower()
            if 'kontributor' in l1 and 'kategori' in l1:
                v, nm = L.parse_num(pad(r, 10)), L.split_name(pad(r, 9))
                if v is not None and nm['name']:
                    kons['Kategori'].append((nm['name'], nm['sub'], v))
            if 'kontributor' in l2 and 'dp' in l2:
                v2, dn = L.parse_num(pad(r, 15)), str(pad(r, 13) or '').strip()
                if v2 is not None and dn:
                    kons['DP'].append((dn, str(pad(r, 14) or '').strip(), v2))
        for jenis, items in kons.items():
            for nama, sub, v in items:
                c.execute('INSERT INTO kontributor(jenis,nama,sub,nominal) VALUES(?,?,?,?)', (jenis, nama, sub, v))
                n_kon += 1

        # Tabel poin & warna Claim
        top = grid[:60]
        start = next((i for i, r in enumerate(top) if re.match(r'^total\s+poin', str(pad(r, 0) or '').strip(), re.I)), 12)
        if start < len(top):
            tot = L.parse_point(pad(top[start], 2))
            c.execute("INSERT INTO pengaturan(kunci,nilai) VALUES('total_poin',?) "
                      "ON CONFLICT(kunci) DO UPDATE SET nilai=excluded.nilai",
                      ('' if tot is None else str(tot),))
            for j in range(start + 1, min(len(top), start + 13)):
                r = top[j]
                colr = str(pad(r, 3) or '').strip()
                if not re.match(r'^#[0-9a-f]{6}$', colr, re.I):
                    break
                nom = L.parse_num(pad(r, 1))
                if nom is None:
                    continue
                c.execute('INSERT INTO poin_tier(label,nominal,poin,warna) VALUES(?,?,?,?)',
                          (str(pad(r, 0) or '').strip(), nom, L.parse_point(pad(r, 2)), colr))
                n_tier += 1

        # Jumlah Complain Platform (hari ini): blok A21:D24
        blk = grid[20:24]
        plat = None
        for h in range(min(3, len(blk))):
            for cc in range(4):
                if re.search(r'hari\s*ini', str(pad(blk[h], cc) or ''), re.I) and h + 1 < len(blk):
                    v = L.parse_num(pad(blk[h + 1], cc))
                    if v is not None:
                        plat = v
                        break
            if plat is not None:
                break
        if plat is None and len(blk) > 2:
            plat = L.parse_num(pad(blk[2], 0))
        c.execute("INSERT INTO pengaturan(kunci,nilai) VALUES('complain_platform',?) "
                  "ON CONFLICT(kunci) DO UPDATE SET nilai=excluded.nilai",
                  ('' if plat is None else str(plat),))

    return {'config': n_cfg, 'indikator': n_ind, 'kontributor': n_kon, 'tier': n_tier}
