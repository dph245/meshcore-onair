"""Real Leaflet, offline HTTP/WS fixtures; no MQTT or production archive."""
from copy import deepcopy
from playwright.sync_api import sync_playwright, expect
from browser_meshlive import route_page, NODES, packet, emit
from browser_replay import fixture
from onair_trace import trace_sessions
from test_trace import reception

A, B = NODES[0]['public_key'], NODES[1]['public_key']
C = A[:6] + 'f' * 58
CHAT = A[:6] + 'e' * 58


def collision(page, number=100):
    p = packet(number)
    p['decoded'].update(advert={**NODES[0], 'public_key': C.upper(), 'timestamp': 200,
                                 'signature_status': 'Gültig'}, advert_status=None)
    emit(page, [], kind='snapshot', seq=0)
    emit(page, [p], kind='delta', seq=1, receptions=[p])


def new_page(browser):
    page = browser.new_page(viewport=dict(width=1280, height=900))
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    route_page(page, [])
    return page, errors


def main_and_live(browser):
    page, errors = new_page(browser)
    nodes = deepcopy(NODES[:2]) + [dict(NODES[0], public_key=CHAT, name='Companion', node_type=1)]

    def bootstrap(route):
        if route.request.url.endswith('mesh_live=true'):
            route.fulfill(json=dict(nodes=nodes, tokens=[], map_repeater_keys=[A, B]))
        else:
            route.fulfill(json=dict(items=nodes, repeaters=nodes[:2], without_position=0,
                                    inactive=0, map_repeater_keys=[A, B]))

    page.route('**/api/map-nodes*', bootstrap)
    page.goto('http://visibility.test/')
    page.locator('#tab-map').click()
    page.wait_for_function('mapMarkers.size === 3')
    # Coincident Companion and repeater have offset lines; removal must clean these too.
    assert page.evaluate('key => !!mapMarkers.get(key).line', A)
    page.evaluate('key => { selectMapRepeater(key); mapMarkers.get(key).marker.openPopup(); }', A)
    expect(page.locator('#node-map .leaflet-popup-content')).to_contain_text(A)
    page.evaluate('''([a,b]) => {
      renderMapNeighbors({items:[{source:{id:a,name:'A',resolved:true},
        target:{id:b,name:'B',resolved:true}, count:2, forward_count:1, reverse_count:1,
        last_seen:1, distance_km:3}]});
      setMapLinkMode('all');
      const view = [...mapConnectionViews.values()][0];
      view.line.fire('click', {latlng:mapMarkers.get(a).marker.getLatLng()});
    }''', [A, B])
    expect(page.locator('#node-map .leaflet-popup-content').last).to_contain_text('Luftlinie')
    assert page.evaluate('mapConnectionViews.size') == 1
    collision(page)
    page.wait_for_function('mapMarkers.size === 2')
    assert page.evaluate('mapConnectionViews.size') == 0
    assert page.evaluate('key => !mapMarkers.has(key) && selectedMapRepeater === null', A)
    expect(page.locator('#node-map .leaflet-popup-content')).to_have_count(0)
    expect(page.locator('#node-map .map-position-link')).to_have_count(0)
    assert page.evaluate('key => mapMarkers.has(key)', CHAT)
    # A stale server response cannot resurrect the marker.
    page.evaluate('loadMapNodes()')
    assert page.evaluate('key => !mapMarkers.has(key)', A)
    page.locator('#map-show-historical').check()
    page.locator('#map-repeater-search').fill(A)
    expect(page.locator('#map-repeater-results button')).to_be_disabled()
    expect(page.locator('#map-repeater-results')).to_contain_text('Hash-Präfix-Kollision')
    page.evaluate('key => openMapRepeater(key)', A)
    expect(page.locator('#map-repeater-search-status')).to_contain_text('Hash-Präfix-Kollision')
    page.locator('#tab-meshlive').click()
    expect(page.locator('#meshlive-map .map-marker')).to_have_count(2)
    assert A not in page.locator('#meshlive-map').inner_text()
    # Start a real canvas trail from the remaining repeater to the Companion.
    trail = packet(101, hops=[B[:6]])
    trail['origin_id'] = CHAT
    emit(page, [trail], kind='delta', seq=2, receptions=[trail])
    page.wait_for_function('window.__meshStrokes.length > 0')
    second = packet(102)
    second['decoded'].update(advert={**NODES[1], 'public_key': B[:6] + 'f' * 58,
        'timestamp': 200, 'signature_status': 'Gültig'}, advert_status=None)
    emit(page, [second], kind='delta', seq=3, receptions=[second])
    expect(page.locator('#meshlive-map .map-marker')).to_have_count(1)
    assert page.locator('#meshlive-map canvas').evaluate('''canvas => {
      const ctx = canvas.getContext('2d');
      return ctx.getImageData(0,0,canvas.width,canvas.height).data.every(value => value === 0);
    }'''), 'Previously drawn geographic trails are cleared immediately'
    assert not errors, errors
    page.close()


def trace(browser):
    page, errors = new_page(browser)
    rows = [(1, 1700000000, reception(route='aabb', snrs=(3, 4)))]
    groups, _, _ = trace_sessions(rows, {A: 'A', B: 'B'}, include_packets=True)
    detail = deepcopy(groups[0])
    for hop, node in zip(detail['hops'], NODES):
        hop.update(node_type=2, position=dict(latitude=node['latitude'], longitude=node['longitude']))
    detail['map_repeater_keys'] = [A, B]
    page.route('**/api/map-traces?*', lambda route: route.fulfill(json=dict(
        grouped=True, items=groups, scanned=1, before=None, truncated=False, total=1)))
    page.route('**/api/map-traces/1', lambda route: route.fulfill(json=detail))
    page.goto('http://trace-visibility.test/')
    page.locator('#tab-trace').click()
    page.locator('#trace-views [data-view=map]').click()
    page.locator('#map-trace-form button').click()
    page.locator('#map-trace-list button').click()
    expect(page.locator('#trace-map .leaflet-interactive')).to_have_count(3)
    expect(page.locator('#trace-map .trace-snr-label')).to_have_count(1)
    assert page.evaluate('nodeMap === undefined'), 'TRACE must work without opening the main map'
    collision(page)
    expect(page.locator('#trace-map .leaflet-interactive')).to_have_count(1)
    expect(page.locator('#trace-map .trace-snr-label')).to_have_count(0)
    expect(page.locator('#map-trace-detail')).to_contain_text('SNR: 3 dB')
    expect(page.locator('#map-trace-detail')).to_contain_text('SNR: 4 dB')
    assert not errors, errors
    page.close()


def replay(browser):
    page, errors = new_page(browser)
    data = fixture()
    data['bootstrap']['map_repeater_keys'] = [node['public_key'] for node in NODES]
    page.route('**/api/meshlive/replay', lambda route: route.fulfill(json=data))
    page.goto('http://replay-visibility.test/')
    page.locator('#tab-meshlive').click()
    expect(page.locator('#meshlive-map .map-marker')).to_have_count(4)
    page.locator('#meshlive-replay-start').click()
    expect(page.locator('#meshlive-replay-badge')).to_be_visible()
    page.locator('#meshlive-replay-pause').click()
    expect(page.locator('#meshlive-map .map-marker')).to_have_count(4)
    collision(page)
    expect(page.locator('#meshlive-map .map-marker')).to_have_count(3)
    expect(page.locator('#meshlive-replay-badge')).to_be_visible()
    assert not errors, errors
    page.close()


def loading_replay(browser):
    page, errors = new_page(browser)
    keys = [node['public_key'] for node in NODES]
    page.route('**/api/map-nodes?mesh_live=true', lambda route: route.fulfill(
        json=dict(nodes=NODES, tokens=[], map_repeater_keys=keys)))
    pending = []
    page.route('**/api/meshlive/replay', lambda route: pending.append(route))
    page.goto('http://loading-visibility.test/')
    page.locator('#tab-meshlive').click()
    expect(page.locator('#meshlive-map .map-marker')).to_have_count(4)
    page.locator('#meshlive-replay-start').click()
    expect(page.locator('#meshlive-status')).to_contain_text('Replay wird geladen')
    collision(page)
    expect(page.locator('#meshlive-map .map-marker')).to_have_count(3)
    pending[0].fulfill(json={**fixture(), 'bootstrap': {
        **fixture()['bootstrap'], 'map_repeater_keys': keys}})
    expect(page.locator('#meshlive-replay-badge')).to_be_visible()
    expect(page.locator('#meshlive-map .map-marker')).to_have_count(3)
    assert not errors, errors
    page.close()


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                     args=['--no-sandbox'])
        main_and_live(browser)
        trace(browser)
        replay(browser)
        loading_replay(browser)
        browser.close()
    print('Map visibility browser: offset lines, popups, stale snapshots, MeshLive, TRACE and paused replay passed')


if __name__ == '__main__':
    main()
