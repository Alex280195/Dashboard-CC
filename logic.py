"""
logic.py - Port dari Code.gs (parsing / penyusunan data) dan fungsi hitung di Index.html
(status vs target, tren, warna, format angka, tier Claim).
Tidak bergantung pada Streamlit maupun database.
"""
import math
import re
from datetime import date, datetime, timedelta

DENDA_LIMIT_DEFAULT = 300_000_000

BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus',
         'September', 'Oktober', 'November', 'Desember']
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']

TREND_COLOR = {'up': '#0e9f4f', 'down': '#e32119', 'flat': '#e5a000', 'neu': '#2f6fe0'}


# ----------------------------------------------------------------------------------------
# Token tanggal: pengganti rumus =TODAY()-N di Google Sheet
#   {HARI-1} -> "09 November 2026" (kemarin).  Bisa disisipkan di teks: "接通率 {HARI-1}"
# ----------------------------------------------------------------------------------------
def resolve_tokens(text, today=None):
    if text is None:
        return ''
    today = today or date.today()

    def rep(m):
        d = today - timedelta(days=int(m.group(1)))
        return f"{d.day:02d} {BULAN[d.month - 1]} {d.year}"

    return re.sub(r'\{HARI-(\d+)\}', rep, str(text))


# ----------------------------------------------------------------------------------------
# Parser sel (parseBool_, parseLogic_, parseNum_, splitName_, parsePoint_, prevLabel_)
# ----------------------------------------------------------------------------------------
def parse_bool(v):
    if isinstance(v, bool):
        return v
    s = str(v if v is not None else '').strip().lower()
    if s in ('true', 'ya', '1'):
        return True
    if s in ('false', 'tidak', '0'):
        return False
    return None


_QUOTES = '"\'\u201c\u201d'
_UP = re.compile(r'naik\s*[:=\-\u2013>' + _QUOTES + r']*\s*([mh])', re.I)
_DOWN = re.compile(r'turun\s*[:=\-\u2013>' + _QUOTES + r']*\s*([mh])', re.I)
_SINGLE = re.compile(r'^[' + _QUOTES + r'\s]*([mh])(?:erah|ijau)?[' + _QUOTES + r'\s]*$', re.I)


def parse_logic(v):
    """'Naik M, Turun H' -> {'up':'M','down':'H'}  (M = merah, H = hijau). Kosong -> None."""
    s = str(v if v is not None else '').strip()
    if not s:
        return None
    up = down = None
    m = _UP.search(s)
    if m:
        up = m.group(1).upper()
    m = _DOWN.search(s)
    if m:
        down = m.group(1).upper()
    if not up and not down:
        m = _SINGLE.match(s)
        if m:
            up = m.group(1).upper()
    if not up and not down:
        return None
    opp = lambda x: 'H' if x == 'M' else 'M'
    if not up:
        up = opp(down)
    if not down:
        down = opp(up)
    return {'up': up, 'down': down}


def parse_num(v):
    """Angka dari sel angka atau teks seperti 'Rp 5,305,541'."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    s = re.sub(r'[^0-9.,\-]', '', str(v if v is not None else ''))
    if not s:
        return None
    try:
        return float(s.replace(',', ''))
    except ValueError:
        return None


def parse_point(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    s = re.sub(r'[^0-9.,\-]', '', str(v if v is not None else '')).replace(',', '.', 1)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def split_name(v):
    """'中文 \\n Bahasa Indonesia' -> {'name': Indonesia, 'sub': Mandarin}"""
    lines = [re.sub(r'\s+', ' ', x).strip() for x in re.split(r'\r?\n', str(v if v is not None else '').replace('"', ''))]
    lines = [x for x in lines if x]
    zh, idn = '', []
    for x in lines:
        if re.search(r'[\u3400-\u9fff]', x):
            zh = zh or x
        else:
            idn.append(x)
    name = ' '.join(idn) or zh
    return {'name': name, 'sub': zh if idn else ''}


def prev_label(v, today=None):
    """'07 November 2026' / '07/11/2026' -> '07/Nov' ; teks lain apa adanya ; kosong -> ''."""
    s = re.sub(r'\s+', ' ', resolve_tokens(v, today)).strip()
    if not s:
        return ''
    m = re.match(r'^(\d{1,2}) ([A-Za-z]{3,})', s)
    if m:
        return f"{int(m.group(1)):02d}/{m.group(2)[0].upper()}{m.group(2)[1:3].lower()}"
    m = re.match(r'^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$', s)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(1)):02d}/{MON[int(m.group(2)) - 1]}"
    return s


def to_num(v, unit, fmt, mode):
    """toNum() di Code.gs: sel berformat % (0.97) atau mode 'ya' -> 97. 'num' & 'rp' tidak diubah."""
    if v is None or v == '':
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(n):
        return None
    if unit == '%':
        frac = mode == 'ya' or (mode != 'tidak' and '%' in (fmt or ''))
        if frac:
            n = math.floor(n * 10000 + 0.5) / 100
    return n


def style_of(name):
    s = str(name or '').upper()
    if re.search(r'(PRAKIRAAN|PERKIRAAN)\s+CLAIM', s):
        return 'claim'
    if 'DENDA' in s:
        return 'denda'
    if 'COMPLAINT SELLER' in s:
        return 'seller'
    if re.match(r'^JUMLAH\s+(COMPLAINT|KOMPLAIN)', s):
        return 'complaint'
    return ''


def finish_card(card, sec_title, logic_cell):
    st = style_of(card['name'])
    card['style'] = st
    card['hideMtd'] = str(sec_title or '').strip().upper() == 'HOTLINE'
    lg = parse_logic(logic_cell)
    gb = None if lg else parse_bool(logic_cell)
    card['logic'] = lg
    if lg:
        card['goodUp'] = lg['up'] == 'H'
    elif gb is True or gb is False:
        card['goodUp'] = gb
    else:
        card['goodUp'] = not st
    return card


# ----------------------------------------------------------------------------------------
# Penyusunan data dashboard (getDashboardData)
# ----------------------------------------------------------------------------------------
def _s(v):
    return '' if v is None else str(v)


def _nz(v):
    """None / NaN -> None, selain itu float."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _intish(v):
    f = _nz(v)
    if f is None:
        return _s(v)
    return int(f) if f == int(f) else f


def teks_from_cfg(cfg, cfg_c):
    t = {}
    for k, v in cfg.items():
        if re.match(r'^(label|judul|sub judul|teks)', k, re.I):
            c = cfg_c.get(k)
            if c is not None and str(c).strip() != '':
                v = c
        t[k] = _s(v)
    return t


def build_dashboard(cfg_rows, ind_rows, kon_rows, tier_rows, settings, now=None):
    """
    cfg_rows : list[dict] (nama, isi, ganti_isi)
    ind_rows : list[dict] baris tabel indikator
    kon_rows : list[dict] (jenis, nama, sub, nominal)
    tier_rows: list[dict] (label, nominal, poin, warna)
    settings : dict (total_poin, complain_platform, ...)
    """
    now = now or datetime.now()
    today = now.date()
    cfg, cfg_c = {}, {}
    for r in cfg_rows:
        k = _s(r.get('nama')).strip()
        if k:
            cfg[k] = r.get('isi')
            cfg_c[k] = r.get('ganti_isi')

    denda_limit = _nz(cfg.get('Batas Denda (Rp)')) or DENDA_LIMIT_DEFAULT

    # --- Top Kontributor (3 terbesar per jenis) ---
    kon = {'kategori': [], 'dp': []}
    for r in kon_rows:
        nominal, nama = _nz(r.get('nominal')), _s(r.get('nama')).strip()
        if not nama or nominal is None:
            continue
        item = {'name': nama, 'sub': _s(r.get('sub')).strip(), 'value': nominal}
        j = _s(r.get('jenis')).strip().lower()
        if j == 'dp':
            kon['dp'].append(item)
        elif j == 'kategori':
            kon['kategori'].append(item)
    for k in kon:
        kon[k] = sorted(kon[k], key=lambda x: -x['value'])[:3]

    # --- Tabel poin Claim ---
    tiers = [{'label': _s(r.get('label')).strip(), 'nominal': _nz(r.get('nominal')),
              'point': _nz(r.get('poin')), 'color': _s(r.get('warna')).strip()}
             for r in tier_rows
             if _nz(r.get('nominal')) is not None and re.match(r'^#[0-9a-f]{6}$', _s(r.get('warna')).strip(), re.I)]
    poin = {'total': _nz(settings.get('total_poin')), 'tiers': tiers}
    platform = _nz(settings.get('complain_platform'))

    # --- Seksi & kartu ---
    sections, order = {}, []
    rows = [r for r in ind_rows
            if r.get('no_seksi') is not None and _s(r.get('indikator')).strip() != ''
            and _s(r.get('tampil')).strip().lower() != 'tidak']
    rows.sort(key=lambda r: (float(r['no_seksi']), r.get('id') or 0))
    for r in rows:
        no = _intish(r['no_seksi'])
        unit = (_s(r.get('satuan')) or '%').strip().lower()
        if no not in sections:
            sections[no] = {'no': no, 'title': _s(r.get('judul_seksi')), 'zh': _s(r.get('judul_seksi_cn')),
                            'note': '', 'cards': []}
            order.append(no)
        op = _s(r.get('operator')).strip()
        card = {
            'id': r.get('id'), 'name': _s(r.get('indikator')), 'sub': resolve_tokens(r.get('keterangan'), today),
            'icon': _s(r.get('ikon')), 'unit': unit, 'op': op if op in ('<=', '>=') else '',
            'target': _nz(r.get('target')), 'today': _nz(r.get('hari_ini')), 'mtd': _nz(r.get('bulan_ini')),
            'yesterday': _nz(r.get('hari_sebelumnya')), 'day2': _nz(r.get('dua_hari_lalu')),
            'lineColor': _s(r.get('warna_garis')) or '#2f80ed',
            'target2': _nz(r.get('target2')), 'today2': _nz(r.get('hari_ini2')),
            'prevLabel': prev_label(r.get('ket_hari_sebelumnya'), today),
        }
        finish_card(card, r.get('judul_seksi'), r.get('logic_trend'))
        if card['style'] == 'claim':
            card['kontributor'] = kon
            card['poin'] = poin
        if card['style'] == 'complaint' and platform is not None:
            card['platform'] = platform
        sections[no]['cards'].append(card)

    return {
        'meta': {
            'wilayah': _s(cfg.get('Wilayah')), 'agen': _s(cfg.get('Agen')), 'agenZh': _s(cfg.get('Agen (CN)')),
            'tanggal': resolve_tokens(cfg.get('Tanggal'), today), 'sumber': _s(cfg.get('Sumber')),
            'jumlahAgen': _s(cfg.get('Jumlah Agen')), 'jumlahHari': _s(cfg.get('Jumlah Hari')),
            'dendaLimit': denda_limit,
            'teks': {k: resolve_tokens(v, today) for k, v in teks_from_cfg(cfg, cfg_c).items()},
            'diperbarui': now.strftime('%H:%M'),
        },
        'sections': [sections[k] for k in order],
    }


# ----------------------------------------------------------------------------------------
# Format angka (fmt / fmtRp / fmtRpFull / fmtDelta di Index.html)
# ----------------------------------------------------------------------------------------
def _round_half_up(x):
    return math.floor(x + 0.5)


def loc_id(n):
    """Number.toLocaleString('id-ID'): titik ribuan, koma desimal, maks 3 desimal."""
    n = float(n)
    ip, fp = f"{abs(n):,.3f}".split('.')
    fp = fp.rstrip('0')
    ip = ip.replace(',', '.')
    neg = '-' if (n < 0 and (ip != '0' or fp)) else ''
    return neg + ip + (',' + fp if fp else '')


def fmt_rp(n):
    a, s = abs(n), ('-' if n < 0 else '')
    if a >= 1e9:
        return s + 'Rp ' + f"{a / 1e9:.2f}".replace('.', ',') + ' M'
    if a >= 1e6:
        return s + 'Rp ' + f"{a / 1e6:.1f}".replace('.', ',') + ' jt'
    return s + 'Rp ' + loc_id(a)


def fmt_rp_full(n):
    a = _round_half_up(abs(n))
    return ('-' if n < 0 else '') + 'Rp ' + f"{int(a):,}".replace(',', '.')


def fmt_poin(n):
    if n is None:
        return '–'
    v = _round_half_up(n * 100) / 100
    return (str(int(v)) if v == int(v) else str(v)).replace('.', ',')


def fmt(n, unit):
    if n is None:
        return '–'
    if unit == 'rpfull':
        return fmt_rp_full(n)
    if unit == 'rp':
        return fmt_rp(n)
    if unit == 'num':
        return loc_id(n)
    return f"{n:.2f}%"


def fmt_delta(d, unit):
    s, a = ('+' if d >= 0 else '-'), abs(d)
    if unit == 'rpfull':
        return s + fmt_rp_full(a)
    if unit == 'rp':
        return s + fmt_rp(a).replace('Rp ', '')
    if unit == 'num':
        return s + loc_id(a)
    return s + f"{a:.2f}"


# ----------------------------------------------------------------------------------------
# Status, tren, warna
# ----------------------------------------------------------------------------------------
def meets(v, op, t):
    if v is None or t is None or not op:
        return True
    return v <= t if op == '<=' else v >= t


def has_val(v):
    return v is not None and not (isinstance(v, float) and math.isnan(v)) and float(v) != 0


def status_of(v, op, t, unit):
    """up (hijau) | down (merah) | flat (kuning); None jika tanpa target."""
    if v is None or t is None or not op:
        return None
    d = v - t
    eps = 0 if unit in ('rp', 'num') else 0.005
    if abs(d) < eps or d == 0:
        return 'flat'
    above = d > 0
    return 'up' if ((not above) if op == '<=' else above) else 'down'


def trend_of(c):
    if c['today'] is None or c['yesterday'] is None:
        return None
    d = c['today'] - c['yesterday']
    eps = 0 if c['unit'] in ('rp', 'num') else 0.005
    if abs(d) < eps or d == 0:
        return 'flat'
    return 'up' if d > 0 else 'down'


def color_of(c):
    t = trend_of(c)
    if not t:
        return None
    if t == 'flat':
        return 'neu' if c['style'] else 'flat'
    if c.get('logic') and c['logic'].get(t):
        return 'down' if c['logic'][t] == 'M' else 'up'
    return 'up' if ((t == 'up') == (c.get('goodUp') is not False)) else 'down'


def text_on(hexcolor):
    s = str(hexcolor or '').replace('#', '')
    if len(s) != 6:
        return '#1b2340'
    r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    return '#1b2340' if (r * 299 + g * 587 + b * 114) / 1000 > 150 else '#fff'


def claim_tier(c):
    ts = sorted((c.get('poin') or {}).get('tiers') or [], key=lambda t: t['nominal'])
    if c['today'] is None or not ts:
        return None
    for t in ts:
        if c['today'] <= t['nominal']:
            return t
    return {'color': '#FF0000'}
