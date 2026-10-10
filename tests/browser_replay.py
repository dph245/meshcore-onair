"""Offline Chromium replay lifecycle, clocks and LiveView regression tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright, expect
from browser_meshlive import route_page, packet, emit, NODES, NOW, text_regression


def fixture():
    start = NOW - 600
    nodes = deepcopy(NODES)
    for n in nodes:
        n.update(first_seen=start-100, last_seen=start-1)
    events = []
    for i, offset in enumerate([1, 20, 599.5], 1):
        p = packet(i, hash_value=f'REPLAY{i}')
        p['received_at'] = datetime.fromtimestamp(start+offset, timezone.utc).isoformat()
        events.append(dict(id=i, received=start+offset, packet=p))
    return dict(window_start=start, window_end=NOW, speed=10, events=events,
                bootstrap=dict(nodes=nodes, tokens=[], seed_packets=[]),
                archive_latest_received=NOW-5, seed_scan_limited=True, seed_adverts_scanned=2000)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                     args=['--no-sandbox', '--disable-dev-shm-usage'])
        page = browser.new_page(viewport={'width':1280, 'height':900})
        errors, requests, calls = [], [], []
        response = {'status':200, 'data':fixture()}
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.clock.install()
        route_page(page, requests)
        def replay_route(route):
            calls.append(route.request.url)
            route.fulfill(status=response['status'], json=response['data'])
        page.route('**/api/meshlive/replay', replay_route)
        page.goto('http://replay.test/')
        page.wait_for_function('window.__sockets.length === 1')
        text_regression(page)
        assert calls == [], 'No replay fetch before user starts it'
        page.locator('#tab-meshlive').click()
        expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes · Live')
        page.clock.pause_at(datetime.now(timezone.utc)+timedelta(milliseconds=100))
        click = lambda selector: page.locator(selector).evaluate('(el)=>el.click()')
        mesh_requests = lambda: sum('mesh_live=true' in r for r in requests)
        initial_mesh_requests = mesh_requests()
        click('#meshlive-replay-start')
        expect(page.locator('#meshlive-status')).to_contain_text('REPLAY · 10×')
        expect(page.locator('#meshlive-replay-badge')).to_be_visible()
        expect(page.locator('#meshlive-replay-message')).to_contain_text('Positionssuche begrenzt')
        assert len(calls) == 1
        assert page.evaluate('window.__sockets.length') == 1
        page.clock.run_for(200)
        assert page.evaluate('window.__meshStrokes.some(s=>s.dash.length) && window.__meshStrokes.some(s=>!s.dash.length)')
        assert 0 < page.locator('#meshlive-replay-progress').evaluate('(el)=>el.value') < .01
        click('#meshlive-replay-pause')
        page.clock.run_for(20)
        frozen = page.locator('#meshlive-map canvas').evaluate('(c)=>c.toDataURL()')
        progress = page.locator('#meshlive-replay-progress').evaluate('(el)=>el.value')
        frames = page.evaluate('window.__meshFrames')
        # Live still reaches the text view, while replay is frozen.
        emit(page, [packet(100)])
        emit(page, [packet(1)], 'snapshot')
        assert 'Test 1' in page.locator('#packets').inner_text()
        page.clock.run_for(5000)
        assert page.locator('#meshlive-map canvas').evaluate('(c)=>c.toDataURL()') == frozen
        assert page.locator('#meshlive-replay-progress').evaluate('(el)=>el.value') == progress
        assert page.evaluate('window.__meshFrames') == frames, 'Paused replay has no permanent draw loop'
        assert mesh_requests() == initial_mesh_requests, 'Live snapshots never refresh replay nodes'
        click('#meshlive-replay-pause')
        page.clock.run_for(300)
        assert page.locator('#meshlive-replay-progress').evaluate('(el)=>el.value') > progress
        click('#tab-live')
        frames = page.evaluate('window.__meshFrames')
        page.clock.run_for(5000)
        assert page.evaluate('window.__meshFrames') == frames
        click('#tab-meshlive')
        expect(page.locator('#meshlive-replay-pause')).to_have_text('Replay fortsetzen')
        assert len(calls) == 1 and mesh_requests() == initial_mesh_requests
        # Returning to the tab does not auto-resume or advance the historical cursor.
        progress = page.locator('#meshlive-replay-progress').evaluate('(el)=>el.value')
        page.clock.run_for(1000)
        assert page.locator('#meshlive-replay-progress').evaluate('(el)=>el.value') == progress
        page.screenshot(path='/tmp/meshlive-replay-desktop.png')
        # Browser visibility behaves like tab switching.
        click('#meshlive-replay-pause')
        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true}); document.dispatchEvent(new Event('visibilitychange'))")
        page.clock.run_for(1000)
        page.evaluate("delete document.hidden; document.dispatchEvent(new Event('visibilitychange'))")
        expect(page.locator('#meshlive-replay-pause')).to_have_text('Replay fortsetzen')
        assert mesh_requests() == initial_mesh_requests
        # Stop: new live bootstrap, never the packets accumulated during replay.
        page.evaluate('window.__meshStrokes=[]')
        click('#meshlive-replay-end')
        expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes · Live')
        page.clock.run_for(100)
        expect(page.locator('#meshlive-replay-badge')).to_be_hidden()
        assert not page.evaluate('window.__meshStrokes.length')
        assert mesh_requests() == initial_mesh_requests+1
        emit(page, [packet(2)])
        page.clock.run_for(100)
        assert page.evaluate('window.__meshStrokes.length') > 0
        # Complete 60-second timeline plus full one-second final trail, no timeouts per packet.
        click('#meshlive-replay-start')
        expect(page.locator('#meshlive-status')).to_contain_text('REPLAY · 10×')
        page.clock.run_for(60000)
        expect(page.locator('#meshlive-replay-badge')).to_be_visible()
        assert page.locator('#meshlive-replay-progress').evaluate('(el)=>el.value') == 1
        page.clock.run_for(1100)
        expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes · Live')
        expect(page.locator('#meshlive-replay-message')).to_contain_text('Replay beendet')
        assert len(calls) == 2
        # Empty window and server limits are explicit, never a partial replay.
        response['data'] = {**fixture(), 'events':[]}
        click('#meshlive-replay-start')
        expect(page.locator('#meshlive-replay-message')).to_contain_text('Keine archivierten Empfänge')
        expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes · Live')
        response.update(status=413, data={'detail':'Mehr als 5.000 Empfänge. Nichts abgeschnitten.'})
        click('#meshlive-replay-start')
        expect(page.locator('#meshlive-replay-message')).to_contain_text('5.000 Empfänge')
        expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes · Live')
        expect(page.locator('#meshlive-replay-badge')).to_be_hidden()
        # A response arriving after cancellation may not re-enter replay.
        response.update(status=200, data=fixture())
        page.evaluate('''data => {
          window.__fetch = window.fetch;
          window.fetch = (url, options) => url === '/api/meshlive/replay'
            ? new Promise(resolve => window.__finishReplay = () => resolve(new Response(JSON.stringify(data))))
            : window.__fetch(url, options);
        }''', fixture())
        click('#meshlive-replay-start')
        expect(page.locator('#meshlive-status')).to_contain_text('Replay wird geladen')
        click('#meshlive-replay-end')
        expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes · Live')
        page.evaluate('window.__finishReplay(); window.fetch=window.__fetch')
        page.clock.run_for(100)
        expect(page.locator('#meshlive-replay-badge')).to_be_hidden()
        # Mobile controls remain visible/readable; tab switch also pauses during loading.
        page.set_viewport_size({'width':390,'height':844})
        click('#meshlive-replay-start')
        expect(page.locator('#meshlive-status')).to_contain_text('REPLAY · 10×')
        click('#meshlive-replay-pause')
        page.clock.run_for(20)
        page.locator('#meshlive-replay-controls').scroll_into_view_if_needed()
        page.screenshot(path='/tmp/meshlive-replay-mobile.png')
        assert page.locator('#meshlive-replay-controls').bounding_box()['width'] <= 390
        click('#meshlive-replay-end')
        expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes · Live')
        # Text LiveView still accepts filters, details and its own pause after replay.
        click('#tab-live')
        page.clock.resume()
        text_regression(page)
        assert not errors, errors
        browser.close()
    print('Replay Chromium: one bounded fetch, 10× timeline, pause/frozen trails, tabs/visibility, live isolation, end/tail, limits, cancellation and mobile passed')


if __name__ == '__main__':
    main()
