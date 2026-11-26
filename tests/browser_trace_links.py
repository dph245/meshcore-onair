"""Offline Canvas and UI regression, with optional timings on real archive output."""
import argparse
import json
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright
from browser_meshlive import route_page


def frames(page):
    page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def stats(count=2, median=.125):
    return dict(count=count, last=.25, min=0, median=median, max=.25, first_at=1795000000,
                last_at=1795000100, quality=dict(last_known=count))


A, B, C = (prefix.ljust(64, '0') for prefix in ('aabbcc12', 'bbccee12', 'ccddff12'))
P7 = dict(spreading_factor=7, frequency_hz=869618000, bandwidth_hz=62500, coding_rate=8)
P9 = dict(P7, spreading_factor=9)


def link(a, b, first, second, profiles, sizes=(4, 4)):
    return dict(endpoints=[dict(public_key=key, name=name) for key, name in (a, b)],
                positions=[dict(latitude=lat, longitude=lon) for lat, lon in [first, second]],
                position_at=1795000100, profiles=profiles, prefix_bytes=sizes)


def fixture(sf):
    links = [link((A, 'West'), (B, 'Ost'), (52.1, 10.2), (52.11, 10.21),
                  [dict(profile=P7, forward=stats(), reverse=stats(1, .25)),
                   dict(profile=P9, forward=stats(1, 0), reverse=None)]),
             link((B, 'Ost'), (C, 'Süd'), (52.11, 10.21), (52.09, 10.25),
                  [dict(profile={}, forward=None, reverse=stats(2))], sizes=(2, 2))]
    filtered = [row for row in links if sf == 'all' or any(
        str(group['profile'].get('spreading_factor', 'unknown')) == sf for group in row['profiles'])]
    return dict(links=filtered, summary=dict(measurements=8, partial=2, visible_samples=12,
        without_visible_links=1, unmapped_samples=dict(unknown=1), undecodable=0),
        spreading_factors=[7, 9], backfill=dict(done=True, scanned=8))


def run_regression(browser):
    page = browser.new_page(viewport=dict(width=390, height=900))
    page.clock.install()
    errors, requests, queries, sample_queries = [], [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    route_page(page, requests)

    def route(request):
        query = parse_qs(urlparse(request.request.url).query)
        if 'a' in query:
            sample_queries.append(query)
            request.fulfill(json=dict(items=[dict(measurement_id=17, hop=2, source=A, target=B, snr=0,
                time=1795000000, profile=P7, quality='last_known', observations=[33])], total=1, next=None))
        else:
            queries.append(query)
            request.fulfill(json=fixture(query['sf'][0]))

    def details(request):
        request.fulfill(json=dict(prefix_bytes=4, complete=True, hops=[dict(hash='aabbcc12', snr=2),
            dict(hash='bbccee12', snr=0)], observations=[dict(packet_id=33, observer_name='Testempfänger',
                received=1795000010, source_at=1795000000, observer_rssi=-92, observer_snr=3,
                radio=dict(match='last_known', profile=P7))]))

    page.route('**/api/trace-links?*', route)
    page.route('**/api/trace-measurements/17', details)
    page.goto('http://trace-links.test/')
    assert not queries
    page.locator('#tab-trace').click()
    expect(page.locator('#trace-links-status')).to_contain_text('2 Linkstrecken')
    expect(page.locator('#trace-map canvas')).to_have_count(1)
    page.evaluate('traceMap.setView([52.105,10.22], 12, {animate:false})')
    expect(page.locator('.trace-link-tooltip')).to_have_count(2)
    expect(page.locator('.trace-link-tooltip').first).to_contain_text('+0,125 dB')
    expect(page.locator('#trace-links-sf option[value="9"]')).to_have_count(1)
    assert not sample_queries
    page.evaluate('window.savedTraceLines = Object.values(traceMap._layers).filter(layer => layer instanceof L.Polyline)')
    for mode in ('light', 'dark'):
        page.evaluate('(mode) => document.documentElement.dataset.theme=mode', mode)
        color = page.locator('.trace-link-tooltip').first.evaluate('(el) => getComputedStyle(el).color')
        assert color == ('rgb(38, 52, 66)' if mode == 'light' else 'rgb(203, 211, 221)'), color
    page.locator('#trace-links-stat').select_option('last')
    expect(page.locator('.trace-link-tooltip').first).to_contain_text('+0,25 dB')
    assert len(queries) == 1
    page.locator('#trace-links-sf').select_option('9')
    expect(page.locator('#trace-links-status')).to_contain_text('1 Linkstrecken')
    assert page.evaluate('traceMap.hasLayer(savedTraceLines[0]) && !traceMap.hasLayer(savedTraceLines[1])')
    page.locator('#trace-links-pair').select_option(f'{A}/{B}')
    expect(page.locator('#trace-links-detail')).to_contain_text('Keine Messung')
    expect(page.locator('#trace-links-detail')).to_contain_text('SF7')
    expect(page.locator('#trace-links-detail')).to_contain_text('SF9')
    assert not sample_queries
    page.get_by_role('button', name='Einzelmessungen laden').click()
    expect(page.locator('#trace-links-detail')).to_contain_text('TRACE #17')
    page.locator('#trace-links-detail summary').click()
    expect(page.locator('#trace-links-detail')).to_contain_text('Observer-RSSI -92 dBm')
    assert len(sample_queries) == 1
    page.locator('#trace-links-period').select_option('custom')
    page.locator('#trace-links-start').fill('2026-11-10T18:00')
    page.locator('#trace-links-end').fill('2026-11-18T18:00')
    page.locator('#trace-links-form button').click()
    page.wait_for_function('document.querySelector("#trace-links-status").textContent.includes("1 Linkstrecken")')
    page.wait_for_timeout(50)
    original = queries[-1]
    assert float(original['end'][0]) - float(original['start'][0]) == 8 * 86400
    page.clock.fast_forward(11000)
    before = len(queries)
    page.evaluate("""() => window.__sockets.at(-1).onmessage({data:JSON.stringify({
      type:'snapshot', seq:0, groups:[], status:{trace_revision:1, received:0}
    })})""")
    page.wait_for_timeout(100)
    assert len(queries) == before + 1 and queries[-1] == original
    page.locator('#tab-live').click()
    before = len(queries)
    page.evaluate("""() => window.__sockets.at(-1).onmessage({data:JSON.stringify({
      type:'delta', seq:1, receptions:[], status:{trace_revision:2, received:0}
    })})""")
    page.clock.fast_forward(12000)
    page.wait_for_timeout(100)
    assert len(queries) == before
    assert page.locator('#trace-map canvas').count() == 0
    page.locator('#tab-trace').click()
    expect(page.locator('#trace-links-start')).to_have_value('2026-11-10T18:00')
    expect(page.locator('#trace-links-status')).to_contain_text('1 Linkstrecken')
    assert page.evaluate('traceMap.hasLayer(savedTraceLines[0])')
    assert not errors, errors
    page.close()


def benchmark(browser, folder):
    data = (folder / 'trace-links-0.json').read_text()
    payload = json.loads(data)
    page = browser.new_page(viewport=dict(width=1280, height=900))
    route_page(page, [])
    page.route('**/api/trace-links?*', lambda route: route.fulfill(body=data, content_type='application/json'))
    page.goto('http://trace-benchmark.test/')
    cdp = page.context.new_cdp_session(page)
    cdp.send('Performance.enable')
    browser_cdp = browser.new_browser_cdp_session()

    def metrics():
        return {m['name']: m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}

    def idle():
        cdp.send('HeapProfiler.collectGarbage')
        before = metrics()
        start = perf_counter()
        page.wait_for_timeout(2500)
        elapsed = perf_counter() - start
        after = metrics()
        pss = []
        for process in browser_cdp.send('SystemInfo.getProcessInfo')['processInfo']:
            if process['type'] != 'renderer':
                continue
            try:
                memory = Path(f"/proc/{process['id']}/smaps_rollup").read_text().splitlines()
                pss.append(next(int(line.split()[1]) for line in memory if line.startswith('Pss:')))
            except (OSError, StopIteration):
                continue
        return dict(main_thread_cpu_percent=round(100 * (after['TaskDuration'] - before['TaskDuration']) / elapsed, 3),
                    js_heap_bytes=int(after['JSHeapUsedSize']), dom_nodes=int(after['Nodes']),
                    renderer_pss_kib=sum(pss) if pss else None, renderer_count=len(pss))

    inactive_before = idle()
    page.evaluate('''() => {
      const fetchData = window.fetch;
      window.fetch = async (...args) => {
        const response = await fetchData(...args);
        if (String(args[0]).startsWith('/api/trace-links?')) {
          const decode = response.json.bind(response);
          response.json = async () => {
            const data = await decode();
            window.traceRenderStart = performance.now();
            new MutationObserver((entries, observer) => {
              if (!document.querySelector('#trace-map canvas')) return;
              observer.disconnect();
              requestAnimationFrame(() => requestAnimationFrame(() => {
                window.traceRenderMs = performance.now() - window.traceRenderStart;
              }));
            }).observe(document.querySelector('#trace-map'), {childList:true, subtree:true});
            return data;
          };
        }
        return response;
      };
    }''')
    begin = perf_counter()
    page.locator('#tab-trace').click()
    expect(page.locator('#trace-links-status')).to_contain_text(f"{len(payload['links'])} Linkstrecken")
    page.wait_for_function('window.traceRenderMs !== undefined')
    elapsed = (perf_counter() - begin) * 1000
    render = page.evaluate('traceRenderMs')
    active = idle()
    page.locator('#tab-live').click()
    frames(page)
    inactive_after = idle()
    browser_cdp.detach()
    page.close()
    return dict(links=len(payload['links']), decoded_data_to_paint_ms=round(render, 2),
                click_to_confirmed_render_ms=round(elapsed, 2), active=active,
                inactive_before=inactive_before, inactive_after=inactive_after)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', type=Path)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        run_regression(browser)
        print('Historische TRACE-Karte: Canvas, Layer, Auswahl, Filter, beide Themes und Lazy Loading bestanden')
        if args.benchmark:
            print(json.dumps(benchmark(browser, args.benchmark), indent=2))
        browser.close()
