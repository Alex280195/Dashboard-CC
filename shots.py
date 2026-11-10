"""
shots.py - Screenshot dashboard di sisi server (opsional, butuh Playwright).

Instalasi sekali saja:
    pip install playwright
    playwright install chromium

Dijalankan lewat subprocess supaya aman dari konflik event-loop Streamlit.
"""
import os
import subprocess
import sys
import tempfile
from datetime import datetime

_DIR = os.path.dirname(os.path.abspath(__file__))
SHOT_DIR = os.path.join(_DIR, 'screenshots')


def save_screenshot(html, folder=SHOT_DIR):
    """Render HTML ke PNG (lebar 1288px, skala 2x). Mengembalikan path file PNG."""
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, 'Dashboard_Agen_' + datetime.now().strftime('%Y%m%d_%H%M') + '.png')
    with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False, encoding='utf-8') as f:
        f.write(html)
        tmp = f.name
    try:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), tmp, out], capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(tmp)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or '').strip().splitlines()
        raise RuntimeError('Screenshot gagal. Pastikan "pip install playwright" dan "playwright install chromium" sudah dijalankan. '
                           + (msg[-1] if msg else ''))
    return out


def _worker(html_path, out_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={'width': 1288, 'height': 900}, device_scale_factor=2)
        pg.goto('file://' + html_path)
        try:
            pg.wait_for_load_state('networkidle', timeout=8000)
        except Exception:
            pass   # font Google mungkin tidak terjangkau; lanjut saja
        pg.wait_for_timeout(400)
        pg.locator('#shot').screenshot(path=out_path)
        b.close()


if __name__ == '__main__':
    _worker(sys.argv[1], sys.argv[2])
