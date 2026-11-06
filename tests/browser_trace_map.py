"""Offline TRACE map integration: real Leaflet, mocked archive, no MQTT/server."""
from playwright.sync_api import sync_playwright, expect
from browser_meshlive import route_page


def settle(page):
    page.evaluate('''async () => {
      await document.fonts.ready;
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }''')


def performance_regression(page, trace_requests):
    page.set_viewport_size(dict(width=1280, height=1000))
    page.evaluate('traceMap.setView([52.1,10.1], 10, {animate:false})')
    settle(page)
    expect(page.locator('.trace-snr-label')).to_have_count(4)
    page.evaluate('''() => {
      window.traceMetrics = {circles:0, lines:0, markers:0, reads:0, projections:0};
      for (const [name, counter] of [['circleMarker','circles'], ['polyline','lines'], ['marker','markers']]) {
        const create = L[name];
        L[name] = (...args) => { traceMetrics[counter]++; return create(...args); };
      }
      for (const name of ['offsetWidth', 'offsetHeight']) {
        const descriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, name);
        Object.defineProperty(HTMLElement.prototype, name, {...descriptor, get() {
          if (this.classList.contains('trace-snr-label')) traceMetrics.reads++;
          return descriptor.get.call(this);
        }});
      }
      const project = traceMap.latLngToContainerPoint.bind(traceMap);
      traceMap.latLngToContainerPoint = (...args) => { traceMetrics.projections++; return project(...args); };
      window.traceGroup = Object.values(traceMap._layers).find(layer => layer instanceof L.LayerGroup);
      traceGroup.clearLayers = () => { throw Error('TRACE must reconcile individual layers'); };
      window.savedTraceLayers = traceGroup.getLayers().map(layer => [layer, layer.getElement()]);
      window.savedLabelBoxes = [...document.querySelectorAll('.trace-snr-label')];
      window.traceLayersRetained = () => savedTraceLayers.every(([layer, element]) =>
        traceGroup.hasLayer(layer) && layer.getElement() === element);
    }''')
    calls = len(trace_requests)
    # All three end events in a single task must result in one label pass.
    page.evaluate('''() => {
      traceMetrics.projections = 0;
      traceMap.fire('zoomend').fire('moveend').fire('resize', {oldSize:traceMap.getSize(), newSize:traceMap.getSize()});
    }''')
    settle(page)
    assert page.evaluate('traceMetrics.projections === 8'), page.evaluate('traceMetrics')
    assert page.evaluate('traceMetrics.reads === 0 && traceLayersRetained()')
    # Real zoom updates pixel-sized arrows without replacing SVG paths or labels.
    page.evaluate('''() => {
      window.traceArrows = traceGroup.getLayers().filter(layer => layer instanceof L.Polyline && layer.options.weight === 3 && layer.options.interactive === false)
        .map(layer => [layer, layer.getLatLngs()[0]]);
      traceMap.setZoom(11, {animate:false});
    }''')
    settle(page)
    assert page.evaluate('traceLayersRetained() && traceArrows.length > 0 && traceArrows.every(([layer, point]) => !layer.getLatLngs()[0].equals(point))')
    page.evaluate('traceMap.panBy([20,10], {animate:false})')
    settle(page)
    assert page.evaluate('traceLayersRetained() && traceMetrics.reads === 0'), page.evaluate('traceMetrics')
    assert page.evaluate('traceMetrics.circles === 0 && traceMetrics.lines === 0 && traceMetrics.markers === 0')
    # A real resize retains geometry and cached label sizes too.
    page.set_viewport_size(dict(width=1200, height=950))
    settle(page)
    assert page.evaluate('traceLayersRetained() && traceMetrics.reads === 0')

    # Keep a label just beyond the viewport in the prefetch margin.
    page.evaluate('''() => {
      const midpoint = traceMap.latLngToContainerPoint([52.05,10.05]);
      traceMap.panBy([midpoint.x + 100,0], {animate:false});
    }''')
    settle(page)
    assert page.evaluate('savedLabelBoxes[0].isConnected && traceMetrics.markers === 0 && traceMetrics.reads === 0')

    # Cull labels/leader lines, keep route geometry; returning reuses label DOM.
    page.evaluate('''() => {
      window.routeGeometry = savedTraceLayers.filter(([layer]) => layer instanceof L.Path && layer.options.className !== 'trace-snr-leader');
      traceMap.setView([0,0], 11, {animate:false});
    }''')
    settle(page)
    expect(page.locator('.trace-snr-label')).to_have_count(0)
    assert page.evaluate('routeGeometry.every(([layer, element]) => traceGroup.hasLayer(layer) && layer.getElement() === element)')
    assert page.evaluate('traceMetrics.markers === 0 && traceMetrics.reads === 0')
    page.evaluate('traceMap.setView([52.1,10.1], 11, {animate:false})')
    settle(page)
    expect(page.locator('.trace-snr-label')).to_have_count(4)
    assert page.evaluate('savedLabelBoxes.every(box => box.isConnected) && traceMetrics.markers === 0')
    reads = page.evaluate('traceMetrics.reads')
    page.evaluate("traceMap.fire('moveend')")
    settle(page)
    assert page.evaluate('traceMetrics.reads') == reads, 'Reattached label dimensions are cached again'

    # Font/CSS changes must invalidate sizes without losing collision avoidance.
    page.evaluate("savedLabelBoxes.forEach(box => box.style.fontSize = '18px')")
    settle(page)
    boxes = page.locator('.trace-snr-label').evaluate_all('''labels => labels.map(box => {
      const rect = box.getBoundingClientRect(); return {x:rect.x,y:rect.y,w:rect.width,h:rect.height};
    })''')
    for i, a in enumerate(boxes):
        for b in boxes[i+1:]:
            assert a['x']+a['w'] <= b['x'] or b['x']+b['w'] <= a['x'] or a['y']+a['h'] <= b['y'] or b['y']+b['h'] <= a['y'], (a,b)
    assert len(trace_requests) == calls, 'Map movement/resize/font changes never fetch archive data'

    # Removing blue recolors the retained orange route; adding a new selection
    # must leave that surviving geometry and label content intact.
    page.evaluate('''() => {
      window.orangeLayers = traceGroup.getLayers().filter(layer => layer.options.color === '#d97706').map(layer => [layer, layer.getElement()]);
      window.orangeLabels = [...document.querySelectorAll('.trace-snr-label[data-trace-id="4"]')];
    }''')
    page.locator('#map-trace-detail button').first.click()
    settle(page)
    expect(page.locator('.trace-snr-label')).to_have_count(2)
    assert page.evaluate("orangeLayers.length > 0 && orangeLayers.every(([layer, element]) => traceGroup.hasLayer(layer) && layer.getElement() === element && layer.options.color === '#3388ff')")
    assert page.evaluate("orangeLabels.every(box => box.isConnected && box.style.borderColor === 'rgb(51, 136, 255)')")
    # Existing circle interactivity and tooltip survive route recoloring.
    page.evaluate("orangeLayers.find(([layer]) => layer instanceof L.CircleMarker)[0].fire('mouseover')")
    expect(page.locator('#trace-map .leaflet-tooltip')).to_contain_text('#4')
    page.evaluate("orangeLayers.find(([layer]) => layer instanceof L.CircleMarker)[0].closeTooltip()")
    # Select a new route while looking far away. Suppress only the selection's
    # fitBounds in the harness so its first render really is outside the margin.
    page.evaluate('''() => {
      traceMap.setView([0,0], 11, {animate:false});
      window.traceFitBounds = traceMap.fitBounds;
      traceMap.fitBounds = function() { return this; };
      traceMetrics.markers = 0;
    }''')
    settle(page)
    page.locator('#map-trace-list input').nth(2).check()
    expect(page.locator('#map-trace-detail section')).to_have_count(2)
    settle(page)
    expect(page.locator('.trace-snr-label')).to_have_count(0)
    assert page.evaluate('traceMetrics.markers === 0'), 'An offscreen new route does not construct SNR-label DOM'
    page.evaluate('''() => {
      traceMap.fitBounds = traceFitBounds;
      traceMap.setView([52.1,10.1], 11, {animate:false});
    }''')
    settle(page)
    expect(page.locator('.trace-snr-label')).to_have_count(4)
    expect(page.locator('.trace-snr-value')).to_have_count(8)
    assert page.evaluate('traceMetrics.markers === 2 && orangeLabels.every(box => box.isConnected)'), 'Only the newly visible route creates labels'
    assert page.evaluate("orangeLayers.filter(([layer]) => layer.options.className !== 'trace-snr-leader').every(([layer, element]) => traceGroup.hasLayer(layer) && layer.getElement() === element)")
    assert page.locator('.trace-snr-label[data-trace-id="3"]').first.evaluate("box => box.style.borderColor") == 'rgb(217, 119, 6)'
    print('TRACE reuse: event coalescing, zoom, pan, resize, culling, size cache, collisions, tooltips and route changes passed', flush=True)



def grouped_flow(browser):
    from onair_trace import trace_sessions
    from test_trace import reception
    import time
    now = time.time() - 30
    names = {'aa'*32: 'Alpha', 'bb'*32: 'Beta'}
    rows = [(i, now+i, reception(route='aabbaabbaa', snrs=tuple(range(min(i, 5))),
             observer='east' if i % 2 else 'west')) for i in range(1, 11)]
    groups, _, _ = trace_sessions(rows, names, include_packets=True)
    assert len(groups) == 1
    for width, height in [(1280,900), (390,844), (844,390)]:
        page = browser.new_page(viewport=dict(width=width, height=height))
        errors, calls, details = [], [], []
        response_groups = groups
        page.on('pageerror', lambda e: errors.append(str(e)))
        route_page(page, [])
        def listing(route):
            calls.append(route.request.url)
            assert 'grouped=true' in route.request.url
            route.fulfill(json=dict(grouped=True, items=response_groups, scanned=10, before=None,
                                    truncated=False, total=1))
        page.route('**/api/map-traces?*', listing)
        def detail(route):
            identity = int(route.request.url.rsplit('/',1)[1])
            details.append(identity)
            items, _, _ = trace_sessions([rows[identity-1]], names)
            item = items[0]
            for hop in item['hops']:
                hop['position'] = dict(latitude=52 if hop['hash']=='aa' else 52.2, longitude=10)
            route.fulfill(json=item)
        page.route('**/api/map-traces/*', detail)
        page.goto('http://trace-groups.test/')
        page.locator('#tab-trace').click()
        assert page.evaluate('nodeMap === undefined'), 'TRACE opens independently of Map'
        assert not calls, 'Opening TRACE does not search the archive'
        page.locator('#map-trace-form button').click()
        expect(page.locator('#map-trace-list button')).to_have_count(1)
        expect(page.locator('#map-trace-list button')).to_contain_text('10 Empfänge')
        expect(page.locator('#map-trace-list button')).to_contain_text('2 Observer')
        page.locator('#map-trace-list button').click()
        expect(page.locator('#map-trace-detail h3')).to_contain_text('#10')
        expect(page.locator('#map-trace-summary')).to_contain_text('Beste Einzelabdeckung 5/5')
        expect(page.locator('#map-trace-summary')).to_contain_text('aggregiert')
        expect(page.locator('#map-trace-receptions input')).to_have_count(10)
        assert details == [10]
        assert page.locator('#map-trace-summary').bounding_box()['y'] < page.locator('#map-trace-receptions').bounding_box()['y']
        page.locator('#map-trace-receptions input[data-id="4"]').check()
        expect(page.locator('#map-trace-detail section')).to_have_count(2)
        expect(page.locator('#map-trace-detail h3').nth(1)).to_contain_text('Orange · #4')
        page.locator('#map-trace-receptions input[data-id="3"]').click()
        expect(page.locator('#map-trace-receptions input[data-id="3"]')).not_to_be_checked()
        page.locator('#map-trace-receptions input[data-id="10"]').uncheck()
        expect(page.locator('#map-trace-detail section')).to_have_count(1)
        expect(page.locator('#map-trace-detail h3')).to_contain_text('Blau · #4')
        page.locator('#tab-map').click()
        page.locator('#tab-trace').click()
        expect(page.locator('#map-trace-detail h3')).to_contain_text('#4')
        assert len(calls) == 1
        page.locator('#map-trace-summary button').click()
        assert page.locator('#trace-map').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('#map-trace-summary').scroll_into_view_if_needed()
        page.screenshot(path=f'/tmp/onair-trace-v2-{width}.png', full_page=True)
        # A bounded reception table paginates without fetching/correlating again.
        extra = [dict(id=100+i, received=now+i*.1, observer='east', observer_id='east',
                      observed_hops=0, weakest_snr=None) for i in range(51)]
        response_groups = [dict(groups[0], packets=groups[0]['packets'] + extra, receptions=61)]
        page.locator('#map-trace-first').fill('aa')
        page.locator('#map-trace-form button').click()
        expect(page.locator('#map-trace-list button')).to_contain_text('61 Empfänge')
        expect(page.locator('#map-trace-detail h3')).to_contain_text('#4')
        assert 'first=aa' in calls[-1]
        page.locator('#map-trace-list button').click()
        expect(page.locator('#map-trace-receptions input')).to_have_count(50)
        before_calls = len(calls)
        page.locator('#map-trace-receptions button', has_text='Weitere').click()
        expect(page.locator('#map-trace-receptions input')).to_have_count(11)
        page.locator('#map-trace-receptions button', has_text='Vorherige').click()
        expect(page.locator('#map-trace-receptions input')).to_have_count(50)
        assert len(calls) == before_calls
        assert not errors, errors
        page.close()


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
        page.route('**/api/traces?*', lambda route: route.fulfill(json=dict(items=[], histories=[], scanned=0)))
        page.goto('http://trace.test/')
        page.locator('#tab-map').click()
        page.wait_for_function('mapMarkers.size > 0')
        page.evaluate("setMapLinkMode('none'); selectMapRepeater([...mapMarkers.keys()][0])")
        page.locator('#tab-trace').click()
        assert page.locator('#panel-map').is_hidden()
        page.locator('#map-trace-form button').click()
        expect(page.locator('#map-trace-list input')).to_have_count(4)
        page.locator('#map-trace-list input').first.check()
        expect(page.locator('#map-trace-detail')).to_contain_text('Quelle: unbekannt')
        # Full route: 3 circles, 2 segments, 2 arrow polylines.
        expect(page.locator('#trace-map .leaflet-overlay-pane path:not(.trace-snr-leader)')).to_have_count(7)
        expect(page.locator('.trace-snr-label')).to_have_count(2)
        expect(page.locator('.trace-snr-value').nth(0)).to_have_text('→ +7,5 dB')
        expect(page.locator('.trace-snr-value').nth(1)).to_have_text('→ −10,5 dB')
        assert page.locator('.trace-snr-label').first.is_visible(), 'No hover needed'
        page.locator('#map-trace-list input').nth(1).check()
        expect(page.locator('#map-trace-detail')).to_contain_text('Historische Position unbekannt')
        # Unknown intermediate hop adds only 2 markers, never a bridge.
        expect(page.locator('#trace-map .leaflet-overlay-pane path:not(.trace-snr-leader)')).to_have_count(9)
        before = len(trace_requests)
        page.evaluate('traceMap.panBy([30, 20]); traceMap.setZoom(10)')
        page.wait_for_timeout(300)
        assert len(trace_requests) == before
        page.locator('#tab-map').click()
        assert page.locator('#panel-trace').is_hidden()
        assert page.locator('#trace-map').is_hidden()
        page.locator('#tab-trace').click()
        assert page.locator('#trace-map .leaflet-overlay-pane path:not(.trace-snr-leader)').count() == 9
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
        trace_count = page.locator('#trace-map .leaflet-overlay-pane path').count()
        for mode in ['none', 'all', 'selected']:
            page.evaluate('(mode) => setMapLinkMode(mode)', mode)
            expect(page.locator('.trace-snr-label')).to_have_count(4)
            expect(page.locator('.trace-snr-value')).to_have_count(8)
            assert page.locator('#trace-map .leaflet-overlay-pane path').count() == trace_count
        # Dense sections at regional zoom: both routes retain every value on mobile.
        page.evaluate('traceMap.setView([52.1,10.1], 7, {animate:false})')
        page.wait_for_timeout(300)
        boxes = page.locator('.trace-snr-label').evaluate_all('(labels)=>labels.map(e=>{const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}})')
        for i, a in enumerate(boxes):
            for b in boxes[i+1:]:
                assert a['x']+a['w'] <= b['x'] or b['x']+b['w'] <= a['x'] or a['y']+a['h'] <= b['y'] or b['y']+b['h'] <= a['y'], (a,b)
        for theme in ['light','dark']:
            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            page.locator('#trace-map').screenshot(path=f'/tmp/onair-trace-snr-{theme}.png')
        page.locator('#tab-map').click()
        expect(page.locator('#trace-map')).to_be_hidden()
        page.locator('#tab-trace').click()
        expect(page.locator('.trace-snr-value')).to_have_count(8)
        page.locator('#map-trace-period').select_option('custom')
        assert page.locator('#map-trace-start').is_enabled()
        assert not errors, errors
        before = len(trace_requests)
        page.locator('[data-view=history]').click()
        expect(page.locator('#trace-analysis')).to_be_visible()
        expect(page.locator('#trace-map')).to_be_hidden()
        expect(page.locator('#trace-status')).to_contain_text('Keine auswertbaren')
        page.locator('[data-view=map]').click()
        expect(page.locator('.trace-snr-value')).to_have_count(8)
        assert len(trace_requests) == before
        assert page.locator('#panel-map #map-traces').count() == 0
        assert not errors, errors
        performance_regression(page, trace_requests)
        assert not errors, errors
        grouped_flow(browser)
        browser.close()
        print('TRACE map desktop/mobile: passed')


if __name__ == '__main__':
    main()
