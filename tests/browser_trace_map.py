"""Offline TRACE map integration: real Leaflet, mocked archive, no MQTT/server."""
from playwright.sync_api import sync_playwright, expect
from browser_meshlive import route_page


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                     args=['--no-sandbox', '--disable-dev-shm-usage'])
        page = browser.new_page(viewport={'width':1280, 'height':900})
        errors, requests, trace_requests = [], [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda request: trace_requests.append(request.url) if '/api/map-traces' in request.url else None)
        route_page(page, requests)
        page.route('**/api/map-traces?*', lambda route: route.fulfill(json=dict(items=[
            dict(id=i, received=1000+i, route=['aa','bb','cc'], observed_hops=3, tag='01')
            for i in [1,2,3,4]], scanned=2, before=None)))
        def detail(route):
            identity = int(route.request.url.rsplit('/',1)[1])
            tokens = ['aa','bb','cc'] if identity <= 2 else ['aa','bb','cc','bb','aa']
            values = [12,7.5,-10.5] if identity <= 2 else [12,7.5,-10.5,-3,.25] if identity == 3 else [9,-1,5,-7,3]
            route.fulfill(json=dict(id=identity, first_seen=1000+identity, observed_hops=len(tokens),
                hops=[dict(hash=token, name=token, public_key=token*32, snr_min=values[i], snr_max=values[i],
                    position=(None if identity == 2 and i == 1 else dict(
                    latitude=52+['aa','bb','cc'].index(token)*.1,
                    longitude=10+['aa','bb','cc'].index(token)*.1))) for i,token in enumerate(tokens)]))
        page.route('**/api/map-traces/*', detail)
        page.goto('http://trace.test/')
        page.locator('#tab-map').click()
        page.wait_for_function('mapMarkers.size > 0')
        page.evaluate("setMapLinkMode('none'); selectMapRepeater([...mapMarkers.keys()][0])")
        page.locator('[data-mode=traces]').click()
        assert page.locator('#map-node-tools').is_hidden()
        page.locator('#map-trace-form button').click()
        expect(page.locator('#map-trace-list input')).to_have_count(4)
        page.locator('#map-trace-list input').first.check()
        expect(page.locator('#map-trace-detail')).to_contain_text('Quelle: unbekannt')
        # Full route: 3 circles, 2 segments, 2 arrow polylines.
        assert page.locator('#node-map .leaflet-overlay-pane path:not(.trace-snr-leader)').count() == 7
        expect(page.locator('.trace-snr-label')).to_have_count(2)
        expect(page.locator('.trace-snr-value').nth(0)).to_have_text('→ +7,5 dB')
        expect(page.locator('.trace-snr-value').nth(1)).to_have_text('→ −10,5 dB')
        assert page.locator('.trace-snr-label').first.is_visible(), 'No hover needed'
        page.locator('#map-trace-list input').nth(1).check()
        expect(page.locator('#map-trace-detail')).to_contain_text('Historische Position unbekannt')
        # Unknown intermediate hop adds only 2 markers, never a bridge.
        assert page.locator('#node-map .leaflet-overlay-pane path:not(.trace-snr-leader)').count() == 9
        before = len(trace_requests)
        page.evaluate('nodeMap.panBy([30, 20]); nodeMap.setZoom(10)')
        page.wait_for_timeout(300)
        assert len(trace_requests) == before
        page.locator('[data-mode=paths]').click()
        assert page.locator('#map-traces').is_hidden()
        assert page.locator('#node-map .leaflet-overlay-pane path:not(.trace-snr-leader)').count() == 0
        page.locator('[data-mode=traces]').click()
        assert page.locator('#node-map .leaflet-overlay-pane path:not(.trace-snr-leader)').count() == 9
        page.set_viewport_size({'width':390,'height':844})
        page.locator('#map-trace-detail').scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='/tmp/onair-trace-mobile.png', full_page=True)
        page.locator('#map-trace-detail button').first.click()
        expect(page.locator('#map-trace-detail section')).to_have_count(1)
        # Compare two complete round trips over the SAME physical sections.
        page.locator('#map-trace-detail button').first.click()
        expect(page.locator('.trace-snr-label')).to_have_count(0)
        page.locator('#map-trace-list input').nth(2).check()
        expect(page.locator('.trace-snr-label')).to_have_count(2)
        page.locator('#map-trace-list input').nth(3).check()
        expect(page.locator('.trace-snr-label')).to_have_count(4)
        expect(page.locator('.trace-snr-value')).to_have_count(8)
        assert page.locator('.trace-snr-label[data-trace-id="3"]').first.inner_text().splitlines()[-2:] == ['→ +7,5 dB', '← +0,25 dB']
        assert page.locator('.trace-snr-label[data-trace-id="3"]').nth(1).inner_text().splitlines()[-2:] == ['→ −10,5 dB', '← −3,0 dB']
        assert page.locator('.trace-snr-label[data-trace-id="4"]').first.inner_text().splitlines()[-2:] == ['→ −1,0 dB', '← +3,0 dB']
        # Normal-link settings must never clear or redraw away TRACE comparison/SNR.
        trace_count = page.locator('#node-map .leaflet-overlay-pane path').count()
        for mode in ['none', 'all', 'selected']:
            page.locator('#map-link-mode').select_option(mode)
            expect(page.locator('.trace-snr-label')).to_have_count(4)
            expect(page.locator('.trace-snr-value')).to_have_count(8)
            assert page.locator('#node-map .leaflet-overlay-pane path').count() == trace_count
        # Dense sections at regional zoom: both routes retain every value on mobile.
        page.evaluate('nodeMap.setView([52.1,10.1], 7, {animate:false})')
        page.wait_for_timeout(300)
        boxes = page.locator('.trace-snr-label').evaluate_all('(labels)=>labels.map(e=>{const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}})')
        for i, a in enumerate(boxes):
            for b in boxes[i+1:]:
                assert a['x']+a['w'] <= b['x'] or b['x']+b['w'] <= a['x'] or a['y']+a['h'] <= b['y'] or b['y']+b['h'] <= a['y'], (a,b)
        for theme in ['light','dark']:
            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            page.locator('#node-map').screenshot(path=f'/tmp/onair-trace-snr-{theme}.png')
        page.locator('[data-mode=paths]').click()
        expect(page.locator('.trace-snr-label')).to_have_count(0)
        page.locator('[data-mode=traces]').click()
        expect(page.locator('.trace-snr-value')).to_have_count(8)
        page.locator('#map-trace-period').select_option('custom')
        assert page.locator('#map-trace-start').is_enabled()
        assert not errors, errors
        browser.close()
        print('TRACE map desktop/mobile: passed')


if __name__ == '__main__':
    main()
