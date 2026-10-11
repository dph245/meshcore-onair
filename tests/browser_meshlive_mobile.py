"""Offline responsive/touch regression. Emulation, not physical mobile hardware."""
from playwright.sync_api import sync_playwright, expect
from browser_meshlive import route_page, emit, packet
from browser_replay import fixture

SIZES=[(320,568),(375,667),(390,844),(430,932),(844,390),(1440,900)]


def inside(page, selector):
    box=page.locator(selector).bounding_box()
    assert box,selector
    size=page.viewport_size
    assert box['x']>=0 and box['y']>=0 and box['x']+box['width']<=size['width']+1 and box['y']+box['height']<=size['height']+1,(selector,box,size)


def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width,height in SIZES:
            page=browser.new_page(viewport={'width':width,'height':height},has_touch=True)
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            route_page(page,[])
            page.route('**/api/meshlive/replay',lambda route:route.fulfill(json=fixture()))
            page.goto('http://mobile.test/')
            page.evaluate('''()=>{const create=L.map;L.map=(...a)=>window.__map=create(...a);}''')
            page.locator('#tab-meshlive').tap()
            expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes · Live')
            page.wait_for_timeout(150)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            for selector in ['#meshlive-map','#meshlive-pause','#meshlive-tones','#meshlive-replay-start']:
                inside(page,selector)
            mobile=page.locator('#meshlive-more').is_visible()
            if mobile:
                assert page.locator('#meshlive-more').get_attribute('aria-expanded')=='false'
                page.locator('#meshlive-more').tap()
            page.locator('#meshlive-fit').tap()
            if mobile:page.locator('#meshlive-more').tap()
            page.wait_for_timeout(150)
            # Real CDP touch gestures reach Leaflet through the canvas.
            box=page.locator('#meshlive-map').bounding_box()
            x,y=box['x']+box['width']/2,box['y']+box['height']/2
            center=page.evaluate('window.__map.getCenter()')
            cdp=page.context.new_cdp_session(page)
            cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
            for step in range(1,7):
                cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x+step*8,'y':y+step*2}]})
            cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
            page.wait_for_timeout(200)
            assert page.evaluate('window.__map.getCenter()')!=center,'Touch pan blocked'
            zoom=page.evaluate('window.__map.getZoom()')
            cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x-30,'y':y},{'x':x+30,'y':y}]})
            for offset in [40,50,60,70]:
                cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x-offset,'y':y},{'x':x+offset,'y':y}]})
                page.wait_for_timeout(30)
            cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
            page.wait_for_timeout(250)
            assert page.evaluate('window.__map.getZoom()')>zoom,'Pinch zoom blocked'
            zoom=page.evaluate('window.__map.getZoom()')
            page.locator('#meshlive-map .leaflet-control-zoom-in').tap()
            assert page.evaluate('window.__map.getZoom()')==zoom+1
            page.locator('#meshlive-tones').check()
            assert page.evaluate('localStorage.getItem("onair-meshlive-tones")')=='true'
            emit(page,[packet(1)])
            page.wait_for_function('window.__meshStrokes.length>0')
            page.locator('#meshlive-replay-start').tap()
            expect(page.locator('#meshlive-status')).to_contain_text('REPLAY · 10×')
            page.wait_for_timeout(150)
            for selector in ['#meshlive-tones','#meshlive-replay-pause','#meshlive-replay-end','#meshlive-replay-progress']:
                inside(page,selector)
            page.locator('#meshlive-replay-pause').tap()
            expect(page.locator('#meshlive-replay-pause')).to_have_text('Replay fortsetzen')
            page.locator('#meshlive-replay-pause').tap()
            page.locator('#tab-live').click()
            page.locator('#tab-meshlive').tap()
            expect(page.locator('#meshlive-replay-pause')).to_have_text('Replay fortsetzen')
            page.screenshot(path=f'/tmp/meshlive-mobile-{width}x{height}.png')
            page.locator('#meshlive-replay-end').tap()
            expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes · Live')
            # Rotation and changing browser-UI height resize both Leaflet and canvas.
            for w,h in [(height,width),(width,max(350,height-90)),(width,height)]:
                page.set_viewport_size({'width':w,'height':h});page.wait_for_timeout(150)
                assert page.evaluate('''()=>{const e=document.querySelector('#meshlive-map'),c=e.querySelector('canvas'),s=window.__map.getSize();return Math.abs(s.x-e.clientWidth)<2 && Math.abs(s.y-e.clientHeight)<2 && c.width===Math.ceil(s.x*Math.min(2,devicePixelRatio));}''')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert not errors,errors
            print(f'{width}x{height}: map {box["height"]:.0f}px; controls, pan, zoom, audio, replay, tabs and resize passed')
            page.close()
        browser.close()


if __name__=='__main__':main()
