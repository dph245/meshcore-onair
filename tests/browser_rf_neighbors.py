"""Offline Chromium RF tab checks: mocked HTTP/WebSocket, no services or DB."""
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright, expect
from browser_meshlive import route_page, emit, packet


EAST, WEST, NODE = '747400' + 'a'*58, '777300' + 'b'*58, 'ab'*32


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                     args=['--no-sandbox', '--disable-dev-shm-usage'])
        for width, height in [(1440, 900), (390, 844), (844, 390)]:
            page = browser.new_page(viewport=dict(width=width, height=height))
            errors, all_requests, rf_requests = [], [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            route_page(page, all_requests)

            def rf_api(route):
                parsed = urlparse(route.request.url)
                query = parse_qs(parsed.query)
                rf_requests.append(parsed.path + '?' + parsed.query)
                if parsed.path.endswith('/observers'):
                    data = dict(items=[dict(observer_key=EAST, name='WF-Ost', reports=21),
                                       dict(observer_key=WEST, name='WF-Rodeland', reports=1)], more=False)
                elif parsed.path.endswith('/reports'):
                    data = dict(items=[dict(message_id=1 if 'before' in query else 21,
                                            reported_at=1000, truncated=True)],
                                next_before=None if 'before' in query else 21)
                else:
                    key = query['observer'][0]
                    data = dict(report=dict(message_id=int(parsed.path.rsplit('/', 1)[1]),
                        observer_key=key, name='WF-Ost' if key == EAST else 'WF-Rodeland',
                        reported_at=1000, received_at='2026-11-05T12:00:00Z',
                        total_neighbors=9, queried_neighbors=7, truncated=True,
                        self_scopes='* de de-ni de-ni-wf', self_default_scope='de-ni-wf', retain=1),
                        entries=[dict(pubkey=NODE, name='<Test-Node>', snr=-2.25,
                                      scopes='de de-ni de-ni-wf '*5, status='timeout',
                                      heard_at=None, heard_secs_ago=None)], entries_more=False)
                route.fulfill(json=data)

            page.route('**/api/rf-neighbors/**', rf_api)
            page.goto('http://onair.test/')
            page.wait_for_function('window.__sockets.length > 0')
            assert not rf_requests
            emit(page, [packet(1)])
            page.locator('#tab-rf-neighbors').click()
            expect(page.locator('#rf-neighbor-results h3')).to_have_text('WF-Ost')
            expect(page.locator('#rf-neighbor-results')).to_contain_text(NODE)
            expect(page.locator('#rf-neighbor-results')).to_contain_text('Unbekannt')
            expect(page.locator('#rf-neighbor-results')).to_contain_text('<Test-Node>')
            assert len(rf_requests) == 3
            page.locator('#rf-neighbor-older').click()
            expect(page.locator('#rf-neighbor-history option')).to_have_count(2)
            page.locator('#rf-neighbor-history').select_option('1')
            expect(page.locator('#rf-neighbor-status')).to_contain_text('Report #1')
            page.locator('#rf-neighbor-observer').select_option(WEST)
            expect(page.locator('#rf-neighbor-results h3')).to_have_text('WF-Rodeland')
            for theme in ('light', 'dark'):
                page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                page.screenshot(path=f'/tmp/onair-rf-neighbors-{width}-{theme}.png', full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            assert page.locator('#rf-neighbor-results .noise-scroll').evaluate(
                'node => node.scrollWidth >= node.clientWidth')
            before = len(rf_requests)
            page.locator('#tab-live').click()
            emit(page, [packet(2)])
            expect(page.locator('#packets')).to_contain_text('Test 2')
            page.locator('#tab-discovery').click()
            expect(page.locator('#discovery-status')).to_contain_text('Keine auswertbaren')
            assert len(rf_requests) == before
            assert not errors, errors
            page.close()
        browser.close()
        print('RF neighbors browser: desktop/mobile/landscape, themes, history, Live/Discovery passed')


if __name__ == '__main__':
    main()
