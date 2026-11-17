"""Offline browser plus real local API logic on synthetic SQLite fixtures."""
from pathlib import Path
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright, expect
from browser_meshlive import route_page, emit, packet
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from onair_archive import Archive


def main():
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as pw:
        archive = Archive(Path(folder) / 'test.db')
        archive.close()
        import time
        now = time.time()
        with archive.connect() as db, db:
            db.executemany('INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?)',
                ((f'777300{i:058x}', '<Unsafe name>', 1, now, now, 2, 52.164, 10.54, 1) for i in range(105)))
            db.execute('INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?)',
                ('ab'*32, 'Reference', 1, now, now, 2, 52.164, 10.54, 1))
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                     args=['--no-sandbox', '--disable-dev-shm-usage'])
        for width, height in ((1440,900),(390,844),(320,568),(844,390)):
            page = browser.new_page(viewport=dict(width=width, height=height))
            errors, requests, queries = [], [], []
            page.set_default_timeout(10000)
            page.on('pageerror', lambda e: errors.append(str(e)))
            route_page(page, requests)
            def api(route):
                q = parse_qs(urlparse(route.request.url).query, keep_blank_values=True)
                queries.append(q)
                kwargs = {k: int(v[0]) if k in ('days','radius','offset') else v[0] for k,v in q.items()}
                try:
                    route.fulfill(json=archive.prefix_explorer.query(**kwargs))
                except ValueError as e:
                    route.fulfill(status=422,json=dict(detail=str(e)))
            page.route('**/api/prefix-explorer?*', api)
            page.goto('http://onair.test/')
            page.wait_for_function('window.__sockets.length > 0')
            assert not queries
            page.locator('#tab-prefix-explorer').click()
            expect(page.locator('#prefix-heatmap button')).to_have_count(256)
            page.screenshot(path=f'/tmp/prefix-explorer-{width}-overview.png',full_page=True)
            page.locator('#prefix-heatmap button[aria-label="77: 105 Repeater"]').click()
            expect(page.locator('#prefix-heading')).to_contain_text('2-Byte')
            page.locator('#prefix-heatmap button[aria-label="7773: 105 Repeater"]').click()
            expect(page.locator('#prefix-heading')).to_contain_text('3-Byte')
            page.locator('#prefix-heatmap button[aria-label="777300: 105 Repeater"]').click()
            expect(page.locator('#prefix-results tbody tr')).to_have_count(100)
            expect(page.locator('#prefix-levels')).to_contain_text('777300: 105 Repeater · Kollision')
            expect(page.locator('#prefix-results')).to_contain_text('<Unsafe name>')
            assert page.locator('#prefix-results unsafe').count() == 0
            expect(page.locator('#prefix-results')).to_contain_text('Verborgen')
            page.locator('#prefix-more').click()
            expect(page.locator('#prefix-results tbody tr')).to_have_count(105)
            page.locator('#prefix-radius').select_option('25')
            expect(page.locator('#prefix-results tbody tr')).to_have_count(0)
            page.locator('#prefix-radius').select_option('0')
            page.locator('#prefix-days').select_option('7')
            expect(page.locator('#prefix-results tbody tr')).to_have_count(100)
            page.locator('#prefix-sort').select_option('count')
            expect(page.locator('#prefix-heatmap button').first).to_have_attribute('aria-label', '777300: 105 Repeater')
            page.locator('#prefix-search').fill('AB')
            page.locator('#prefix-form button[type=submit]').click()
            expect(page.locator('#prefix-results tbody tr')).to_have_count(1)
            page.locator('#prefix-reference').select_option('ab'*32)
            expect(page.locator('#prefix-results')).to_contain_text('0.0 km')
            page.locator('#prefix-sort').select_option('distance')
            expect(page.locator('#prefix-results')).to_contain_text('0.0 km')
            for theme in ('dark','light'):
                page.evaluate('(theme) => document.documentElement.dataset.theme = theme',theme)
                page.screenshot(path=f'/tmp/prefix-explorer-{width}-{theme}.png',full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            assert not errors, errors
            before = len(queries)
            page.locator('#tab-live').click()
            emit(page,[packet(1)])
            expect(page.locator('#packets')).to_contain_text('Test 1')
            assert len(queries) == before
            page.close()
        browser.close()
        print('Prefix Explorer: desktop/mobile/landscape, real queries, drilldowns, search, periods, paging, privacy, themes, Live passed')


if __name__ == '__main__':
    main()
