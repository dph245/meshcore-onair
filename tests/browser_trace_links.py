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


def stats(last, minimum, median, maximum, count=2):
    return dict(count=count, last=last, min=minimum, median=median, max=maximum, last_at=1795000100)


A, B, C = (prefix.ljust(64, '0') for prefix in ('aabbcc12', 'bbccee12', 'ccddff12'))
P7 = dict(spreading_factor=7, frequency_hz=869618000, bandwidth_hz=62500, coding_rate=8)
P9 = dict(P7, spreading_factor=9)


def link(a, b, first, second, forward, reverse, sizes=(4, 4)):
    return dict(endpoints=[dict(public_key=key, name=name) for key, name in (a, b)],
                positions=[dict(latitude=lat, longitude=lon) for lat, lon in [first, second]],
                position_at=1795000100, snr=dict(forward=forward, reverse=reverse), prefix_bytes=sizes)


def fixture(sf):
    links = []
    if sf in ('all', '7', '9'):
        links.append(link((A, 'West'), (B, 'Ost'), (52.1, 10.2), (52.11, 10.21),
                          stats(-4.5, -8.25, .125, 5), stats(2, -1.5, .25, 10)))
        if sf == '9':
            links[0]['snr'] = dict(forward=stats(0, 0, 0, 0, 1), reverse=None)
    if sf in ('all', 'unknown'):
        links.append(link((B, 'Ost'), (C, 'Süd'), (52.11, 10.21), (52.09, 10.25),
                          None, stats(-.5, -3.5, -2, -.5), sizes=(2, 2)))
    return dict(links=links, spreading_factors=[7, 9], backfill=dict(done=True, scanned=8))


def sample_page(query):
    a, b, sf = (query[name][0] for name in ('a', 'b', 'sf'))
    if (a, b) == (A, B):
        series = dict(forward=[[1795000000, 0], [1795000100, -4.5]],
                      reverse=[[1795000010, .25], [1795000090, 2]])
        if sf == '9':
            series = dict(forward=[[1795000000, 0]], reverse=[])
        source, target = a, b
    else:
        series = dict(forward=[], reverse=[[1795000000, -2], [1795000100, -.5]])
        source, target = b, a
    return dict(items=[dict(measurement_id=17, hop=2, source=source, target=target, snr=0,
                           time=1795000000, profile=P9 if sf == '9' else P7,
                           quality='last_known', observations=[33])], history=series, total=1, next=None)


def line_point(page):
    return page.evaluate('''() => {
      const point = traceMap.latLngToContainerPoint([52.103, 10.203]);
      const box = traceMap.getContainer().getBoundingClientRect();
      return [box.left + point.x, box.top + point.y];
    }''')


PAINTED_LINKS = '''() => {
  const map = traceMap?.getContainer(), canvas = map?.querySelector('canvas');
  if (!canvas || !map.clientWidth || !map.clientHeight ||
      !traceMap.getSize().equals([map.clientWidth, map.clientHeight])) return false;
  const rect = canvas.getBoundingClientRect(), area = map.getBoundingClientRect();
  const scale = canvas.width / rect.width;
  const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
  const lines = Object.values(traceMap._layers).filter(layer => layer instanceof L.Polyline);
  return lines.length === 2 && lines.every(line => {
    const [a, b] = line.getLatLngs().map(point => traceMap.latLngToContainerPoint(point));
    const rgb = line.options.color.match(/[a-f0-9]{2}/gi).map(value => parseInt(value, 16));
    for (let t = .25; t <= .75; t += .025) {
      const point = a.add(b.subtract(a).multiplyBy(t));
      if (point.x < 0 || point.x >= map.clientWidth || point.y < 0 || point.y >= map.clientHeight) continue;
      const x = Math.round((area.left + map.clientLeft + point.x - rect.left) * scale);
      const y = Math.round((area.top + map.clientTop + point.y - rect.top) * scale);
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
        const offset = ((y + dy) * canvas.width + x + dx) * 4;
        if (pixels[offset + 3] > 100 && rgb.every((channel, i) => Math.abs(pixels[offset + i] - channel) < 5)) return true;
      }
    }
    return false;
  });
}'''


def run_initial_paint(browser):
    for order in ('immediate', 'visible-first', 'hidden-response', 'data-first'):
        page = browser.new_page(viewport=dict(width=1280, height=900))
        errors, requests = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        route_page(page, [])
        payload = fixture('all')

        def overview(route):
            requests.append(route)
            if order == 'immediate':
                route.fulfill(json=payload)

        page.route('**/api/trace-links?*', overview)
        page.goto('http://trace-first-paint.test/')
        page.evaluate('''() => {
          window.overviewDecoded = 0;
          const decode = Response.prototype.json;
          Response.prototype.json = async function() {
            const value = await decode.call(this);
            if (this.url.includes('/api/trace-links?')) overviewDecoded++;
            return value;
          };
          window.traceFits = 0;
          const fit = L.Map.prototype.fitBounds;
          L.Map.prototype.fitBounds = function(...args) {
            if (this.getContainer().id === 'trace-map') traceFits++;
            return fit.apply(this, args);
          };
        }''')
        if order == 'data-first':
            collapsed = page.add_style_tag(content='#trace-map {width:0!important;height:0!important;border:0!important}')
        with page.expect_request('**/api/trace-links?*'):
            page.locator('#tab-trace').press('Enter')
        if order != 'immediate':
            frames(page)
            expect(page.locator('#trace-map canvas')).to_have_count(0)
            if order == 'hidden-response':
                page.locator('#tab-live').press('Enter')
            requests[0].fulfill(json=payload)
            page.wait_for_function('overviewDecoded === 1')
            frames(page)
            if order == 'hidden-response':
                expect(page.locator('#trace-map canvas')).to_have_count(0)
                page.locator('#tab-trace').press('Enter')
            elif order == 'data-first':
                assert page.evaluate('traceFits === 0')
                expect(page.locator('#trace-map canvas')).to_have_count(0)
                collapsed.evaluate('style => style.remove()')
        page.wait_for_function(PAINTED_LINKS, timeout=3000)
        page.evaluate('''() => {
          window.firstTraceView = {
            map: traceMap, center: traceMap.getCenter(), zoom: traceMap.getZoom(),
            paths: Object.values(traceMap._layers).filter(layer => layer instanceof L.Path)
          };
        }''')

        def retained():
            page.wait_for_function(PAINTED_LINKS, timeout=3000)
            assert page.evaluate('''() => {
              const {map, center, zoom, paths} = firstTraceView;
              return traceMap === map && traceMap.getZoom() === zoom && traceFits === 1 &&
                traceMap.latLngToContainerPoint(center).distanceTo(traceMap.getSize().divideBy(2)) <= 1.5 &&
                paths.every(path => traceMap.hasLayer(path));
            }''')
            assert len(requests) == 1 and not errors, (order, len(requests), errors)

        for _ in range(2):
            page.locator('#tab-live').press('Enter')
            expect(page.locator('#trace-map canvas')).to_have_count(0)
            page.locator('#tab-trace').press('Enter')
            retained()
        if order == 'immediate':
            width = page.locator('#trace-map').evaluate('element => element.clientWidth')
            page.locator('#trace-links-panel-width').press('End')
            page.wait_for_function('width => traceMap.getContainer().clientWidth < width', arg=width)
            retained()
            for width, height in ((844, 390), (390, 844), (1280, 900)):
                page.set_viewport_size(dict(width=width, height=height))
                retained()
        page.close()
    print('TRACE-Erstzeichnung: sichtbare Canvas-Linien, verzögerte Daten, Tabwechsel und Größenänderungen bestanden')


def assert_tooltip_layout(tooltip, min_width):
    layout = tooltip.evaluate(r'''el => {
      const {width, height, left, right, top, bottom} = el.getBoundingClientRect();
      const container = el.closest('#trace-map');
      const map = container.getBoundingClientRect();
      const range = document.createRange();
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const splitWords = [];
      for (let node; (node = walker.nextNode());) {
        for (const match of node.textContent.matchAll(/\S+/gu)) {
          range.setStart(node, match.index);
          range.setEnd(node, match.index + match[0].length);
          if (range.getClientRects().length !== 1) splitWords.push(match[0]);
        }
      }
      const readings = [...el.querySelectorAll('.trace-link-reading')];
      const coversControls = [...container.querySelectorAll('.leaflet-control-zoom, .leaflet-control-attribution')]
        .some(control => {
          const rect = control.getBoundingClientRect();
          return left < rect.right && right > rect.left && top < rect.bottom && bottom > rect.top;
        });
      return {width, height, maxWidth: parseFloat(getComputedStyle(el).maxWidth),
        mapWidth: map.width, splitWords, readings: readings.length,
        readingsOnOneLine: readings.every(reading => reading.getClientRects().length === 1),
        contained: left >= map.left && right <= map.right && top >= map.top && bottom <= map.bottom,
        overflows: el.scrollWidth > el.clientWidth, coversControls};
    }''')
    assert min_width <= layout['width'] <= layout['maxWidth'] <= min(400, layout['mapWidth'] - 16), layout
    assert layout['contained'] and not layout['overflows'] and not layout['splitWords'], layout
    assert not layout['coversControls'], layout
    assert layout['readings'] and layout['readingsOnOneLine'], layout
    return layout


def run_tooltip_layout(browser):
    page = browser.new_page(viewport=dict(width=1280, height=900))
    payload = fixture('all')
    west = 'Westlicher Repeater auf dem Höhenzug hinter der ehemaligen Relaisstation'
    east = 'Östlicher Repeater am Aussichtspunkt oberhalb der Gemeinde mit Blick zum Tal'
    link = payload['links'][0]
    link['endpoints'][0]['name'], link['endpoints'][1]['name'] = west, east
    link['snr'] = dict(forward=stats(-17.875, -17.875, -17.875, -17.875),
                       reverse=stats(-11.25, -11.25, -11.25, -11.25))
    route_page(page, [])
    page.route('**/api/trace-links?*', lambda route: route.fulfill(json=payload))
    page.goto('http://trace-tooltip.test/')
    page.locator('#tab-trace').click()
    expect(page.locator('#trace-links-status')).to_contain_text('2 Linkstrecken')
    page.locator('#trace-links-panel-width').press('End')

    tooltip = page.locator('.trace-link-hover')
    for width, mode, right in ((1280, 'light', True), (360, 'dark', False)):
        page.set_viewport_size(dict(width=width, height=940))
        page.evaluate('mode => document.documentElement.dataset.theme = mode', mode)
        page.locator('#trace-map').scroll_into_view_if_needed()
        page.mouse.move(0, 0)
        page.evaluate('''right => {
          traceMap.setView([52.105, 10.22], 12, {animate:false});
          const size = traceMap.getSize();
          const edge = right ? L.point(size.x - 18, size.y - 14) : L.point(50, 16);
          const point = traceMap.latLngToContainerPoint([52.103, 10.203]);
          traceMap.panBy(point.subtract(edge), {animate:false});
        }''', right)
        frames(page)
        page.mouse.move(*line_point(page))
        expect(tooltip).to_contain_text(f'{west} ↔ {east}')
        expect(tooltip).to_contain_text('← −11,25 dB')
        expect(tooltip).to_contain_text('→ −17,875 dB')
        layout = assert_tooltip_layout(tooltip, 280)
        assert abs(layout['width'] - layout['maxWidth']) <= 1, layout
        assert layout['height'] < 150, layout

    page.mouse.move(0, 0)
    page.locator('#trace-links-options summary').click()
    page.locator('#trace-links-label-mode').select_option('full')
    page.locator('#trace-links-options summary').click()
    permanent = page.locator('.trace-link-tooltip:not(.trace-link-hover)').filter(has_text=west)
    expect(permanent).to_contain_text('← −11,25 dB')
    assert_tooltip_layout(permanent, 280)
    expect(tooltip).to_have_count(0)
    page.close()


def run_regression(browser):
    page = browser.new_page(viewport=dict(width=1280, height=900))
    page.clock.install()
    errors, requests, queries, sample_queries = [], [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    route_page(page, requests)

    def route(request):
        query = parse_qs(urlparse(request.request.url).query)
        if 'a' in query:
            sample_queries.append(query)
            request.fulfill(json=sample_page(query))
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
    expect(page.locator('#trace-links-start')).to_be_hidden()
    expect(page.locator('#trace-links-end')).to_be_hidden()
    expect(page.locator('#trace-links-label-mode')).to_have_value('none')
    expect(page.locator('#trace-links-period')).to_have_value('all')
    expect(page.locator('#trace-links-legend')).to_contain_text('Schwächerer Richtungswert')
    expect(page.get_by_text('SF7-Reserveprognose')).to_have_count(0)
    assert queries[0]['compact'] == ['true'] and queries[0]['start'] == ['0']
    page.evaluate('traceMap.setView([52.105,10.22], 12, {animate:false})')
    frames(page)
    expect(page.locator('.trace-link-tooltip')).to_have_count(0)
    expect(page.locator('#trace-links-sf option[value="9"]')).to_have_count(1)
    assert not sample_queries
    page.evaluate('''() => {
      savedTraceMap = traceMap;
      savedTraceCanvas = document.querySelector('#trace-map canvas');
      savedTraceLines = Object.values(traceMap._layers).filter(layer => layer instanceof L.Polyline);
      savedTraceDots = Object.values(traceMap._layers).filter(layer => layer instanceof L.CircleMarker);
      savedCenter = traceMap.getCenter();
    }''')
    assert page.evaluate('savedTraceLines.length === 2 && savedTraceDots.length === 3 && savedTraceDots.every(dot => !dot.options.interactive)')
    assert page.evaluate("savedTraceLines[0].options.color === '#15803d' && !savedTraceLines[0].options.dashArray")
    assert page.evaluate("savedTraceLines[1].options.color === '#b45309' && savedTraceLines[1].options.dashArray === '7 5'")

    page.mouse.move(*line_point(page))
    tooltip = page.locator('.trace-link-hover')
    expect(tooltip).to_have_count(1)
    expect(tooltip).to_contain_text('West ↔ Ost')
    expect(tooltip).to_contain_text('← +0,25 dB')
    expect(tooltip).to_contain_text('+0,125 dB')
    layout = assert_tooltip_layout(tooltip, 130)
    assert layout['height'] < 75, layout
    for mode in ('light', 'dark'):
        page.evaluate('(mode) => document.documentElement.dataset.theme=mode', mode)
        color = tooltip.evaluate('(el) => getComputedStyle(el).color')
        assert color == ('rgb(38, 52, 66)' if mode == 'light' else 'rgb(203, 211, 221)'), color
    page.mouse.click(*line_point(page))
    expect(page.locator('#trace-links-pair')).to_have_value(f'{A}/{B}')
    expect(page.locator('#trace-links-detail h3')).to_have_text('West ↔ Ost')
    chart = page.locator('.trace-link-chart')
    expect(chart).to_be_visible()
    expect(chart).to_have_attribute('aria-label', 'SNR-Verlauf in dB · West → Ost und Ost → West')
    expect(page.locator('.trace-link-chart-caption')).to_have_text('○ West → Ost× Ost → West')
    assert len(sample_queries) == 1
    assert page.evaluate('savedTraceLines[0].options.weight === 7 && savedTraceLines[1].options.opacity < .9')
    page.mouse.move(0, 0)
    expect(tooltip).to_have_count(0)
    page.locator('#trace-links-pair').select_option(f'{B}/{C}')
    expect(page.locator('#trace-links-detail h3')).to_have_text('Ost ↔ Süd')
    assert page.evaluate('savedTraceLines[1].options.weight === 7 && savedTraceLines[0].options.weight === 4')
    page.locator('#trace-links-pair').select_option('')
    assert page.evaluate('savedTraceLines.every(line => line.options.weight === 4 && line.options.opacity === .9)')

    mode = page.locator('#trace-links-label-mode')
    page.locator('#trace-links-options summary').click()
    mode.select_option('snr')
    compact = page.locator('.trace-link-compact')
    expect(compact).to_have_count(2)
    expect(compact.first).to_have_text('→ +0,125 dB · ← +0,25 dB')
    expect(compact.last).to_have_text('→ — · ← −2,0 dB')
    page.evaluate('traceMap.setZoom(10, {animate:false})')
    expect(compact).to_have_count(0)
    mode.select_option('full')
    full = page.locator('.trace-link-tooltip')
    expect(full).to_have_count(2)
    expect(full.first).to_contain_text('West ↔ Ost')
    statistic = page.locator('#trace-links-stat')
    for stat, value, color in (('last', '−4,5 dB', '#c62828'), ('min', '−8,25 dB', '#c62828'),
                               ('max', '+5,0 dB', '#15803d'), ('median', '+0,125 dB', '#15803d')):
        statistic.select_option(stat)
        expect(full.first).to_contain_text(value)
        assert page.evaluate('color => savedTraceLines[0].options.color === color', color)
    assert len(queries) == 1

    mode.select_option('none')
    page.locator('#trace-links-options summary').click()
    expect(full).to_have_count(0)

    page.evaluate('''() => {
      traceMap.setZoom(12, {animate:false});
      savedCenter = traceMap.getCenter();
      resizeEvents = 0;
      traceMap.on('resize', () => resizeEvents++);
    }''')
    map_box = lambda: page.locator('#trace-map').bounding_box()
    details = page.locator('#trace-links-details')
    toggle = page.locator('#trace-links-toggle-details')
    assert details.bounding_box()['x'] >= map_box()['x'] + map_box()['width']
    width = map_box()['width']
    toggle.click()
    expect(details).to_be_hidden()
    assert map_box()['width'] > width
    frames(page)
    page.mouse.click(*line_point(page))
    expect(details).to_be_visible()
    expect(toggle).to_have_attribute('aria-expanded', 'true')
    expect(page.locator('#trace-links-pair')).to_have_value(f'{A}/{B}')
    panel_width = details.bounding_box()['width']
    page.locator('#trace-links-panel-width').press('End')
    assert details.bounding_box()['width'] > panel_width
    height = map_box()['height']
    page.set_viewport_size(dict(width=1280, height=740))
    frames(page)
    assert map_box()['height'] < height
    page.set_viewport_size(dict(width=820, height=740))
    frames(page)
    assert details.bounding_box()['y'] >= map_box()['y'] + map_box()['height']
    expect(page.locator('#trace-links-panel-width')).to_be_hidden()
    assert page.evaluate('''() => traceMap === savedTraceMap && traceMap.getZoom() === 12 &&
      traceMap.latLngToContainerPoint(savedCenter).distanceTo(traceMap.getSize().divideBy(2)) <= 1.5 &&
      document.querySelector('#trace-map canvas') === savedTraceCanvas &&
      [...savedTraceLines, ...savedTraceDots].every(layer => traceMap.hasLayer(layer)) && resizeEvents > 0''')
    before = page.evaluate('resizeEvents')
    frames(page)
    assert page.evaluate('resizeEvents') == before
    assert len(queries) == 1

    before = len(sample_queries)
    page.locator('#trace-links-sf').select_option('9')
    expect(page.locator('#trace-links-status')).to_have_text('1 Linkstrecke')
    assert page.evaluate('traceMap.hasLayer(savedTraceLines[0]) && !traceMap.hasLayer(savedTraceLines[1])')
    page.locator('#trace-links-pair').select_option(f'{A}/{B}')
    expect(page.locator('.trace-link-chart-caption')).to_contain_text('Ost → West (keine Messung)')
    expect(page.locator('.trace-link-samples summary').first).to_have_text('Einzelmessungen')
    page.locator('.trace-link-samples summary').first.click()
    expect(page.locator('#trace-links-detail')).to_contain_text('TRACE #17')
    page.get_by_text('TRACE #17', exact=False).click()
    expect(page.locator('#trace-links-detail')).to_contain_text('Observer-RSSI -92 dBm')
    assert len(sample_queries) == before + 1 and sample_queries[-1]['sf'] == ['9']
    page.locator('#trace-links-period').select_option('custom')
    expect(page.locator('#trace-links-start')).to_be_visible()
    expect(page.locator('#trace-links-end')).to_be_visible()
    page.locator('#trace-links-start').fill('2026-11-10T18:00')
    page.locator('#trace-links-end').fill('2026-11-18T18:00')
    page.locator('#trace-links-apply').click()
    expect(page.locator('#trace-links-status')).to_have_text('1 Linkstrecke')
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
    expect(page.locator('#trace-links-status')).to_have_text('1 Linkstrecke')
    assert page.evaluate('traceMap.hasLayer(savedTraceLines[0])')
    page.locator('#trace-links-options summary').click()
    mode.select_option('full')
    page.locator('#trace-links-options summary').click()
    toggle.click()
    page.reload()
    page.locator('#tab-trace').click()
    expect(mode).to_have_value('full')
    expect(toggle).to_have_attribute('aria-expanded', 'false')
    expect(details).to_be_hidden()
    page.set_viewport_size(dict(width=1280, height=900))
    toggle.click()
    expect(page.locator('#trace-links-panel-width')).to_have_value('54')
    assert not errors, errors
    page.close()


def run_touch(browser, width, height):
    page = browser.new_page(viewport=dict(width=width, height=height), is_mobile=True, has_touch=True)
    route_page(page, [])
    def response(route):
        query = parse_qs(urlparse(route.request.url).query)
        route.fulfill(json=sample_page(query) if 'a' in query else fixture('all'))
    page.route('**/api/trace-links?*', response)
    page.goto('http://trace-touch.test/')
    page.locator('#tab-trace').tap()
    expect(page.locator('#trace-links-status')).to_contain_text('2 Linkstrecken')
    page.locator('#trace-links-toggle-details').tap()
    page.locator('#trace-map').scroll_into_view_if_needed()
    page.evaluate('traceMap.setView([52.105,10.22], 12, {animate:false})')
    frames(page)
    point = line_point(page)
    assert page.evaluate('([x,y]) => document.elementFromPoint(x,y) instanceof HTMLCanvasElement', point)
    page.touchscreen.tap(*point)
    expect(page.locator('#trace-links-pair')).to_have_value(f'{A}/{B}')
    expect(page.locator('#trace-links-detail h3')).to_be_in_viewport()
    expect(page.locator('.trace-link-chart')).to_be_visible()
    expect(page.locator('.trace-link-tooltip')).to_have_count(0)
    page.locator('#trace-links-pair').select_option(f'{B}/{C}')
    expect(page.locator('#trace-links-detail h3')).to_have_text('Ost ↔ Süd')
    assert page.evaluate('document.querySelector("main").scrollWidth === document.querySelector("main").clientWidth')
    page.locator('#trace-links-options summary').tap()
    page.locator('#trace-links-label-mode').select_option('full')
    page.locator('#trace-links-options summary').tap()
    label = page.locator('.trace-link-tooltip').filter(has_text='West ↔ Ost')
    expect(label).to_contain_text('+0,125 dB')
    assert_tooltip_layout(label, 130)
    expect(page.locator('.trace-link-hover')).to_have_count(0)
    page.close()


def run_location_protection(browser):
    page = browser.new_page(viewport=dict(width=1280, height=900))
    route_page(page, [])
    payload = fixture('all')
    page.route('**/api/trace-links?*', lambda route: route.fulfill(json=payload))
    page.goto('http://trace-location-protection.test/')
    page.locator('#tab-trace').press('Enter')
    page.wait_for_function(PAINTED_LINKS, timeout=3000)
    page.locator('#tab-live').press('Enter')
    page.evaluate('''() => repeaterMapVisibility.addKeys(['bbcceed1'.padEnd(64, '0')])''')
    page.locator('#tab-trace').press('Enter')
    expect(page.locator('#trace-links-status')).to_have_text('1 Linkstrecke')
    pair = page.locator('#trace-links-pair option')
    assert pair.evaluate_all('options => options.map(option => option.value)') == ['', f'{A}/{B}']
    assert page.evaluate('Object.values(traceMap._layers).filter(layer => layer instanceof L.Polyline).length === 1')
    page.evaluate('''() => repeaterMapVisibility.addKeys(['bbccee12aa'.padEnd(64, '0')])''')
    expect(page.locator('#trace-links-status')).to_have_text('Keine Linkstrecken im Filter')
    assert page.evaluate('!Object.values(traceMap._layers).some(layer => layer instanceof L.Path)')
    page.close()


def benchmark(browser, folder):
    data = (folder / 'trace-links-0.json').read_text()
    payload = json.loads(data)
    page = browser.new_page(viewport=dict(width=1280, height=900))
    route_page(page, [])
    overview_requests = []
    def overview(route):
        overview_requests.append(route.request.url)
        route.fulfill(body=data, content_type='application/json')
    page.route('**/api/trace-links?*', overview)
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
    permanent_labels = page.locator('#trace-map .trace-link-tooltip').count()
    assert permanent_labels == 0
    switch_times = page.evaluate('''async () => {
      const control = document.querySelector('#trace-links-stat');
      const lines = Object.values(traceMap._layers).filter(layer => layer instanceof L.Path);
      const times = {};
      for (const statistic of ['last', 'min', 'max', 'median']) {
        const start = performance.now();
        control.value = statistic;
        control.dispatchEvent(new Event('change'));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        times[statistic] = Math.round(100 * (performance.now() - start)) / 100;
      }
      if (!lines.every(line => traceMap.hasLayer(line))) throw Error('Kartenlayer ausgetauscht');
      return times;
    }''')
    assert len(overview_requests) == 1
    active = idle()
    page.locator('#tab-live').click()
    frames(page)
    inactive_after = idle()
    browser_cdp.detach()
    page.close()
    return dict(links=len(payload['links']), permanent_labels=permanent_labels, decoded_data_to_paint_ms=round(render, 2),
                statistic_switch_to_paint_ms=switch_times, extra_statistic_requests=len(overview_requests) - 1,
                click_to_confirmed_render_ms=round(elapsed, 2), active=active,
                inactive_before=inactive_before, inactive_after=inactive_after)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', type=Path)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        run_initial_paint(browser)
        run_regression(browser)
        run_tooltip_layout(browser)
        run_location_protection(browser)
        run_touch(browser, 390, 844)
        run_touch(browser, 667, 375)
        print('Historische TRACE-Karte: Canvas, Labelmodi, Themes, Auswahl, Touch, Layout, Filter und Lazy Loading bestanden')
        if args.benchmark:
            print(json.dumps(benchmark(browser, args.benchmark), indent=2))
        browser.close()
