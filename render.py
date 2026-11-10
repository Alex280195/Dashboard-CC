"""
render.py - Port render dashboard dari Index.html ke HTML statis (dipakai st.components.html
dan screenshot server). CSS diambil dari style.css (salinan persis dari Index.html).
"""
import os
from html import escape

import logic as L

_DIR = os.path.dirname(os.path.abspath(__file__))

LOGO = ('<svg viewBox="0 0 156 42" xmlns="http://www.w3.org/2000/svg" aria-label="J&amp;T Express">'
        '<text x="0" y="40" font-family="\'Arial Black\',\'Nunito Sans\',Arial,sans-serif" font-size="46" font-weight="900" '
        'font-style="italic" fill="#e4161c" textLength="101" lengthAdjust="spacingAndGlyphs">J&amp;T</text>'
        '<text x="102" y="40" font-family="\'Nunito Sans\',Arial,sans-serif" font-size="19" font-weight="800" '
        'font-style="italic" fill="#e4161c" textLength="54" lengthAdjust="spacingAndGlyphs">EXPRESS</text></svg>')


def esc(s):
    return escape('' if s is None else str(s), quote=True)


class Ctx:
    """Menggantikan variabel global TEKS & DENDA_LIMIT di Index.html."""
    def __init__(self, meta):
        self.teks = meta.get('teks') or {}
        self.denda = float(meta.get('dendaLimit') or L.DENDA_LIMIT_DEFAULT)

    def T(self, k, d=''):
        v = self.teks.get(k)
        return str(v) if (v is not None and str(v).strip() != '') else d


def prev_txt(x, c, u):
    lead = (esc(c['prevLabel']) + ' = ') if c.get('prevLabel') else (esc(x.T('Label Kemarin', 'Kemarin')) + ' ')
    return lead + L.fmt(c['yesterday'], u)


def sparkline(c):
    if c['style'] == 'claim':
        return ''
    t = L.trend_of(c)
    if not t:
        return ''
    d = {'up': 'M0 88 L50 88 Q82 88 100 8',
         'down': 'M0 10 L50 16 Q82 20 100 90'}.get(t, 'M0 50 L100 50')
    col = L.TREND_COLOR.get(L.color_of(c)) or c['lineColor']
    return ('<svg viewBox="0 0 100 100" preserveAspectRatio="none"><path d="%s" fill="none" stroke="%s" stroke-width="2" '
            'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>') % (d, esc(col))


def delta_html(c, u):
    delta = c.get('delta')
    if delta is None and c['today'] is not None and c['yesterday'] is not None:
        delta = c['today'] - c['yesterday']
    if delta is None:
        return ''
    return '<span class="delta %s">%s%s</span>' % (L.color_of(c) or 'flat', '▲ ' if delta >= 0 else '▼ ', L.fmt_delta(delta, u))


def top_panel(x, title, zh, arr):
    mx = max([a['value'] for a in (arr or [])] + [0])
    if arr:
        rows = ''
        for i, a in enumerate(arr[:3]):
            w = max(6, a['value'] / mx * 32) if mx > 0 else 6
            rows += ('<div class="tp-row"><div class="tp-rk">%d</div><div class="tp-tx"><div class="tp-nm">%s</div>%s</div>'
                     '<div class="tp-bar"><b style="width:%.1f%%"></b><span>%s</span></div></div>') % (
                i + 1, esc(a['name']), ('<div class="tp-sub">%s</div>' % esc(a['sub'])) if a.get('sub') else '',
                w, L.fmt_rp_full(a['value']))
    else:
        rows = '<div class="tp-empty">%s</div>' % esc(x.T('Teks Belum Ada Data', 'Belum ada data'))
    return '<div class="tp"><div class="tp-head">%s%s</div><div class="tp-body">%s</div></div>' % (
        esc(title), ('<span class="zh">%s</span>' % esc(zh)) if zh else '', rows)


def claim_html(x, c):
    u, k = 'rpfull', c.get('kontributor') or {}
    tier = L.claim_tier(c)
    clr = tier['color'] if tier else ''
    total = (c.get('poin') or {}).get('total')
    poin_html = ''
    if total is not None:
        bg = clr or '#dbe5f7'
        poin_html = '<div class="c-poin">%s: <b class="poin-chip" style="background:%s;color:%s">%s</b></div>' % (
            esc(x.T('Label Total Point', 'Total Point')), esc(bg), L.text_on(bg), L.fmt_poin(total))
    info = ''
    if c['target'] is not None:
        info += '<div class="c-target">%s: %s</div>' % (esc(x.T('Label Target Bulanan', 'Target Bulanan')), L.fmt(c['target'], u))
    if L.has_val(c['mtd']):
        info += '<div class="c-mtd">%s: %s</div>' % (esc(x.T('Label Bulan Ini', 'Bulan Ini')), L.fmt(c['mtd'], u))
    col1 = ('<div class="tp"><div class="tp-head">%s<span class="zh">%s</span></div><div class="tp-body tp-main">'
            '<div class="c-value"><span class="c-ico">%s</span><span class="c-num">%s</span></div>'
            '<div class="c-info">%s%s</div>'
            '<div class="c-foot"><span>%s</span>%s</div></div></div>') % (
        esc(c['name']), esc(x.T('Judul Claim (CN)', '预估理赔金额')), esc(c['icon']), L.fmt(c['today'], u),
        info, poin_html, prev_txt(x, c, u), delta_html(c, u))
    return '<div class="card neutral claim"><span class="dot"></span>%s%s%s</div>' % (
        col1,
        top_panel(x, x.T('Judul Kontributor Sub Kategori', '3 Top Kontributor Sub Kategori'),
                  x.T('Judul Kontributor Sub Kategori (CN)', '前三名子类别'), k.get('kategori')),
        top_panel(x, x.T('Judul Kontributor DP', '3 Top Kontributor DP'),
                  x.T('Judul Kontributor DP (CN)', '前三名网点'), k.get('dp')))


def card_html(x, c):
    if c['style'] == 'claim':
        return claim_html(x, c)
    u, op, col = c['unit'] or '%', c['op'] or '', L.color_of(c)
    if c['style'] == 'denda' and u == 'rp':
        u = 'rpfull'
    has_target = bool(op) and c['target'] is not None and not c['style']
    dual = c['today2'] is not None
    state = 'neutral'
    if c['style'] == 'denda':
        state = 'bad' if (c['today'] is not None and c['today'] > x.denda) else 'neutral'
    elif c['style']:
        state = '' if col == 'up' else ('bad' if col == 'down' else 'neutral')
    elif has_target:
        ok = L.meets(c['today'], op, c['target']) and (not dual or L.meets(c['today2'], op, c['target2']))
        state = '' if ok else 'bad'

    sign = '≤' if op == '<=' else '≥'
    plat_txt = ''
    # Bulan Ini: tampil jika ada isinya (kosong / 0 -> tidak tampil); disembunyikan untuk seksi HOTLINE
    mtd_txt = '' if c.get('hideMtd') else (
        x.T('Label Bulan Ini', 'Bulan Ini') + ': ' + L.fmt(c['mtd'], u) if L.has_val(c['mtd']) else '')
    if c['style'] == 'complaint':
        target_txt = (x.T('Label Komplain JMS', 'Jumlah Komplain JMS') + ': ' + L.fmt(c['target'], u)) if c['target'] is not None else ''
        plat_txt = (x.T('Label Komplain Platform', 'Jumlah Komplain Platform') + ': ' + L.fmt(c.get('platform'), u)) \
            if c.get('platform') is not None else ''
    elif c['style'] == 'denda':
        target_txt = x.T('Label Batas Denda', 'Merah jika >') + ' ' + L.fmt_rp_full(x.denda)
    elif has_target:
        target_txt = x.T('Label Target', 'Target') + ' ' + sign + ' ' + L.fmt(c['target'], u)
        if dual and c['target2'] is not None:
            target_txt += ' | ' + sign + ' ' + L.fmt(c['target2'], u)
    else:
        target_txt = x.T('Label Tanpa Target', '')

    s1 = None if c['style'] else L.status_of(c['today'], op, c['target'], u)
    s2 = L.status_of(c['today2'], op, c['target2'], u) if (dual and not c['style']) else None
    if dual:
        val_html = ('<span class="c-num dual"><span class="tv%s">%s</span><i>/</i><span class="tv%s">%s</span></span>') % (
            (' t-' + s1) if s1 else '', L.fmt(c['today'], u), (' t-' + s2) if s2 else '', L.fmt(c['today2'], u))
    else:
        val_html = '<span class="c-num%s%s">%s</span>' % ((' t-' + s1) if s1 else '', ' long' if u == 'rpfull' else '', L.fmt(c['today'], u))

    info = ''
    if target_txt:
        info += '<div class="c-target">%s</div>' % esc(target_txt)
    if plat_txt:
        info += '<div class="c-mtd same">%s</div>' % esc(plat_txt)
    if mtd_txt:
        info += '<div class="c-mtd%s">%s</div>' % (' same' if c['style'] == 'complaint' else '', esc(mtd_txt))

    return ('<div class="card%s"><span class="dot"></span>'
            '<div class="c-head"><div class="c-name">%s</div>%s</div>'
            '<div class="c-value"><span class="c-ico">%s</span>%s</div>'
            '<div class="c-info">%s</div>'
            '<div class="c-foot"><span>%s</span>%s</div>'
            '<div class="spark">%s</div></div>') % (
        (' ' + state) if state else '', esc(c['name']), ('<div class="c-sub">%s</div>' % esc(c['sub'])) if c['sub'] else '',
        esc(c['icon']), val_html, info, prev_txt(x, c, u), delta_html(c, u), sparkline(c))


def sections_html(x, d):
    out = []
    for s in d['sections']:
        n = len(s['cards'])
        out.append(
            '<div class="sec-bar"><div class="no">%s</div><div class="t">%s%s%s</div><div class="count">%d %s</div></div>'
            '<div class="grid" data-n="%d" style="--n:%d">%s</div>' % (
                esc(s['no']), esc(s['title']), ('<span>%s</span>' % esc(s['zh'])) if s['zh'] else '',
                ('<em>(%s)</em>' % esc(s['note'])) if s['note'] else '', n, esc(x.T('Label Indikator', 'Indikator')),
                n, n, ''.join(card_html(x, c) for c in s['cards'])))
    return ''.join(out) or '<div class="state">Belum ada data.</div>'


_SHOT_JS = """
function toast(m){var t=document.getElementById('toast');t.textContent=m;t.style.display='block';
  clearTimeout(toast._t);toast._t=setTimeout(function(){t.style.display='none';},5000);}
function stamp(){var d=new Date(),p=function(n){return('0'+n).slice(-2)};
  return d.getFullYear()+p(d.getMonth()+1)+p(d.getDate())+'_'+p(d.getHours())+p(d.getMinutes());}
function shot(){
  if(typeof html2canvas==='undefined'){toast('html2canvas belum termuat, coba lagi.');return;}
  toast('Mengambil screenshot…');
  html2canvas(document.getElementById('shot'),{scale:2,backgroundColor:'#edf1f8',useCORS:true,scrollX:0,scrollY:-window.scrollY,
    windowWidth:Math.max(document.documentElement.clientWidth,1288)}).then(function(cv){
    var a=document.createElement('a');a.href=cv.toDataURL('image/png');a.download='Dashboard_Agen_'+stamp()+'.png';
    document.body.appendChild(a);a.click();a.remove();toast('Screenshot diunduh.');
  }).catch(function(e){toast('Screenshot gagal: '+e.message);});
}
"""


def page_html(d, with_tools=True):
    """Dokumen HTML lengkap dashboard. with_tools=False untuk screenshot server."""
    x = Ctx(d['meta'])
    m = d['meta']
    css = open(os.path.join(_DIR, 'style.css'), encoding='utf-8').read()
    zh_t, zh_s = x.T('Judul Dashboard (CN)', '每日代理区绩效看板'), x.T('Sub Judul (CN)', '仅限总部内部团队')
    sep = '<span class="sep">|</span>'
    meta_html = (
        esc(x.T('Label Wilayah', 'Wilayah')) + ': <b>' + esc(m['wilayah']) + '</b>' + sep +
        esc(x.T('Label Agen', 'Agen')) + ': <b>' + esc(m['agen']) + '&nbsp; ' + esc(m['agenZh']) + '</b>' + sep +
        esc(x.T('Label Tanggal', 'Tanggal')) + ': <b>' + esc(m['tanggal']) + '</b>' + sep +
        esc(x.T('Label Sumber', 'Sumber')) + ': <b>' + esc(m['sumber']) + '</b>' + sep +
        esc(x.T('Label Diperbarui', 'Diperbarui')) + ': <b>' + esc(m.get('diperbarui', '')) + '</b>')
    tools = ''
    scripts = ''
    if with_tools:
        tools = ('<div class="tools" data-html2canvas-ignore="true"><button onclick="shot()">📸 Screenshot</button></div>'
                 '<div class="toast" id="toast" data-html2canvas-ignore="true"></div>')
        scripts = ('<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>'
                   '<script>' + _SHOT_JS + '</script>')
    return (
        '<!DOCTYPE html><html lang="id"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><title>Dashboard Performa Agen Harian</title>'
        '<link href="https://fonts.googleapis.com/css2?family=Nunito+Sans:wght@400;600;700;800;900&display=swap" rel="stylesheet">'
        '<style>' + css + '</style></head><body>'
        '<div class="wrap" id="shot"><div class="header"><div class="logo">' + LOGO + '</div><div class="h-center">'
        '<div class="h-title">' + esc(x.T('Judul Dashboard', 'DASHBOARD PERFORMA AGEN HARIAN')) +
        (('<span class="zh">' + esc(zh_t) + '</span>') if zh_t else '') + '</div>'
        '<div class="h-sub">' + esc(x.T('Sub Judul', 'KHUSUS TIM INTERNAL AGEN BANDUNG')) +
        ((' <span class="zh">' + esc(zh_s) + '</span>') if zh_s else '') + '</div>'
        '<div class="h-meta">' + meta_html + '</div></div></div>'
        '<div id="content">' + sections_html(x, d) + '</div></div>' + tools + scripts + '</body></html>')


def estimate_height_px(d, rem_px=12):
    """Perkiraan tinggi iframe (rem -> px) supaya hampir tanpa scroll internal."""
    rem = 8.6 + 0.9 + 3.6
    for s in d['sections']:
        n = len(s['cards'])
        rem += 5.5
        if n == 1 and s['cards'][0]['style'] == 'claim':
            rem += 25
        elif n == 1:
            rem += 10
        else:
            rem += 19
    return int(rem * rem_px + 40)
