"""All tabs, offline fixtures, touch and local overflow at seven viewport sizes.

Uses the existing Playwright/Chromium harness; never starts MQTT or a database.
Screenshots are written to /tmp/onair-responsive/.
"""
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
from browser_meshlive import route_page, emit, packet, NODES, KEYS, NOW

SIZES = [(320, 568), (375, 667), (390, 844), (430, 932), (667, 375), (844, 390), (932, 430), (768, 1024), (1440, 900)]
LONG = 'Bergstation-' + 'Langname' * 12


def fixtures(page):
    route_page(page, [])
    nodes = [dict(n, name=LONG if i == 0 else n['name']) for i, n in enumerate(NODES)]
    hop = dict(hash='aabb', name=LONG, snr_min=4, snr_max=6)
    source = dict(id=KEYS[0], name=LONG, resolved=True)
    target = dict(id=KEYS[1], name='Ziel', resolved=True)
    link = dict(source=source, target=target, forward_count=4, reverse_count=2,
                count=6, last_seen=NOW, distance_km=5)
    observer = lambda i: dict(origin_id=KEYS[i], origin=LONG if i == 2 else 'Observer B',
                             count=10, best_rssi=-80, best_snr=9, last_seen=NOW)
    data = {
        '/api/observer-comparison': dict(observers=[observer(2), observer(3)],
            items=[dict(id=KEYS[0], name=LONG, tokens=['aabb'], observers=[observer(2), observer(3)])]),
        '/api/repeaters': dict(items=[dict(id=KEYS[0], name=LONG, tokens=['aabb'], count=10,
            rssi=-80, min_rssi=-100, max_rssi=-70, last_seen=NOW)]),
        '/api/repeater-history': dict(items=[dict(received=NOW-i*60, rssi=-80-i, snr=5,
            origin='Observer', origin_id=KEYS[2]) for i in [2, 1, 0]], has_more=False),
        '/api/channels': dict(channels=['Public']),
        '/api/archive': dict(items=[dict(id=1, packet=packet(1))], next_before=None),
        '/api/nodes': dict(items=nodes, next_after=None),
        '/api/repeater-neighbors/table': dict(items=[link], total=1, total_all=1, one_way_total=0, page=0),
        '/api/routes/nodes': dict(items=[source, target]),
        '/api/routes': dict(start=source, target=target, excluded_links=0, routes=[dict(hops=1,
            one_way_steps=0, unobserved_steps=0, distance_km=5, nodes=[source, target], steps=[link])]),
        '/api/discovery': dict(scanned=1, items=[dict(id=1, first_seen=NOW, request=None,
            tag='abcdef', scope=LONG, receptions=1, observers=[], responses=[dict(name=LONG,
                node_type='Repeater', snr_min=4, snr_max=6, receptions=1, public_key=KEYS[0])])]),
        '/api/traces': dict(scanned=1, items=[dict(id=1, first_seen=NOW, weakest_snr=4,
            weakest_hops=[1], observed_hops=1, hops=[hop], tag='abcdef', scope=LONG,
            receptions=1, observers=[])], histories=[dict(id=1, route=[hop], scope=LONG, point_count=3,
                points=[dict(time=NOW-i*60, tag='abc', snr_min=[4+i], snr_max=[6+i]) for i in [2, 1, 0]])]),
    }
    def api(route):
        path = urlparse(route.request.url).path
        if path in data:
            route.fulfill(json=data[path])
        else:
            route.fallback()
    page.route('**/api/**', api)


def layout(page, name):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), name
    assert page.evaluate('document.querySelector("main").scrollWidth <= document.querySelector("main").clientWidth'), (name, 'main overflow')
    # Every visible control must fit horizontally unless it belongs to an explicit
    # table/chart scroller or the tab strip. Vertical scrolling is intentional.
    bad = page.locator('[role=tabpanel]:visible').evaluate('''panel => [...panel.querySelectorAll('button,input,select,summary')].filter(e => {
      if (!e.getClientRects().length || e.closest('.noise-scroll,.live-table-scroll,.leaflet-pane')) return false;
      const r=e.getBoundingClientRect(); return r.left < -1 || r.right > innerWidth+1;
    }).map(e=>e.id || e.outerHTML.slice(0,100))''')
    assert not bad, (name, bad)
    tab = page.locator('[role=tab][aria-selected=true]').bounding_box()
    assert tab['x'] >= -1 and tab['x'] + tab['width'] <= page.viewport_size['width']+1, (name, tab)


def tap(page, selector):
    page.locator(selector).tap()


def main():
    output = Path('/tmp/onair-responsive'); output.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        for width, height in SIZES:
            page = browser.new_page(viewport=dict(width=width, height=height), has_touch=True)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            fixtures(page)
            page.goto('http://responsive.test/')
            emit(page, [packet(1)], 'snapshot')
            tabs = page.locator('[role=tab]').evaluate_all('(els)=>els.map(e=>e.id)')
            for tab in tabs:
                tap(page, '#' + tab)
                name = tab.removeprefix('tab-')
                panel = page.locator('#panel-' + name)
                if name == 'live':
                    if page.locator('#live-filter-toggle').is_visible():
                        tap(page, '#live-filter-toggle')
                    page.locator('#live-repeater').fill('missing')
                    expect(page.locator('#packets tr.packet')).to_have_count(0)
                    tap(page, '#live-filter-reset')
                    expect(page.locator('#packets tr.packet')).to_have_count(1)
                    if page.locator('#live-filter-toggle').is_visible():
                        tap(page, '#live-filter-toggle')
                    tap(page, '#packets .expand')
                    expect(page.locator('#packets .reception')).to_have_count(1)
                    scroll = page.locator('.live-table-scroll')
                    if width < 950:
                        assert scroll.evaluate('(e)=>e.scrollWidth>e.clientWidth')
                    scroll.evaluate('(e)=>e.scrollLeft=e.scrollWidth')
                    assert page.evaluate('scrollX===0')
                    tap(page, '#pause'); emit(page, [packet(2)])
                    expect(page.locator('#packets tr.packet')).to_have_count(1)
                    tap(page, '#pause')
                    expect(page.locator('#packets tr.packet')).to_have_count(2)
                elif name == 'raw':
                    tap(page, '#raw-follow'); assert not page.locator('#raw-follow').is_checked()
                    assert 'raw fixture' in page.locator('#raw-output').inner_text()
                elif name == 'observers':
                    page.locator('#observer-east').select_option(KEYS[2])
                    page.locator('#observer-west').select_option(KEYS[3])
                    expect(page.locator('#observers-results tbody tr')).to_have_count(1)
                elif name == 'repeaters':
                    expect(page.locator('.repeater-chart')).to_be_visible()
                elif name == 'channels':
                    tap(page, '#channels-results summary')
                elif name in ('archive', 'nodes'):
                    tap(page, f'#{name}-search button')
                    expect(page.locator(f'#{name}-results .reception').first).to_be_visible()
                    if name == 'archive': tap(page, '#archive-results summary')
                elif name == 'map':
                    tap(page, '#map-fit')
                    page.locator('#map-link-mode').select_option('selected')
                    marker = page.locator('#node-map .map-marker').first
                    marker.scroll_into_view_if_needed()
                    page.wait_for_timeout(350)
                    marker.tap()
                    expect(page.locator('#node-map .leaflet-popup')).to_be_visible()
                    popup = page.locator('#node-map .leaflet-popup')
                    map_box = page.locator('#node-map').bounding_box()
                    popup_box = popup.bounding_box()
                    assert popup_box['height'] <= map_box['height'], (map_box, popup_box)
                    tap(page, '#node-map .leaflet-popup-close-button')
                    expect(popup).to_be_hidden()
                elif name == 'neighbors':
                    tap(page, '#neighbors-one-way')
                    page.locator('#map-neighbors-search').fill('Berg')
                    tap(page, '#neighbors-sort-source')
                    expect(page.locator('#map-neighbors-list tr')).to_have_count(2)
                elif name == 'routes':
                    page.locator('#routes-start').fill(KEYS[0])
                    page.locator('#routes-target').fill(KEYS[1])
                    tap(page, '#routes-swap')
                    assert page.locator('#routes-start').input_value() == KEYS[1]
                    tap(page, '#routes-submit')
                    expect(page.locator('.route-card')).to_be_visible()
                elif name == 'discovery':
                    tap(page, '#discovery-results summary')
                elif name == 'trace':
                    expect(page.locator('.trace-chart')).to_be_visible()
                    tap(page, '#trace-results summary')
                    page.locator('.trace-chart circle').first.tap()
                    expect(page.locator('#trace-history [role=status]')).to_contain_text('SNR')
                elif name == 'noise':
                    page.evaluate('''()=>{const samples=[0,1,2].map(i=>({received_at:new Date(Date.now()-i*60000).toISOString(), noise_floor:-110-i, origin:'Observer', origin_id:'abc'}));status.noise_history=samples;renderNoise(samples)}''')
                    expect(page.locator('.noise-chart')).to_be_visible()
                    page.locator('#noise-charts .noise-point').first.tap()
                    expect(page.locator('.noise-tooltip')).to_contain_text('dBm')
                elif name == 'meshlive':
                    expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes')
                layout(page, (width, height, name))
                page.screenshot(path=str(output / f'{width}x{height}-{name}.png'))
            # Keyboard navigation and resize keep the selected tab in the strip.
            page.locator('#tab-meshlive').focus()
            page.keyboard.press('Home')
            expect(page.locator('#tab-live')).to_have_attribute('aria-selected', 'true')
            page.keyboard.press('End')
            for w, h in [(height, width), (width, height)]:
                page.set_viewport_size(dict(width=w, height=h))
                page.wait_for_timeout(100)
                layout(page, (w, h, 'rotation'))
            assert not errors, errors
            print(f'{width}x{height}: all 14 tabs, populated details, forms, navigation and overflow passed', flush=True)
            page.close()
        browser.close()


if __name__ == '__main__':
    main()
