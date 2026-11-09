"""Offline browser regression for viewport loading, History cache and chart interaction."""
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

from browser_meshlive import NOW, route_page


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        page = browser.new_page(viewport={'width': 390, 'height': 844}, has_touch=True)
        errors, requests = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        route_page(page, [])
        items = [dict(id=f'{i:04x}', name=f'Repeater {i:02d}', tokens=[f'{i:04x}'],
                      count=10, last_seen=NOW) for i in range(1, 25)]

        def api(route):
            url = urlparse(route.request.url)
            if url.path == '/api/repeaters':
                route.fulfill(json={'items': items})
            elif url.path == '/api/repeater-history':
                query = parse_qs(url.query)
                identity, hours = query['identity'][0], query['hours'][0]
                assert query.get('compact') == ['true']
                requests.append((identity, hours))
                offset = 100 if hours == '1' else 0
                route.fulfill(json=dict(points=[[NOW - 20 - offset, -91, 0], [NOW - offset, -73, 1]],
                    observers=[['abcdef-east', 'East'], ['abcdef-west', 'West']],
                    total=2, sampled=False, has_more=False, valid_for=3600))
            else:
                route.fallback()

        page.route('**/api/**', api)
        page.goto('http://repeaters.test/')
        assert not requests
        page.locator('#tab-repeaters').tap()
        rows = page.locator('.repeater-entry')
        expect(rows).to_have_count(24)
        rows.first.locator('select').scroll_into_view_if_needed()
        chart = rows.first.locator('.repeater-chart')
        expect(chart).to_be_visible()
        assert ('0018', '24') not in requests
        assert len(requests) < len(items)
        expect(chart.locator('path')).to_have_count(2)
        expect(chart.locator('circle')).to_have_count(2)
        point = chart.locator('circle').first
        point.focus()
        expect(rows.first.locator('.repeater-history > p').last).to_contain_text('East [abcdef]')
        chart.locator('circle').last.dispatch_event('pointerover')
        expect(rows.first.locator('.repeater-history > p').last).to_contain_text('West [abcdef]')
        point.tap()
        expect(rows.first.locator('.repeater-history > p').last).to_contain_text('-91 dBm')

        rows.last.scroll_into_view_if_needed()
        expect(rows.last.locator('.repeater-chart')).to_be_visible()
        assert ('0018', '24') in requests
        page.get_by_role('button', name='Repeater 01', exact=True).tap()
        expect(page.locator('.repeater-entry:visible')).to_have_count(1)
        page.evaluate("window.saved = document.querySelector('.repeater-chart')")
        page.locator('#tab-live').tap()
        page.locator('#tab-repeaters').tap()
        rows.first.locator('select').scroll_into_view_if_needed()
        page.evaluate('loadRepeaters()')
        assert requests.count(('0001', '24')) == 1
        assert page.evaluate("saved === document.querySelector('.repeater-chart')")

        hours = rows.first.locator('select')
        hours.select_option('1')
        page.wait_for_function("repeaterViews.get('0001').cache.has('1')")
        assert requests.count(('0001', '1')) == 1
        hours.select_option('24')
        hours.select_option('1')
        assert requests.count(('0001', '24')) == 1
        assert requests.count(('0001', '1')) == 1

        # When only the time window expires, reload while keeping identical SVG nodes.
        page.evaluate("""() => {
            window.saved = document.querySelector('.repeater-chart');
            repeaterViews.get('0001').cache.get('1').expires = 0;
        }""")
        page.evaluate('loadRepeaters()')
        page.wait_for_function("!repeaterViews.get('0001').loading")
        assert requests.count(('0001', '1')) == 2
        assert page.evaluate("saved === document.querySelector('.repeater-chart')")
        items[0]['count'] += 1
        page.evaluate('loadRepeaters()')
        page.wait_for_function("repeaterViews.get('0001').item.count === 11 && !repeaterViews.get('0001').loading")
        assert requests.count(('0001', '1')) == 3
        assert page.evaluate("saved === document.querySelector('.repeater-chart')")

        # Even a late response that ignores abort cannot replace a newer period.
        page.evaluate("""() => {
            const fetchReal = window.fetch;
            window.fetch = (url, options) => {
                if (!url.includes('/api/repeater-history?') || !url.includes('hours=168')) {
                    return fetchReal(url, options);
                }
                window.staleHistorySignal = options.signal;
                return new Promise(resolve => {
                    window.finishStaleHistory = () => resolve(new Response(JSON.stringify({
                        points: [[1, -1, 0]], observers: [[null, null]], total: 1, valid_for: null,
                    })));
                });
            };
        }""")
        hours.select_option('168')
        page.wait_for_function('typeof window.finishStaleHistory === "function"')
        hours.select_option('0')
        page.wait_for_function("repeaterViews.get('0001').cache.has('0')")
        assert page.evaluate("""async () => {
            const view = repeaterViews.get('0001');
            finishStaleHistory();
            await new Promise(resolve => setTimeout(resolve, 0));
            return staleHistorySignal.aborted && !view.cache.has('168') && view.displayed.items.length === 2;
        }""")
        assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
        assert not errors, errors
        browser.close()
    print('Repeater History: lazy loading, cache, expiry, refresh and mobile interaction passed')


if __name__ == '__main__':
    main()
