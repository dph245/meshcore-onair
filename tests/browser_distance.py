"""Offline desktop/mobile analysis UI; no MQTT, running server, or production DB."""
import copy
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect
from browser_meshlive import route_page

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
        failure = [False]
        def handle(route):
            q = parse_qs(urlparse(route.request.url).query); analysis.append(q)
            if failure[0]: route.fulfill(status=422, json={'detail':'Bitte Zeitraum verkürzen.'}); return
            if 'source' not in q: route.fulfill(json=dict(BASE, items=[LINK])); return
            offset = int(q.get('offset', ['0'])[0])
            rows = [dict(id=i+1, received=START+i, kind='ADVERT', directions=['reverse' if i == 0 else 'forward'],
                         observer='<Observer>', observer_hash='ABCD', route='FLOOD', packet_key='a'*64,
                         path=['3c4afc','3134db','dad317'] if i == 0 else ['3134db','3c4afc','dad317'])
                    for i in range(offset, min(offset+100,107))]
            route.fulfill(json=dict(BASE, link=LINK, evidence=rows, more=offset+100<107))
        page.route('**/api/repeater-neighbors/analysis?*', handle)
        page.goto('http://distance.test/')
        page.locator('#tab-neighbors').click()
        page.locator('#distance-analysis>summary').click()
        assert not analysis, 'Opening the tab/details must not scan the archive'
        page.locator('#distance-example').click()
        expect(page.locator('#distance-status')).to_contain_text('1 Fernverbindungen')
        assert analysis[-1]['start'] == [str(START)]
        assert analysis[-1]['end'] == [str(START+3*86400)]
        page.locator('#distance-links button').click()
        expect(page.locator('#distance-status')).to_contain_text('100 Einzelbelege')
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
        page.set_viewport_size({'width':390,'height':844})
        page.locator('#distance-detail').scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'No mobile page overflow'
        for theme in ['dark','light']:
            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            page.locator('#distance-detail').screenshot(path=f'/tmp/onair-distance-{theme}.png')
        page.locator('#distance-minimum').select_option('250')
        expect(page.locator('#distance-detail')).to_be_empty()
        page.locator('#distance-form button[type=submit]').click()
        expect(page.locator('#distance-status')).to_contain_text('1 Fernverbindungen')
        assert analysis[-1]['minimum'] == ['250']
        failure[0] = True
        page.locator('#distance-form button[type=submit]').click()
        expect(page.locator('#distance-status')).to_contain_text('Bitte Zeitraum verkürzen.')
        expect(page.locator('#distance-links')).to_be_empty()
        # Existing table action opens the analysis using the selected link's bounds.
        failure[0] = False
        source = copy.deepcopy(LINK)
        source.update(first_seen=START,last_seen=START+3600,distance_km=308.498)
        page.evaluate('(link)=>window.openDistanceAnalysis(link)',source)
        expect(page.locator('#distance-status')).to_contain_text('100 Einzelbelege')
        assert analysis[-1]['source'] == [A]
        assert not errors, errors
        browser.close()
        print('Historical analysis: desktop/mobile, chart directions, evidence pagination, escaping, filters and errors passed')


if __name__ == '__main__': main()
