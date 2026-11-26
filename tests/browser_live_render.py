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
        page = browser.new_page(viewport=dict(width=1280, height=900), color_scheme='dark')
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
        # Versioned snapshots and deltas use the same rendering and raw ring.
        def frame(kind, seq, status=None, **data):
            page.evaluate('data => __sockets.at(-1).onmessage({data: JSON.stringify(data)})',
                          dict(type=kind, seq=seq, status=dict(connected=True, max_receptions=2) | (status or {}), **data))

        click('#tab-live')
        first = packet(800)
        frame('snapshot', 10, groups=[dict(id='HASH800', first_seen=first['received_at'],
                                         latest=first, count=1, receptions=[first])], raw_packets=['one'])
        check(page, "__sockets.at(-1).url.endsWith('/ws?stream=delta')")
        click('#packets button.expand')
        click('#pause')
        late = dict(packet(801, observer=3, hash_value='HASH800'), time='01:00:00')
        frame('delta', 11, receptions=[late, packet(802, hash_value='HASH800')], raw_packets=['two', 'three'])
        check(page, "displayedGroups[0].count === 1 && displayedGroups[0].receptions.length === 1")
        click('#pause')
        check(page, "groups.get('HASH800').count === 3 && rawPackets.join(',') === 'one,two,three'")
        check(page, "groups.get('HASH800').receptions.map(p => p.number).join() === '801,802'")
        assert page.locator('#packets .reception').count() == 2
        assert 'Test 802' in page.locator('#packets').inner_text()
        page.locator('#live-observer').select_option(KEYS[3])
        assert 'Test 801' in page.locator('#packets').inner_text()
        click('#live-filter-reset')
        revived = dict(packet(804, hash_value='HASH800'), received_at='2026-10-10T12:01:00+00:00')
        frame('delta', 12, receptions=[packet(803), revived], evictions={'0': 'HASH800', '1': 'HASH803'})
        check(page, "groups.size === 1 && groups.get('HASH800').count === 1")
        assert page.evaluate("groups.get('HASH800').first_seen") == revived['received_at']
        # Queue-overflow snapshots can legitimately jump over sequence numbers.
        frame('snapshot', 20, groups=[], raw_packets=['overflow'])
        frame('delta', 21, receptions=[packet(805)], raw_packets=['after overflow'])
        check(page, "groups.has('HASH805') && rawPackets.join(',') === 'overflow,after overflow'")
        # A gap in ordinary updates must neither apply nor leak to any consumer.
        frame('delta', 23, receptions=[packet(807)], raw_packets=['gap'])
        check(page, "__sockets.at(-1).readyState === 3 && !groups.has('HASH807') && !rawPackets.includes('gap')")
        frame('delta', 22, receptions=[packet(806)])
        check(page, "!groups.has('HASH806')")
        page.wait_for_function('__sockets.length === 2')
        frame('snapshot', 1, groups=[], raw_packets=['restart'])
        frame('delta', 2, receptions=[packet(808)], raw_packets=['resume'])
        check(page, "groups.size === 1 && groups.has('HASH808') && rawPackets.join(',') === 'restart,resume'")
        frame('delta', 2, receptions=[packet(808)], raw_packets=['resume'])
        check(page, "__sockets.at(-1).readyState === 3 && groups.get('HASH808').count === 1 && rawPackets.length === 2")
        page.wait_for_function('__sockets.length === 3')
        assert 'SF8' not in page.locator('header').inner_text()
        stamp = page.evaluate('Date.now() / 1000')
        reading = page.evaluate('({origin_id, origin}) => ({origin_id, origin, noise_floor:-115, received_at:new Date().toISOString()})',
                                dict(origin_id='AB' * 32, origin='Gleicher Name'))
        east = dict(frequency_hz=869618000, bandwidth_hz=62500, spreading_factor=8, coding_rate=8)
        west = dict(spreading_factor=11)
        radios = [
            dict(origin_id='ab' * 32, origin='Gleicher Name',
                 profile=dict(east, firmware='MeshCore', firmware_version='1.14'),
                 field_times=dict.fromkeys(east, stamp), last_confirmed_at=stamp),
            dict(origin_id='cd' * 32, origin='Gleicher Name', profile=west,
                 field_times=dict.fromkeys(west, stamp - 90000), last_confirmed_at=stamp - 90000)
        ]
        header = page.locator('#noise-floor')
        latest_noise = [reading, dict(reading, origin_id='legacy', origin='Alt')]
        activity = {
            'ab' * 32: dict(origin='Gleicher Name', last_contact=int(stamp)),
            'legacy': dict(origin='Alt', last_contact=int(stamp)),
            'cd' * 32: dict(origin='Gleicher Name', last_contact=int(stamp) - 1800),
        }
        frame('snapshot', 1, groups=[], status=dict(noise_observers=latest_noise,
                                                    radio_observers=radios, observer_activity=activity))
        assert header.locator('.observer-status-row').count() == 3
        assert '-115 dBm' in header.locator('.observer-status-row').first.inner_text()
        assert header.locator('strong').first.inner_text() == 'SF8'
        assert '869,618 MHz · BW 62,5 kHz · SF8 · CR 4/8' in header.inner_text()
        assert 'Funkprofil unbekannt' in header.inner_text()
        assert 'SF11 · CR — · veraltet' in header.inner_text()
        assert 'Offline' in header.locator('.observer-offline').inner_text()
        assert 'MeshCore 1.14' in header.locator('.observer-status-row').first.get_attribute('title')
        page.evaluate('''() => {
          const header = document.querySelector('#noise-floor');
          window.headerWrites = [];
          window.eastRow = header.firstElementChild;
          window.westRow = header.lastElementChild;
          window.headerObserver = new MutationObserver(records => headerWrites.push(...records));
          headerObserver.observe(header, {subtree:true, childList:true, attributes:true, characterData:true});
        }''')
        activity['ab' * 32]['last_contact'] += 1
        frame('delta', 2, receptions=[packet(809)], status=dict(noise_observers=latest_noise,
                                                               observer_activity={'ab' * 32: activity['ab' * 32]}))
        check(page, "headerWrites.length === 0 && headerObserver.takeRecords().length === 0")
        radios[0]['profile']['spreading_factor'] = 7
        frame('delta', 3, receptions=[], status=dict(noise_observers=latest_noise, radio_observers=radios))
        assert header.locator('strong').first.inner_text() == 'SF7'
        check(page, """westRow === document.querySelector('#noise-floor').lastElementChild &&
                       headerWrites.length > 0 && headerWrites.every(({target}) => eastRow.contains(target))""")

        def observer_lines():
            return header.locator('.observer-status-row').evaluate_all(
                'rows => new Set(rows.map(row => row.getBoundingClientRect().top)).size')

        assert observer_lines() == 1
        page.set_viewport_size(dict(width=820, height=900))
        assert header.evaluate('''el => {
          const style = getComputedStyle(el.parentElement);
          return el.clientWidth === el.parentElement.clientWidth -
            parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        }''')
        assert observer_lines() == 1
        page.set_viewport_size(dict(width=390, height=844))
        assert observer_lines() > 1
        page.set_viewport_size(dict(width=320, height=600))
        long_name = 'Observer mit sehr langem Namen ' * 6
        latest_noise[0] = dict(reading, origin=long_name)
        activity['ab' * 32]['origin'] = long_name
        frame('delta', 4, receptions=[], status=dict(noise_observers=latest_noise,
                                                    observer_activity={'ab' * 32: activity['ab' * 32]}))
        first_row = header.locator('.observer-status-row').first
        assert first_row.locator('.observer-name').evaluate('el => el.scrollWidth > el.clientWidth')
        assert first_row.locator('.observer-reading > :last-child').inner_text() == '· -115 dBm'
        tooltip = first_row.get_attribute('title')
        assert long_name.strip() in tooltip and 'SF7 · CR 4/8' in tooltip
        assert header.locator('.observer-status-row').evaluate_all('''rows => rows.every(row =>
          row.getBoundingClientRect().height === 2 * parseFloat(getComputedStyle(row).lineHeight))''')
        dark_color = first_row.locator('.observer-radio').evaluate('el => getComputedStyle(el).color')
        click('#theme-toggle')
        check(page, "document.documentElement.dataset.theme === 'light'")
        assert first_row.locator('.observer-radio').evaluate('el => getComputedStyle(el).color') != dark_color
        check(page, 'document.documentElement.scrollWidth === innerWidth')
        activity.pop('cd' * 32)
        frame('snapshot', 5, groups=[], status=dict(noise_observers=latest_noise, radio_observers=[],
                                                    observer_activity=activity))
        assert 'SF7' not in header.inner_text()
        assert header.locator('.observer-status-row').count() == 2
        # Drive the existing header refresh with a fixed clock at both boundaries.
        clock = page.evaluate('''() => {
          window.observerTestNow = Math.floor(Date.now() / 1000) * 1000;
          Date.now = () => window.observerTestNow;
          return observerTestNow / 1000;
        }''')
        last_contact = clock - 15 * 60 + 1
        saved_radio = dict(radios[0], field_times=dict.fromkeys(east, clock - 3600),
                           last_confirmed_at=clock - 3600)
        frame('snapshot', 6, groups=[], status=dict(radio_observers=[saved_radio],
              observer_activity={'ab' * 32: dict(origin='Gleicher Name', last_contact=last_contact)}))
        row = header.locator('.observer-status-row')
        assert row.count() == 1 and not header.locator('.observer-offline').count()
        page.evaluate("window.originalObserver = document.querySelector('.observer-status-row')")
        page.evaluate('observerTestNow += 1000')
        header.locator('.observer-offline').wait_for()
        check(page, "originalObserver === document.querySelector('.observer-status-row')")
        assert 'Offline' in row.inner_text() and 'veraltet' not in row.inner_text()
        page.evaluate('seconds => { observerTestNow = seconds * 1000; connection(); }',
                      last_contact + 24 * 60 * 60)
        assert row.count() == 1 and 'Offline' in row.inner_text()
        page.evaluate('observerTestNow += 1000')
        row.wait_for(state='detached')
        assert header.inner_text() == 'Noise Floor: —'
        frame('delta', 7, receptions=[], status=dict(observer_activity={
            'ab' * 32: dict(origin='Gleicher Name', last_contact=last_contact + 86401)}))
        assert row.count() == 1 and 'Offline' not in row.inner_text()
        assert 'SF7 · CR 4/8 · veraltet' in row.inner_text()
        assert not errors, errors
        browser.close()
    print('Live rendering: packet rows, snapshots, deltas and responsive Observer header in both themes passed')


if __name__ == '__main__':
    main()
