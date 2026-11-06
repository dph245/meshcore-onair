"""Offline historical repeater selection with real Leaflet; no production writes."""
from copy import deepcopy

from playwright.sync_api import sync_playwright, expect
from browser_meshlive import NODES, route_page


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                    args=['--no-sandbox'])
        for width, height in [(1280, 900), (390, 844)]:
            page = browser.new_page(viewport=dict(width=width, height=height))
            errors, requests = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            route_page(page, requests)
            old = dict(deepcopy(NODES[0]), name='FZ-ZGORA-OS17', historical=True,
                       latitude=51.93545, longitude=15.52704,
                       last_seen=NODES[0]['last_seen'] - 38 * 86400)
            nodes = [old, deepcopy(NODES[1])]
            def respond(route):
                route.fulfill(json=dict(items=nodes, repeaters=[
                    dict(public_key=n['public_key'], name=n['name'], historical=n.get('historical', False))
                    for n in nodes], inactive=1, without_position=0))
            page.route('**/api/map-nodes', respond)
            page.goto('http://history.test/')
            page.locator('#tab-map').click()
            expect(page.locator('#node-map .map-marker')).to_have_count(2)
            expect(page.locator('#node-map .map-historical')).to_have_count(1)
            expect(page.locator('#node-map .map-historical .map-neighbor-dot')).to_have_css('background-color', 'rgb(102, 114, 124)')
            search = page.locator('#map-repeater-search')
            search.fill('fz-zgora-os17')
            result = page.locator('#map-repeater-results button')
            expect(result).to_be_enabled()
            expect(result).to_contain_text('Historischer Standort')
            result.click()
            popup = page.locator('#node-map .leaflet-popup-content')
            expect(popup).to_contain_text('Historischer Standort')
            expect(popup).to_contain_text('51.935450, 15.527040')
            expect(page.locator('#node-map .map-historical .map-node-symbol')).to_have_css('border-top-style', 'dashed')
            assert page.evaluate('selectedMapRepeater') == old['public_key']
            assert page.evaluate('nodeMap.getZoom()') >= 12
            expect(page.locator('#map-dx-analysis')).to_be_enabled()
            page.evaluate('loadMapNodes()')
            expect(popup).to_contain_text('Historischer Standort')
            # The DX-to-Map entry point also opens an old stored location.
            page.locator('#tab-dx').click()
            page.evaluate('(key) => openMapRepeater(key)', old['public_key'])
            expect(page.locator('#panel-map')).to_be_visible()
            expect(popup).to_contain_text('FZ-ZGORA-OS17')
            # A newly received ADVERT removes the historical styling on refresh.
            old.update(historical=False, last_seen=NODES[0]['last_seen'])
            page.wait_for_function('!mapLoading')
            page.evaluate('loadMapNodes()')
            expect(page.locator('#node-map .map-historical')).to_have_count(0)
            expect(popup).not_to_contain_text('Historischer Standort')
            assert page.evaluate('selectedMapRepeater') == old['public_key']
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors
            page.close()
        browser.close()
    print('Historical map: desktop/mobile search, popup, DX navigation and reactivation passed')


if __name__ == '__main__':
    main()
