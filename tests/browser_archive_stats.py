"""Offline Chromium test for the archive statistics in the real dashboard."""
from playwright.sync_api import expect, sync_playwright

from browser_meshlive import route_page


def check(browser, width):
    page = browser.new_page(viewport={'width': width, 'height': 800})
    page.clock.install()
    route_page(page, [])
    replies = iter([
        dict(total_packets=1_963_042, packets_last_24h=1234, database_bytes=8 * 1024**3 + 512 * 1024**2),
        dict(total_packets=1_963_046, packets_last_24h=0, database_bytes=None),
        None,
        dict(total_packets=1_963_050, packets_last_24h=8, database_bytes=1024),
    ])
    requests = []

    def stats(route):
        reply = next(replies)
        requests.append(route.request.url)
        if reply is None:
            route.fulfill(status=503)
        else:
            route.fulfill(json=reply)

    page.route('**/api/archive/stats', stats)
    page.goto('http://onair.local/')
    total = page.locator('#archive-stats-total')
    recent = page.locator('#archive-stats-recent')
    size = page.locator('#archive-stats-size')
    expect(total).to_have_text('—')
    assert requests == []
    page.locator('#tab-archive').click()
    expect(total).to_have_text('1.963.042')
    expect(recent).to_have_text('1.234')
    expect(size).to_have_text('8,5 GiB')
    expect(size).to_have_attribute('title', '9.126.805.504 Byte')
    assert page.locator('.archive-stats').evaluate('e => e.scrollWidth <= e.clientWidth')
    search = page.locator('#archive-search [name=q]')
    search.fill('Testsuche')

    page.clock.fast_forward(30_000)
    expect(total).to_have_text('1.963.046')
    expect(recent).to_have_text('0')
    expect(size).to_have_text('—')
    expect(search).to_have_value('Testsuche')

    page.clock.fast_forward(30_000)
    expect(total).to_have_text('—')
    expect(recent).to_have_text('—')

    page.locator('#tab-live').click()
    page.clock.fast_forward(30_000)
    assert len(requests) == 3
    page.locator('#tab-archive').click()
    expect(total).to_have_text('1.963.050')
    expect(size).to_have_text('1 KiB')
    expect(search).to_have_value('Testsuche')
    page.close()


if __name__ == '__main__':
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                             args=['--no-sandbox'])
        for width in (320, 1440):
            check(browser, width)
        print('Archivstatistik: Formatierung, Aktualisierung und Fehleranzeige bei 320 und 1440 Pixeln geprüft.')
