"""Offline Chromium integration test. No app lifespan, MQTT, archive or remote tiles.

Run with a Python environment containing playwright:
  python tests/browser_meshlive.py [--compare-ref HEAD]
"""
import argparse
import base64
import json
import mimetypes
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
NOW = time.time()
KEYS = [s.ljust(64, '0') for s in ['aabbcc', 'bbccdd', 'ccddee', 'ddeeff']]
NODES = [dict(public_key=k, name=f'Node {i}', node_type=2, latitude=52.14 + i*.02,
              longitude=10.49 + i*.04, advert_time=100, position_time=100,
              first_seen=NOW-100, last_seen=NOW) for i, k in enumerate(KEYS)]
TILE = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1cAAAAASUVORK5CYII=')
INIT = '''
window.__sockets = [];
window.WebSocket = class {
  static OPEN = 1; readyState = 1;
  constructor(url) { this.url = url; window.__sockets.push(this); }
  close() { this.readyState = 3; this.onclose?.(); }
};
window.__meshFrames = 0; window.__meshStrokes = [];
const raf = window.requestAnimationFrame;
window.requestAnimationFrame = fn => raf.call(window, t => {
  if (fn.name === 'draw') window.__meshFrames++;
  fn(t);
});
const stroke = CanvasRenderingContext2D.prototype.stroke;
CanvasRenderingContext2D.prototype.stroke = function(...args) {
  if (this.canvas.classList.contains('meshlive-canvas')) {
    window.__meshStrokes.push({frame:window.__meshFrames, dash:this.getLineDash(), alpha:this.globalAlpha});
  }
  return stroke.apply(this, args);
};
'''


def packet(number, hops=None, observer=2, hash_value=None):
    hops = ['aabb', 'bbcc'] if hops is None else hops
    return dict(number=number, observer_hash=hash_value or f'HASH{number}',
                group_id=hash_value or f'HASH{number}', direction='rx', received_at='2026-10-10T12:00:00+00:00',
                origin_id=KEYS[observer], origin=f'Observer {observer}', time='14:00:00',
                rssi=-90, snr=8, length=24, raw_hex='1542aabbbbcceeff', last_hop=hops[-1] if hops else 'direct',
                decoded=dict(route_type=1, route_name='FLOOD', payload_type=5, payload_name='GRP_TXT',
                             payload_ver=0, payload_hex='eeff', hops=hops, hop_labels=hops,
                             hop_count=len(hops), hash_size=2, scope_label='Kein Scope',
                             header=21, path_len_raw=64+len(hops), transport_code=None,
                             group_channel='Public', group_text=f'Test {number}'))


def emit(page, packets, kind='update'):
    groups = {}
    for p in packets:
        group = groups.setdefault(p['group_id'], dict(id=p['group_id'], count=0, first_seen=p['received_at'], receptions=[]))
        group['count'] += 1
        group['latest'] = p
        group['receptions'].append(p)
    page.evaluate('data => window.__sockets.at(-1).onmessage({data:JSON.stringify(data)})',
                  dict(type=kind, groups=list(groups.values()), removed=[], raw_packets=['raw fixture'],
                       status=dict(connected=True, received=len(packets), dropped=0, noise_history=[])))


def route_page(page, requests, baseline=None):
    def route(req):
        parsed = urlparse(req.request.url)
        requests.append(parsed.path + ('?' + parsed.query if parsed.query else ''))
        if parsed.netloc == 'tile.openstreetmap.org':
            req.fulfill(body=TILE, content_type='image/png'); return
        if parsed.path.startswith('/api/'):
            data = {'items': []}
            if parsed.path == '/api/map-nodes':
                data = {'nodes': NODES, 'tokens': []} if parsed.query else {'items': NODES, 'without_position':0, 'inactive':0}
            elif parsed.path == '/api/repeater-neighbors/map':
                data = {'nodes':[], 'links':[], 'total':0}
            elif parsed.path == '/api/channels':
                data = {'channels':[]}
            req.fulfill(json=data); return
        path = 'static/index.html' if parsed.path == '/' else parsed.path.lstrip('/')
        if baseline and path in ('static/index.html', 'static/app.js', 'static/style.css'):
            body = subprocess.check_output(['git', 'show', f'{baseline}:{path}'], cwd=ROOT)
        else:
            target = (ROOT / path).resolve()
            if not target.is_relative_to(ROOT / 'static') or not target.is_file():
                req.fulfill(status=404); return
            body = target.read_bytes()
        req.fulfill(body=body, content_type=mimetypes.guess_type(path)[0] or 'application/octet-stream')
    page.route('**/*', route)
    page.add_init_script(INIT)


def text_regression(page):
    emit(page, [packet(1), packet(2, observer=3, hash_value='HASH1')], 'snapshot')
    assert page.locator('#packets tr.packet').count() == 1
    states = [page.locator('#panel-live').inner_html()]
    page.locator('#live-repeater').fill('bbcc')
    page.locator('#live-observer').select_option(KEYS[2])
    assert page.locator('#packets tr.packet').count() == 1
    page.locator('#packets button.expand').click()
    assert page.locator('#packets .reception').count() == 1
    states.append(page.locator('#panel-live').inner_html())
    page.locator('#pause').click()
    emit(page, [packet(3, ['bbcc', 'ccdd'])])
    assert 'Test 3' not in page.locator('#packets').inner_text()
    states.append(page.locator('#panel-live').inner_html())
    page.locator('#live-filter-reset').click()
    page.locator('#pause').click()
    assert 'Test 3' in page.locator('#packets').inner_text()
    states.append(page.locator('#panel-live').inner_html())
    return states


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compare-ref')
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                              args=['--no-sandbox', '--disable-dev-shm-usage'])
        page = browser.new_page(viewport={'width':1280, 'height':900})
        errors, requests = [], []
        page.on('pageerror', lambda err: errors.append(str(err)))
        route_page(page, requests)
        page.goto('http://meshlive.test/')
        page.wait_for_function('window.__sockets.length === 1')
        assert page.locator('#tab-live').inner_text() == 'Live'
        assert page.locator('#meshlive-map canvas').count() == 0
        assert not any('mesh_live=true' in r for r in requests)
        current_text = text_regression(page)
        if args.compare_ref:
            baseline = browser.new_page(viewport={'width':1280, 'height':900})
            route_page(baseline, [], args.compare_ref)
            baseline.goto('http://baseline.test/')
            baseline.wait_for_function('window.__sockets.length === 1')
            assert text_regression(baseline) == current_text, 'Text LiveView DOM changed from baseline'
            original_tabs = baseline.locator('[role=tab]').evaluate_all('(tabs) => tabs.map(t => [t.id,t.textContent])')
            current_tabs = page.locator('[role=tab]').evaluate_all('(tabs) => tabs.filter(t=>t.id!=="tab-meshlive").map(t => [t.id,t.textContent])')
            assert current_tabs == original_tabs, 'Existing tab order or labels changed'
            baseline.close()
        page.locator('#tab-meshlive').click()
        page.wait_for_function('document.querySelector("#meshlive-status").textContent.includes("4 Nodes · Live")')
        assert page.locator('#meshlive-observed').is_checked()
        assert page.locator('#meshlive-reconstructed').is_checked()
        assert page.locator('#meshlive-map canvas').count() == 1
        assert page.evaluate('window.__sockets.length') == 1, 'No second socket'
        assert page.evaluate('window.__meshStrokes.length') == 0, 'No initial replay'
        emit(page, [packet(4)])
        page.wait_for_function('window.__meshStrokes.some(s=>s.dash.length) && window.__meshStrokes.some(s=>!s.dash.length)')
        assert page.locator('#meshlive-map canvas').evaluate('(c)=>getComputedStyle(c).pointerEvents') == 'none'
        # Interact while the animation runs; Leaflet controls and pan stay available.
        page.locator('#meshlive-map .leaflet-control-zoom-in').click()
        box = page.locator('#meshlive-map').bounding_box()
        page.mouse.move(box['x']+box['width']/2, box['y']+box['height']/2)
        page.mouse.down(); page.mouse.move(box['x']+box['width']/2+35, box['y']+box['height']/2+20); page.mouse.up()
        page.wait_for_timeout(1150)
        assert page.locator('#meshlive-map canvas').evaluate('(c)=>!c.getContext("2d").getImageData(0,0,c.width,c.height).data.some(v=>v)')
        frames = page.evaluate('window.__meshFrames')
        emit(page, [packet(4)])
        page.wait_for_timeout(80)
        assert page.evaluate('window.__meshFrames') == frames, 'Repeated group must not replay'
        for disabled, expected_dashed in [('observed', True), ('reconstructed', False)]:
            page.locator(f'#meshlive-{disabled}').uncheck()
            page.evaluate('window.__meshStrokes=[]')
            emit(page, [packet(5 if disabled == 'observed' else 7)])
            page.wait_for_function('window.__meshStrokes.length > 0')
            assert page.evaluate('window.__meshStrokes.every(s=>Boolean(s.dash.length)===%s)' % json.dumps(expected_dashed))
            page.locator('#meshlive-pause').click()
            page.locator(f'#meshlive-{disabled}').check()
            emit(page, [packet(6 if disabled == 'observed' else 8)])
            assert page.locator('#pause').inner_text() == 'Ansicht pausieren', 'MeshLive pause must not pause text view'
            page.locator('#meshlive-pause').click()
            page.evaluate('window.__meshStrokes=[]')
            page.wait_for_timeout(60)
            assert page.evaluate('window.__meshStrokes.length') == 0, 'No replay after pause'
        # Snapshot after restart resets reception numbering, but never animates history.
        emit(page, [packet(1)], 'snapshot')
        page.wait_for_function('document.querySelector("#meshlive-status").textContent.includes("4 Nodes · Live")')
        assert page.evaluate('window.__meshStrokes.length') == 0
        emit(page, [packet(2)])
        page.wait_for_function('window.__meshStrokes.length > 0')
        page.locator('#tab-live').click()
        frames = page.evaluate('window.__meshFrames')
        count = sum('mesh_live=true' in r for r in requests)
        emit(page, [packet(3)])
        page.wait_for_timeout(80)
        assert page.evaluate('window.__meshFrames') == frames, 'Hidden tab must stop animation loop'
        assert sum('mesh_live=true' in r for r in requests) == count, 'Hidden tab must not fetch nodes'
        assert 'Test 3' in page.locator('#packets').inner_text()
        page.locator('#live-repeater').fill('ccdd')
        assert page.locator('#packets tr.packet').count() == 0, 'Existing filter still applies'
        page.locator('#live-filter-reset').click()
        assert page.locator('#packets tr.packet').count() > 0
        page.locator('#tab-map').click()
        page.wait_for_selector('#node-map .leaflet-marker-icon')
        assert page.locator('#node-map .leaflet-marker-icon').count() == 4
        # Mobile view: independent map, bounded DPR, usable controls.
        page.set_viewport_size({'width':390, 'height':844})
        page.locator('#tab-meshlive').click()
        page.wait_for_function('document.querySelector("#meshlive-status").textContent.includes("4 Nodes · Live")')
        assert page.locator('#meshlive-map').bounding_box()['width'] <= 390
        page.locator('#meshlive-fit').click()
        emit(page, [packet(4)])
        page.wait_for_timeout(80)
        page.screenshot(path='/tmp/meshlive-mobile.png', full_page=True)
        page.set_viewport_size({'width':1280, 'height':900})
        page.locator('#meshlive-fit').click()
        emit(page, [packet(5)])
        page.wait_for_timeout(80)
        page.screenshot(path='/tmp/meshlive-desktop.png', full_page=True)
        # Recent hop deduplication survives resynchronization, even with new RX numbers.
        emit(page, [packet(100, hash_value='RECONNECT')])
        emit(page, [packet(100, hash_value='RECONNECT')], 'snapshot')
        page.wait_for_function('document.querySelector("#meshlive-status").textContent.includes("4 Nodes · Live")')
        page.evaluate('window.__meshStrokes=[]')
        emit(page, [packet(101, hash_value='RECONNECT')])
        page.wait_for_timeout(70)
        assert page.evaluate('window.__meshStrokes.length') == 0, 'Resync must preserve hop dedup window'
        # Browser visibility, separately from the application tab.
        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true}); document.dispatchEvent(new Event('visibilitychange'))")
        frames = page.evaluate('window.__meshFrames')
        count = sum('mesh_live=true' in r for r in requests)
        emit(page, [packet(102)])
        page.wait_for_timeout(70)
        assert page.evaluate('window.__meshFrames') == frames
        assert sum('mesh_live=true' in r for r in requests) == count
        page.evaluate("delete document.hidden; document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_function('document.querySelector("#meshlive-status").textContent.includes("4 Nodes · Live")')
        assert page.evaluate('window.__meshStrokes.length') == 0, 'No replay when document becomes visible'
        # Burst limit applies to actual canvas work, not only the event model.
        page.evaluate('window.__meshStrokes=[]')
        emit(page, [packet(i) for i in range(110, 210)])
        page.wait_for_function('window.__meshStrokes.length > 0')
        assert page.evaluate('''() => {
            const frames = new Map();
            for (const s of window.__meshStrokes) frames.set(s.frame, (frames.get(s.frame)||0)+1);
            return Math.max(...frames.values()) <= 64;
        }''')
        assert '136 Spuren am Limit ausgelassen' in page.locator('#meshlive-status').inner_text()
        page.wait_for_timeout(1100)
        frames = page.evaluate('window.__meshFrames')
        page.wait_for_timeout(70)
        assert page.evaluate('window.__meshFrames') == frames, 'Idle canvas loop stops after burst'
        # No periodic MeshLive bootstrap, even though other tabs have existing intervals.
        count = sum('mesh_live=true' in r for r in requests)
        page.wait_for_timeout(5100)
        assert sum('mesh_live=true' in r for r in requests) == count
        assert not errors, errors
        browser.close()
    print('MeshLive Chromium: lazy map, solid/dashed trails, cleanup, pause, stream snapshots, tab lifecycle, mobile and text LiveView regressions passed')
    if args.compare_ref:
        print(f'Text LiveView DOM and original tab order match {args.compare_ref} exactly across filters, details, pause and resume')


if __name__ == '__main__':
    main()
