"""Offline real Chromium/Web Audio lifecycle and bounded draw load."""
from playwright.sync_api import sync_playwright, expect
from browser_meshlive import route_page, emit, packet
from browser_replay import fixture


def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,
                                  args=['--no-sandbox','--disable-dev-shm-usage'])
        page=browser.new_page(viewport={'width':1280,'height':900})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        route_page(page,[])
        page.add_init_script('''
          window.__audio=[]; window.__notes=[]; window.__drawTimes=[];
          const Native=window.AudioContext;
          window.AudioContext=class extends Native {
            constructor(...args){super(...args);window.__audio.push(this);}
            createOscillator(){const o=super.createOscillator(),start=o.start.bind(o);
              o.start=(...args)=>{window.__notes.push(o.frequency.value);return start(...args)};return o;}
          };
          const frame=window.requestAnimationFrame;
          window.requestAnimationFrame=fn=>frame(t=>{const s=performance.now();fn(t);
            if(fn.name==='draw')window.__drawTimes.push(performance.now()-s);});
        ''')
        page.goto('http://harp.test/')
        page.locator('#tab-meshlive').click()
        expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes · Live')
        page.locator('#meshlive-fit').click()
        assert not page.locator('#meshlive-tones').is_checked()
        assert page.evaluate('window.__audio.length')==0
        page.locator('#meshlive-tones').check()
        page.wait_for_function('window.__audio[0]?.state === "running"')
        emit(page,[packet(1)])
        page.wait_for_function('window.__notes.length >= 6')
        page.wait_for_function('Array.from(document.querySelectorAll(".meshlive-node-dot")).some(e=>e.style.transform && e.style.transform!=="scale(1)")')
        page.wait_for_timeout(800)
        assert page.evaluate('window.__notes.length')==9
        emit(page,[packet(2,hash_value='HASH1')])
        page.wait_for_timeout(100)
        assert page.evaluate('window.__notes.length')==9
        page.locator('#meshlive-pause').click()
        page.wait_for_function('window.__audio[0].state === "suspended"')
        page.locator('#meshlive-pause').click()
        page.wait_for_function('window.__audio[0].state === "running"')
        page.evaluate('window.__notes=[];window.__drawTimes=[]')
        emit(page,[packet(i) for i in range(10,210)])
        page.wait_for_timeout(3200)
        assert page.evaluate('window.__notes.length')<=24
        times=page.evaluate('window.__drawTimes.slice().sort((a,b)=>a-b)')
        print('Desktop 64-trail burst: draw p95=%.2fms max=%.2fms'%(times[int(len(times)*.95)],max(times)))
        assert '336 Spuren am Limit ausgelassen' in page.locator('#meshlive-status').inner_text()
        page.locator('#tab-live').click()
        page.wait_for_function('window.__audio[0].state === "suspended"')
        count=page.evaluate('window.__notes.length')
        emit(page,[packet(250)])
        page.wait_for_timeout(100)
        assert page.evaluate('window.__notes.length')==count
        page.reload()
        assert page.evaluate('window.__audio.length')==0
        page.locator('#tab-meshlive').click()
        expect(page.locator('#meshlive-tones')).to_be_checked()
        page.locator('#meshlive-tones').uncheck()
        page.wait_for_function('window.__audio[0].state === "suspended"')
        page.set_viewport_size({'width':390,'height':844})
        page.locator('#meshlive-fit').click()
        page.locator('#meshlive-tones').check()
        page.wait_for_function('window.__audio[0].state === "running"')
        page.evaluate('window.__drawTimes=[];window.__notes=[]')
        emit(page,[packet(i) for i in range(300,500)])
        page.wait_for_timeout(3200)
        assert page.evaluate('window.__notes.length')<=24
        times=page.evaluate('window.__drawTimes.slice().sort((a,b)=>a-b)')
        print('Mobile viewport 64-trail burst: draw p95=%.2fms max=%.2fms'%(times[int(len(times)*.95)],max(times)))
        page.locator('#meshlive-tones').uncheck()
        assert page.evaluate('localStorage.getItem("onair-meshlive-tones")')=='false'
        # Real audio is also stopped by replay pause, tab changes and cancellation.
        page.route('**/api/meshlive/replay',lambda route:route.fulfill(json=fixture()))
        page.locator('#meshlive-tones').check()
        page.locator('#meshlive-replay-start').click()
        expect(page.locator('#meshlive-status')).to_contain_text('REPLAY · 10×')
        page.wait_for_function('window.__audio[0].state === "running"')
        page.wait_for_timeout(250)
        page.locator('#meshlive-replay-pause').click()
        page.wait_for_function('window.__audio[0].state === "suspended"')
        count=page.evaluate('window.__notes.length')
        page.wait_for_timeout(200)
        assert page.evaluate('window.__notes.length')==count
        page.locator('#meshlive-replay-pause').click()
        page.wait_for_function('window.__audio[0].state === "running"')
        page.locator('#tab-live').click()
        page.wait_for_function('window.__audio[0].state === "suspended"')
        page.locator('#tab-meshlive').click()
        expect(page.locator('#meshlive-replay-pause')).to_have_text('Replay fortsetzen')
        assert page.evaluate('window.__audio[0].state')=='suspended'
        page.locator('#meshlive-replay-end').click()
        expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes · Live')
        page.locator('#meshlive-tones').uncheck()
        # Unsupported audio does not disable the visual map.
        page.add_init_script('window.AudioContext=undefined; window.webkitAudioContext=undefined;')
        page.reload()
        page.locator('#tab-meshlive').click()
        expect(page.locator('#meshlive-status')).to_contain_text('4 Nodes · Live')
        expect(page.locator('#meshlive-tones')).to_be_disabled()
        assert not errors,errors
        browser.close()
    print('Harp Chromium: real Web Audio, pulses, persistence, pause, tabs, mobile and load passed')


if __name__=='__main__':main()
