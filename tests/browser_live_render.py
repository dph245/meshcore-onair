"""Offline Chromium regression for incremental Live rows and scroll preservation.

Run: .venv/bin/python tests/browser_live_render.py
Uses only routed fixtures: no MQTT broker, app lifespan or archive writes.
"""
from playwright.sync_api import sync_playwright
from browser_meshlive import route_page, packet, emit, KEYS


def send(page, **data):
    page.evaluate('data => __sockets.at(-1).onmessage({data: JSON.stringify(data)})',
                  dict(type='update', **data))


def check(page, expression):
    assert page.evaluate(expression), expression


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        page = browser.new_page(viewport=dict(width=1280, height=900))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        route_page(page, [])
        page.goto('http://live.test/')
        page.wait_for_function('__sockets.length === 1')
        click = lambda selector: page.locator(selector).evaluate('(el) => el.click()')
        emit(page, [packet(i) for i in range(1, 501)], 'snapshot')
        page.evaluate('''() => {
          window.saved = [...document.querySelectorAll('#packets tr')];
          window.createdRows = 0;
          const create = document.createElement.bind(document);
          document.createElement = (...args) => {
            if (args[0] === 'tr') createdRows++;
            return create(...args);
          };
          window.tableMutations = 0;
          window.mutations = new MutationObserver(records => tableMutations += records.length);
          mutations.observe(document.querySelector('#packets'), {subtree:true, childList:true, attributes:true, characterData:true});
        }''')
        # Pure status updates must not touch the table at all.
        send(page, status=dict(connected=True, received=501, archive=dict(saved=501)))
        check(page, "createdRows === 0 && tableMutations === 0 && mutations.takeRecords().length === 0")
        assert '501 archiviert' in page.locator('#counts').inner_text()
        # Only one changed group is rebuilt and moved to the front.
        page.evaluate("document.querySelector('#panel-live').scrollTop = 600; document.querySelector('.live-table-scroll').scrollLeft = 80")
        position = page.evaluate("[document.querySelector('#panel-live').scrollTop, document.querySelector('.live-table-scroll').scrollLeft]")
        emit(page, [packet(501, hash_value='HASH1')])
        check(page, "createdRows === 1 && saved[0] === document.querySelectorAll('#packets tr')[1] && !saved[499].isConnected")
        assert page.evaluate("[document.querySelector('#panel-live').scrollTop, document.querySelector('.live-table-scroll').scrollLeft]") == position
        page.wait_for_timeout(50)  # Include deferred browser scroll anchoring.
        assert page.evaluate("[document.querySelector('#panel-live').scrollTop, document.querySelector('.live-table-scroll').scrollLeft]") == position
        # Details follow their group; unrelated open details retain their DOM nodes.
        click('#packets tr.packet:nth-child(2) button')
        page.evaluate("window.detail = document.querySelector('#packets tr.detail'); window.createdRows = 0")
        emit(page, [packet(502, hash_value='HASH1')])
        check(page, "createdRows === 1 && detail === document.querySelector('#packets tr.detail')")
        click('#packets tr.packet:first-child button')
        emit(page, [packet(503, hash_value='HASH1')])
        assert page.locator('#packets tr.detail').count() == 2
        assert '#503' in page.locator('#packets tr.detail').first.inner_text()
        # Eviction removes both rows and releases the expanded-state/cache entry.
        emit(page, [packet(504)])
        send(page, removed=['HASH1'])
        check(page, "!liveRows.has('HASH1') && !expanded.has('HASH1') && liveRows.size === 500")
        assert page.locator('#packets tr.packet').count() == 500
        # Batched changes can move in either direction; compare against a full render.
        emit(page, [packet(505, hash_value='HASH2'), packet(10, hash_value='HASH499')])
        html = page.locator('#packets').inner_html()
        page.evaluate('render(true)')
        assert page.locator('#packets').inner_html() == html
        # Active repeater + observer filters: enter, disappear, and select latest
        # matching reception rather than the latest reception of the whole group.
        click('#live-filter-toggle')
        page.locator('#live-repeater').fill('bbcc')
        page.locator('#live-observer').select_option(KEYS[2])
        emit(page, [packet(506, ['aabb'], hash_value='HASH2')])
        check(page, "!liveRows.has('HASH2')")
        emit(page, [packet(507, observer=3, hash_value='HASH2'), packet(508, hash_value='HASH2')])
        check(page, "liveRows.has('HASH2')")
        emit(page, [packet(509, hash_value='HASH2'), packet(510, observer=3, hash_value='HASH2')])
        assert 'Test 509' in page.locator('#packets tr.packet').first.inner_text()
        html = page.locator('#packets').inner_html()
        page.evaluate('render(true)')
        assert page.locator('#packets').inner_html() == html
        click('#pause')
        html = page.locator('#packets').inner_html()
        emit(page, [packet(511)])
        send(page, removed=['HASH500'])
        assert page.locator('#packets').inner_html() == html
        click('#live-filter-reset')  # Full rebuild still uses the frozen data.
        assert 'Test 511' not in page.locator('#packets').inner_text()
        click('#pause')
        assert 'Test 511' in page.locator('#packets').inner_text()
        check(page, "!liveRows.has('HASH500')")
        # Sustained turnover keeps both the DOM and row cache bounded at 500.
        emit(page, [packet(i) for i in range(1, 501)], 'snapshot')
        page.evaluate("window.createdRows = 0")
        for i in range(501, 551):
            p = packet(i)
            send(page, groups=[dict(id=p['group_id'], count=1, first_seen=p['received_at'],
                                    latest=p, receptions=[p])], removed=[f'HASH{i-500}'])
        check(page, "createdRows === 50 && liveRows.size === 500 && body.children.length === 500")
        check(page, "[...liveRows.values()].every(rows => rows.every(row => row.isConnected))")
        # Snapshot/reconnect clears stale cache entries, including detail rows.
        emit(page, [packet(600)], 'snapshot')
        check(page, "liveRows.size === 1 && liveRows.has('HASH600') && expanded.size === 0")
        # Hidden tabs retain data without mutating the table, including snapshots.
        click('#packets button.expand')
        click('#tab-raw')
        page.evaluate('window.createdRows = 0; window.tableMutations = 0')
        emit(page, [packet(601), packet(602, hash_value='HASH600')])
        send(page, removed=['HASH601'])
        check(page, "groups.has('HASH600') && !groups.has('HASH601') && createdRows === 0 && tableMutations === 0")
        click('#tab-live')
        assert 'Test 602' in page.locator('#packets').inner_text()
        assert page.locator('#packets tr.detail').count() == 1
        html = page.locator('#packets').inner_html()
        page.evaluate('render(true)')
        assert page.locator('#packets').inner_html() == html
        click('#tab-raw')
        emit(page, [packet(700)], 'snapshot')
        click('#pause')
        emit(page, [packet(701)], 'snapshot')
        click('#tab-live')
        assert 'Test 700' in page.locator('#packets').inner_text()
        assert 'Test 701' not in page.locator('#packets').inner_text()
        check(page, "liveRows.size === 1 && !liveRows.has('HASH600')")
        click('#pause')
        assert 'Test 701' in page.locator('#packets').inner_text()
        emit(page, [], 'snapshot')
        check(page, "liveRows.size === 0 && !document.querySelector('#empty').hidden")
        # Noise charts catch up on tab entry, preserve unrelated series and pause.
        noise = page.evaluate("[0,1].map(i => ({origin_id:'observer-'+i, origin:'Observer '+i, noise_floor:-110-i, received_at:new Date().toISOString()}))")
        send(page, status=dict(connected=True, noise_history=noise))
        assert page.locator('#noise-charts .noise-observer').count() == 0
        click('#tab-noise')
        assert page.locator('#noise-charts .noise-observer').count() == 2
        page.evaluate("window.noiseWest = document.querySelectorAll('.noise-observer')[1]")
        noise = noise + [dict(noise[0], noise_floor=-109)]
        send(page, status=dict(connected=True, noise_history=noise))
        check(page, "noiseWest === document.querySelectorAll('.noise-observer')[1]")
        assert page.locator('#noise-charts .noise-point').count() == 3
        click('#pause')
        send(page, status=dict(connected=True, noise_history=[]))
        click('#tab-live')
        click('#tab-noise')
        assert page.locator('#noise-charts .noise-point').count() == 3
        click('#pause')
        assert page.locator('#noise-charts .noise-observer').count() == 0
        assert not errors, errors
        browser.close()
    print('Live rendering: stable nodes, status-only, order, details, eviction, filters, pause, snapshots and scroll passed')


if __name__ == '__main__':
    main()
