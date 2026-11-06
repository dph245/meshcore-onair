"""Offline desktop/mobile analysis UI; no MQTT, running server, or production DB."""
import copy
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect
from browser_meshlive import route_page, NODES

A, B = '3134db'.ljust(64, '0'), '3c4afc'.ljust(64, '0')
START = 1790546400
LINK = dict(source=dict(id=A, name='Auersberg <test>', resolved=True),
            target=dict(id=B, name='Wendland', resolved=True), distance_min_km=308.498,
            distance_max_km=308.498, packets=9, receptions=107, paths=24,
            forward_packets=8, reverse_packets=1, forward_receptions=106, reverse_receptions=1,
            first_seen=START, last_seen=START+3600, forward_first=START,
            forward_last=START+3600, reverse_first=START+60, reverse_last=START+60,
            days=[dict(label='2026-09-28', forward=8, reverse=1, forward_receptions=106, reverse_receptions=1)],
            hours=[dict(label=f'{h:02}', forward=8 if h == 2 else 0, reverse=1 if h == 10 else 0,
                        forward_receptions=106 if h == 2 else 0, reverse_receptions=1 if h == 10 else 0) for h in range(24)])
BASE = dict(start=START, end=START+3*86400, timezone='Europe/Berlin', packet_count=9,
            missing_position_pairs=0, missing_at_reception=0, archive_first=START, archive_last=START+3600)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                     args=['--no-sandbox', '--disable-dev-shm-usage'])
        page = browser.new_page(viewport={'width':1280, 'height':900}, timezone_id='Europe/Berlin')
        errors, requests, analysis = [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        route_page(page, requests)
        map_nodes = [dict(copy.deepcopy(NODES[i]), public_key=endpoint['id'], name=endpoint['name'])
                     for i, endpoint in enumerate((LINK['source'], LINK['target']))]
        page.route('**/api/map-nodes', lambda route: route.fulfill(json=dict(
            items=map_nodes, repeaters=[dict(public_key=n['public_key'], name=n['name']) for n in map_nodes],
            inactive=0, without_position=0)))
        page.route('**/api/repeater-neighbors/map', lambda route: route.fulfill(json=dict(
            nodes=[[n['public_key'], n['name']] for n in map_nodes],
            links=[[0,1,9,8,1,START+3600,308.498]], total=1)))
        failure = [False]
        reject_overview = [False]
        neighbor = copy.deepcopy(LINK)
        neighbor.update(first_seen=START - 40 * 86400, last_seen=START+3600,
                        distance_km=70.2, count=57425, forward_count=57425, reverse_count=0)
        page.route('**/api/repeater-neighbors/table?*', lambda route: route.fulfill(json=dict(
            items=[neighbor], page=0, total=1, total_all=1, one_way_total=1)))
        def handle(route):
            q = parse_qs(urlparse(route.request.url).query); analysis.append(q)
            if failure[0]: route.fulfill(status=422, json={'detail':'Bitte Zeitraum verkürzen.'}); return
            if 'source' not in q:
                if reject_overview[0]:
                    route.fulfill(status=422, json={'detail':'Mehr als 25.000 passende Empfänge.'})
                else:
                    route.fulfill(json=dict(BASE, items=[LINK]))
                return
            offset = int(q.get('offset', ['0'])[0])
            rows = [dict(id=i+1, received=START+i, kind='ADVERT', directions=['reverse' if i == 0 else 'forward'],
                         observer='<Observer>', observer_hash='ABCD', route='FLOOD', packet_key='a'*64,
                         path=['3c4afc','3134db','dad317'] if i == 0 else ['3134db','3c4afc','dad317'])
                    for i in range(offset, min(offset+100,107))]
            route.fulfill(json=dict(BASE, link=LINK, evidence=rows, more=offset+100<107))
        page.route('**/api/repeater-neighbors/analysis?*', handle)
        page.goto('http://distance.test/')
        page.locator('#tab-dx').click()
        expect(page.locator('#panel-dx')).to_be_visible()
        expect(page.locator('#distance-form')).to_be_visible()
        expect(page.locator('#panel-neighbors')).to_be_hidden()
        assert not analysis, 'Opening DX must not scan the archive'
        page.locator('#distance-example').click()
        expect(page.locator('#distance-status')).to_contain_text('1 Fernverbindungen')
        assert analysis[-1]['start'] == [str(START)]
        assert analysis[-1]['end'] == [str(START+3*86400)]
        # Cold map start must wait for markers before selecting the source.
        page.locator('#distance-links .distance-node').first.click()
        expect(page.locator('#panel-map')).to_be_visible()
        page.wait_for_function('(key) => selectedMapRepeater === key', arg=A)
        expect(page.locator('#node-map .map-repeater-selected')).to_have_count(1)
        expect(page.locator('#map-link-mode')).to_have_value('selected')
        expect(page.locator('#node-map .leaflet-popup-content')).to_contain_text('Auersberg <test>')
        page.wait_for_function('neighborLayer.getLayers().length > 0')
        expect(page.locator('#map-dx-analysis')).to_be_enabled()
        before = len(analysis)
        page.locator('#map-dx-analysis').click()
        expect(page.locator('#panel-dx')).to_be_visible()
        expect(page.locator('#distance-status')).to_contain_text('Nachbarverbindung')
        expect(page.locator('#distance-links .distance-analyze')).to_have_count(1)
        expect(page.locator('#distance-links .distance-analyze')).to_contain_text('Wendland')
        assert len(analysis) == before, 'Choosing a repeater must not scan unrelated links'
        page.locator('#distance-start').fill('2026-09-28T00:00')
        page.locator('#distance-form button[type=submit]').click()
        expect(page.locator('#distance-status')).to_contain_text('zuerst eine Nachbarverbindung')
        expect(page.locator('#distance-links .distance-analyze')).to_have_count(1)
        assert len(analysis) == before, 'A node-only selection must never start a global scan'
        page.locator('#distance-links .distance-analyze').click()
        expect(page.locator('#distance-status')).to_contain_text('100 Einzelbelege')
        assert analysis[-1]['source'] == [A] and analysis[-1]['target'] == [B]
        assert float(analysis[-1]['end'][0]) - float(analysis[-1]['start'][0]) <= 31 * 86400
        assert page.locator('#distance-evidence details').count() == 100
        assert page.locator('.distance-bin').count() == 25
        assert page.locator('#distance-detail test').count() == 0
        page.locator('#distance-evidence details').first.locator('summary').click()
        expect(page.locator('.distance-path').first).to_have_text('3c4afc → 3134db → dad317')
        expect(page.locator('#distance-evidence details').first).to_contain_text('<Observer>')
        page.locator('#distance-more').click()
        expect(page.locator('#distance-status')).to_contain_text('107 Einzelbelege')
        assert page.locator('#distance-evidence details').count() == 107
        expect(page.locator('#distance-more')).to_be_hidden()
        # Reusing an initialized map also restores path mode and neighbor links.
        page.locator('#tab-map').click()
        page.locator('#map-link-mode').select_option('none')
        page.locator('#map-modes [data-mode="nodes"]').click()
        page.locator('#tab-dx').click()
        page.locator('#distance-detail .distance-node').last.click()
        page.wait_for_function('(key) => selectedMapRepeater === key', arg=B)
        expect(page.locator('#map-link-mode')).to_have_value('selected')
        expect(page.locator('#map-modes [data-mode="paths"]')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#node-map .leaflet-popup-content').filter(has_text='Wendland')).to_be_visible()
        page.evaluate('''() => neighborLayer.getLayers()
            .find(layer => layer.options.bubblingMouseEvents === false)
            .fire('click', {latlng:nodeMap.getCenter()})''')
        page.locator('#node-map .leaflet-popup-content button', has_text='DX-Analyse').click()
        expect(page.locator('#panel-dx')).to_be_visible()
        expect(page.locator('#distance-status')).to_contain_text('100 Einzelbelege')
        assert analysis[-1]['source'] == [A] and analysis[-1]['target'] == [B]
        page.set_viewport_size({'width':390,'height':844})
        page.locator('#distance-detail').scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'No mobile page overflow'
        for theme in ['dark','light']:
            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            page.locator('#distance-detail').screenshot(path=f'/tmp/onair-distance-{theme}.png')
        page.locator('#distance-minimum').select_option('250')
        expect(page.locator('#distance-detail')).to_be_empty()
        page.locator('#distance-form button[type=submit]').click()
        expect(page.locator('#distance-status')).to_contain_text('100 Einzelbelege')
        assert analysis[-1]['minimum'] == ['250']
        assert analysis[-1]['source'] == [A]
        failure[0] = True
        page.locator('#distance-form button[type=submit]').click()
        expect(page.locator('#distance-status')).to_contain_text('Bitte Zeitraum verkürzen.')
        expect(page.locator('#distance-links')).to_be_empty()
        # Click the actual table action: a local 70-km link must not run an overview.
        failure[0] = False
        reject_overview[0] = True
        before = len(analysis)
        page.locator('#tab-neighbors').click()
        page.locator('#map-neighbors-list button', has_text='Analysieren').click()
        expect(page.locator('#tab-dx')).to_have_attribute('aria-selected', 'true')
        expect(page.locator('#panel-neighbors')).to_be_hidden()
        expect(page.locator('#distance-status')).to_contain_text('100 Einzelbelege')
        assert len(analysis) == before + 1
        assert analysis[-1]['source'] == [A]
        assert analysis[-1]['target'] == [B]
        assert analysis[-1]['minimum'] == ['0']
        assert float(analysis[-1]['end'][0]) - float(analysis[-1]['start'][0]) <= 31 * 86400
        expect(page.locator('#distance-scope')).to_contain_text('Auersberg <test> [3134db]')
        page.locator('#distance-start').fill('2026-09-28T00:00')
        page.locator('#distance-form button[type=submit]').click()
        expect(page.locator('#distance-status')).to_contain_text('100 Einzelbelege')
        assert analysis[-1]['source'] == [A]
        page.locator('#distance-more').click()
        expect(page.locator('#distance-status')).to_contain_text('107 Einzelbelege')
        assert analysis[-1]['target'] == [B]
        assert analysis[-1]['offset'] == ['100']
        # Tab changes preserve the selected pair and its loaded evidence.
        before = len(analysis)
        page.locator('#tab-neighbors').click()
        page.locator('#tab-neighbors').focus()
        page.keyboard.press('ArrowRight')
        expect(page.locator('#tab-rf-neighbors')).to_be_focused()
        page.keyboard.press('ArrowRight')
        expect(page.locator('#tab-dx')).to_be_focused()
        expect(page.locator('#panel-dx')).to_be_visible()
        expect(page.locator('#distance-status')).to_contain_text('107 Einzelbelege')
        assert len(analysis) == before
        before = len(analysis)
        page.locator('#distance-all').click()
        expect(page.locator('#distance-scope')).to_be_hidden()
        assert len(analysis) == before, 'Changing scope requires an explicit new analysis'
        page.locator('#distance-form button[type=submit]').click()
        expect(page.locator('#distance-status')).to_contain_text('Mehr als 25.000')
        assert 'source' not in analysis[-1]
        assert analysis[-1]['minimum'] == ['200']
        # Historical DX endpoints may no longer have a current map position.
        map_nodes.clear()
        page.evaluate('loadMapNodes()')
        page.wait_for_function('mapMarkers.size === 0')
        page.locator('#tab-neighbors').click()
        page.locator('#map-neighbors-list button', has_text='Analysieren').click()
        expect(page.locator('#distance-detail .distance-node')).to_have_count(2)
        page.locator('#distance-detail .distance-node').first.click()
        expect(page.locator('#panel-map')).to_be_visible()
        expect(page.locator('#map-repeater-search-status')).to_contain_text('derzeit nicht auf der Karte verfügbar')
        assert page.evaluate('selectedMapRepeater') is None
        assert not errors, errors
        browser.close()
        print('Historical analysis: desktop/mobile, chart directions, evidence pagination, escaping, filters and errors passed')


if __name__ == '__main__': main()
