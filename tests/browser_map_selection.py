"""Offline real-Leaflet checks for selective links; no server, MQTT or production DB."""
from copy import deepcopy
from playwright.sync_api import sync_playwright, expect
from browser_meshlive import route_page, NODES

KEYS = [prefix.ljust(64, '0') for prefix in ['dd4c42a1', 'dd4c42d1', 'dd4c42b1', 'eeeeffff']]
NAMES = ['Funkfeuer Bridge 02', 'Funkfeuer Ampleben', 'Früherer Kandidat <test>', 'Fernstation']
NODES = [dict(deepcopy(node), public_key=KEYS[i], name=NAMES[i]) for i, node in enumerate(NODES)]
NODES[3].update(latitude=-33.9, longitude=151.2)
DIRECTORY = [dict(public_key=n['public_key'], name=n['name']) for n in NODES]
DIRECTORY += [dict(public_key='dd4c42c1'.ljust(64, '0'), name='Ohne Position', unavailable='Keine bekannte Kartenposition')]
LINKS = dict(nodes=[[n['public_key'], n['name']] for n in NODES],
             links=[[0, 1, 10, 7, 3, 100, 4], [1, 2, 8, 8, 0, 101, 3],
                    [0, 3, 2, 0, 2, 102, 16000]], total=3)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                     args=['--no-sandbox', '--disable-dev-shm-usage'])
        for width, height in [(1280, 900), (390, 844), (320, 568), (844, 390)]:
            page = browser.new_page(viewport=dict(width=width, height=height))
            errors, requests = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            route_page(page, requests)
            page.add_init_script("localStorage.setItem('onair-map-neighbors', 'true')")
            page.route('**/api/map-nodes', lambda route: route.fulfill(json=dict(
                items=NODES, repeaters=DIRECTORY, inactive=0, without_position=1)))
            link_calls = []
            def links(route):
                link_calls.append(route.request.url)
                route.fulfill(json=LINKS, headers={'ETag':'"map-v1"'})
            page.route('**/api/repeater-neighbors/map', links)
            page.goto('http://selection.test/')
            page.locator('#tab-map').click()
            expect(page.locator('#node-map .map-marker')).to_have_count(4)
            expect(page.locator('#map-link-mode')).to_have_value('selected')
            assert page.evaluate('neighborLayer.getLayers().length') == 0
            assert not link_calls, 'No initial complete link request'
            assert page.locator('#map-repeater-search').bounding_box()['y'] < page.locator('#node-map').bounding_box()['y']
            # Search must expose all colliding full keys, without choosing one.
            search = page.locator('#map-repeater-search')
            search.fill('DD4C42')
            expect(page.locator('#map-repeater-results button')).to_have_count(4)
            expect(page.locator('#map-repeater-results button').last).to_be_disabled()
            assert page.locator('#map-repeater-results test').count() == 0
            search.press('Enter')
            assert page.evaluate('selectedMapRepeater') is None
            page.locator('#map-repeater-results button').first.click()
            expect(page.locator('#map-selected-repeater')).to_contain_text(NAMES[0])
            expect(page.locator('#node-map .map-repeater-selected')).to_have_count(1)
            expect(page.locator('#node-map .leaflet-popup-content')).to_contain_text(KEYS[0])
            expect(page.locator('#node-map .map-marker')).to_have_count(4)
            page.wait_for_function('neighborLayer.getLayers().length === 5')
            assert len(link_calls) == 1
            assert page.evaluate('neighborLayer.getLayers().filter(l => l.options.bubblingMouseEvents === false).length') == 2
            # The 16,000 km link is retained, even though its second marker is offscreen.
            assert page.evaluate('neighborLayer.getLayers().some(l => l.getLatLngs().some(p => p.lat < 0))')
            page.evaluate('nodeMap.closePopup(); nodeMap.panBy([30,20], {animate:false}); nodeMap.setZoom(11, {animate:false})')
            assert page.evaluate('selectedMapRepeater') == KEYS[0]
            assert len(link_calls) == 1
            # Actual marker interaction replaces the selection; other markers stay in the layer.
            page.evaluate('(key) => nodeMap.setView(mapMarkers.get(key).marker.getLatLng(), 12, {animate:false})', KEYS[1])
            page.evaluate('(key) => mapMarkers.get(key).marker.getElement().click()', KEYS[1])
            expect(page.locator('#map-selected-repeater')).to_contain_text(NAMES[1])
            assert page.evaluate('neighborLayer.getLayers().length') == 5
            assert page.evaluate('neighborLayer.getLayers().every(l => l.getLatLngs().every(p => p.lat > 0))')
            page.locator('#map-link-mode').select_option('none')
            assert page.evaluate('neighborLayer.getLayers().length') == 0
            assert page.evaluate('selectedMapRepeater') == KEYS[1]
            page.locator('#map-link-mode').select_option('all')
            assert page.evaluate('neighborLayer.getLayers().length') == 7
            page.locator('#map-link-mode').select_option('selected')
            assert page.evaluate('neighborLayer.getLayers().length') == 5
            page.locator('#map-neighbors-reset').click()
            assert page.evaluate('neighborLayer.getLayers().length') == 0
            expect(page.locator('#node-map .map-repeater-selected')).to_have_count(0)
            expect(page.locator('#node-map .map-marker')).to_have_count(4)
            search.fill('ampleben')
            expect(page.locator('#map-repeater-results button')).to_have_count(1)
            page.locator('#map-repeater-results button').click()
            search.fill(KEYS[3])
            expect(page.locator('#map-repeater-results button')).to_have_count(1)
            page.locator('#map-repeater-results button').click()
            assert page.evaluate('selectedMapRepeater') == KEYS[3]
            assert page.evaluate('nodeMap.getCenter().lat') < 0
            assert len(link_calls) == 1, 'Switches, search and zoom reuse links'
            page.locator('[data-mode=nodes]').click()
            expect(page.locator('#map-link-mode')).to_have_value('none')
            assert page.evaluate('neighborLayer.getLayers().length') == 0
            page.locator('[data-mode=paths]').click()
            expect(page.locator('#map-link-mode')).to_have_value('selected')
            assert page.evaluate('neighborLayer.getLayers().length') == 2
            page.locator('[data-mode=traces]').click()
            for mode in ['all', 'none', 'selected']:
                page.locator('#map-link-mode').select_option(mode)
                assert page.evaluate('neighborLayer.getLayers().length') == 0
            page.locator('[data-mode=paths]').click()
            expect(page.locator('#node-map .map-repeater-selected')).to_have_count(1)
            # Explicit refresh must preserve selection and highlighting.
            page.evaluate('loadMapNodes()')
            assert page.evaluate('selectedMapRepeater') == KEYS[3]
            if width == 1280:
                page.evaluate('''() => { mapRepeaterDirectory = Array.from({length: 35}, (_, i) => ({
                    name: `Bulk candidate ${i}`, public_key: String(i).padStart(64, '0'), unavailable: 'Keine bekannte Kartenposition'
                })); }''')
                search.fill('bulk')
                expect(page.locator('#map-repeater-results button')).to_have_count(30)
                page.locator('#map-repeater-more').click()
                expect(page.locator('#map-repeater-results button')).to_have_count(35)
                search.fill('not-found')
                expect(page.locator('#map-repeater-results button')).to_have_count(0)
                expect(page.locator('#map-repeater-search-status')).to_contain_text('0 bekannte')
                search.fill('')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('#node-map').bounding_box()['height'] >= 100
            page.screenshot(path=f'/tmp/onair-map-selection-{width}x{height}.png', full_page=True)
            assert not errors, errors
            page.close()
        browser.close()
    print('Selective map links: four desktop/mobile sizes, modes, collisions, search, far links, context and request counts passed')


if __name__ == '__main__':
    main()
