"""Short landscape shell, independent scrolling, safe-area simulation and resize."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from browser_responsive import fixtures, emit, packet

SIZES = [(667, 375), (844, 390), (932, 430)]
CSS_MARKER = '/* Short phone landscape:'


def shell(page):
    result = page.evaluate('''()=>{
      const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
      return {main:rect('main'),tabs:rect('.tabs'),active:rect('[role=tab][aria-selected=true]'),
        header:rect('header'),width:innerWidth,height:innerHeight,
        overflow:document.documentElement.scrollWidth>innerWidth};
    }''')
    assert not result['overflow'], result
    assert result['main']['y'] <= 65, result
    assert result['main']['bottom'] <= result['height'], result
    assert result['main']['y'] >= result['tabs']['bottom'], result
    assert result['active']['x'] >= result['tabs']['x'] - 1, result
    assert result['active']['right'] <= result['tabs']['right'] + 1, result
    assert result['tabs']['right'] <= result['header']['x'] + 1, result
    return result


def map_size(page, map_id):
    page.wait_for_function('''id=>{
      const e=document.getElementById(id),s=window.__maps[id]?.getSize();
      const c=e.querySelector('canvas');
      return s && Math.abs(s.x-e.clientWidth)<2 && Math.abs(s.y-e.clientHeight)<2 &&
        (!c || (c.width===Math.ceil(s.x*Math.min(2,devicePixelRatio)) && c.height===Math.ceil(s.y*Math.min(2,devicePixelRatio))));
    }''', arg=map_id)
    box = page.locator('#'+map_id).bounding_box()
    sidebar = page.locator('[role=tabpanel]:visible .map-sidebar').bounding_box()
    size = page.viewport_size
    # The normal map now reserves an explicit compact row for selection/search.
    tools = page.locator('.map-selection-tools').bounding_box() if map_id == 'node-map' else None
    reserved = tools['height'] + 14 if tools else 0
    assert box['y'] >= 50 and box['height'] >= size['height'] - 110 - reserved, (box, size)
    if tools:
        assert tools['y'] + tools['height'] <= box['y']
        assert tools['height'] <= 90, tools
    assert box['y'] + box['height'] <= size['height'], (box, size)
    assert box['x'] + box['width'] <= sidebar['x'], (box, sidebar)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        for width, height in SIZES:
            page = browser.new_page(viewport=dict(width=width, height=height), has_touch=True)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            fixtures(page); page.goto('http://landscape.test/')
            emit(page, [packet(i) for i in range(30)], 'snapshot')
            page.evaluate('''()=>{window.__maps={};const create=L.map;
              L.map=(id,...args)=>window.__maps[id]=create(id,...args);}''')
            for tab_id in page.locator('[role=tab]').evaluate_all('(els)=>els.map(e=>e.id)'):
                page.locator('#'+tab_id).tap()
                shell(page)
                expect(page.locator('#theme-toggle')).to_be_visible()
                if tab_id != 'tab-meshlive':
                    expect(page.locator('#pause')).to_be_visible()
            for tab, map_id in [('map','node-map'), ('meshlive','meshlive-map')]:
                page.locator('#tab-'+tab).tap()
                if tab == 'meshlive': page.locator('#meshlive-more').tap()
                for w,h in [(width,height),(height,width),(width,height-80),(width,height)]:
                    page.set_viewport_size(dict(width=w,height=h))
                    page.wait_for_timeout(150)
                    if w>h:
                        shell(page);map_size(page,map_id)
                sidebar = page.locator(f'#panel-{tab} .map-sidebar')
                # Open help, then scroll its own content without moving the map/navigation.
                summary = sidebar.locator('summary').first
                if summary.count(): summary.tap()
                before = page.locator('#'+map_id).bounding_box()
                sidebar.hover();page.mouse.wheel(0,700);page.wait_for_timeout(150)
                assert sidebar.evaluate('(e)=>e.scrollTop') > 0
                assert page.locator('#'+map_id).bounding_box() == before
                shell(page)
                sidebar.evaluate('(e)=>e.scrollTop=0')
                # Non-zero padding models the space occupied by landscape cutouts/home indicator.
                page.add_style_tag(content='body{padding:8px 44px 16px!important}')
                page.wait_for_timeout(150);shell(page);map_size(page,map_id)
                page.screenshot(path=f'/tmp/onair-landscape-{width}-{tab}.png')
                page.locator('style').last.evaluate('(e)=>e.remove()')
            page.locator('#tab-archive').tap()
            # Enough content to exercise main scrolling even with an empty archive.
            page.locator('#archive-results').evaluate("e=>{const p=document.createElement('p');p.style.height='900px';p.textContent='Scroll fixture';e.append(p)}")
            page.locator('#archive-results').hover();page.mouse.wheel(0,600)
            page.wait_for_function('document.querySelector("main").scrollTop>0')
            shell(page)
            page.locator('#tab-live').tap();shell(page)
            assert not errors, errors
            print(f'{width}x{height}: all tabs, one-row shell, scroll, rotation, safe-area spacing and both map resizes passed', flush=True)
            page.close()
        # Outside the new media query, computed geometry must equal the previous CSS.
        for width,height in [(375,667),(390,844),(768,1024),(1440,900)]:
            page=browser.new_page(viewport=dict(width=width,height=height),has_touch=True)
            fixtures(page);page.goto('http://portrait.test/')
            css=Path('static/style.css').read_text().split(CSS_MARKER)[0]
            for tab in ['live','map','meshlive','archive']:
                page.locator('#tab-'+tab).tap();page.wait_for_timeout(100)
                geometry='''()=>['header','.toolbar','.tabs','main','[role=tabpanel]:not([hidden])'].map(s=>{
                  const r=document.querySelector(s).getBoundingClientRect();return [r.x,r.y,r.width,r.height]})'''
                current=page.evaluate(geometry)
                page.locator('link[href*="/static/style.css"]').evaluate('(e)=>e.disabled=true')
                style=page.add_style_tag(content=css)
                assert page.evaluate(geometry)==current,(width,height,tab)
                page.locator('link[href*="/static/style.css"]').evaluate('(e)=>e.disabled=false')
                style.evaluate('(e)=>e.remove()')
            page.close()
            print(f'{width}x{height}: portrait/tablet/desktop geometry unchanged',flush=True)
        browser.close()


if __name__=='__main__': main()
