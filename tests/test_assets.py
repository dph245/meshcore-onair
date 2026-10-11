"""Asset version/cache regressions without MQTT, lifespan or production data."""
from hashlib import sha256
import os
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import urlsplit

from fastapi import FastAPI
from onair_assets import VersionedStaticFiles, index_response, render_index


async def request(app, url, method='GET', headers=None):
    parsed = urlsplit(url)
    messages = []

    async def receive():
        return {'type': 'http.request', 'body': b''}

    async def send(message):
        messages.append(message)

    await app({'type': 'http', 'method': method, 'path': parsed.path,
               'root_path': '', 'query_string': parsed.query.encode(),
               'headers': [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
               'http_version': '1.1', 'scheme': 'http'}, receive, send)
    return (messages[0]['status'], dict((k.decode(), v.decode()) for k, v in messages[0]['headers']),
            b''.join(m.get('body', b'') for m in messages[1:]))


class AssetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.directory.joinpath('index.html').write_text(
            '<link rel="stylesheet" href="/static/style.css">'
            '<script src="/static/app.js" defer></script>'
            '<script src="/static/dependency.js" defer></script>')
        for filename, content in [('style.css', 'body{color:red}'), ('app.js', 'const app = 1;'),
                                  ('dependency.js', 'const dependency = 1;'), ('icon.png', 'binary')]:
            self.directory.joinpath(filename).write_text(content)
        self.app = FastAPI()
        self.app.get('/')(lambda: index_response(self.directory))
        self.app.mount('/static', VersionedStaticFiles(directory=self.directory))

    def urls(self):
        return re.findall(r'(?:src|href)="([^"]+)"', render_index(self.directory))

    async def test_unchanged_files_keep_versions_and_can_be_cached(self):
        first = self.urls()
        self.directory.joinpath('app.js').touch()
        self.assertEqual(first, self.urls())
        for url in first:
            status, headers, body = await request(self.app, url)
            self.assertEqual(status, 200)
            self.assertIn('immutable', headers['cache-control'])
            self.assertEqual(urlsplit(url).query, 'v=' + sha256(body).hexdigest()[:12])
            status, cached_headers, body = await request(self.app, url, headers={'If-None-Match': headers['etag']})
            self.assertEqual((status, body), (304, b''))
            self.assertEqual(cached_headers['cache-control'], headers['cache-control'])

    async def test_changed_css_js_and_dependency_even_with_same_size_and_mtime(self):
        for filename in ['style.css', 'app.js', 'dependency.js']:
            with self.subTest(filename=filename):
                before = self.urls()
                position = next(i for i, url in enumerate(before) if filename in url)
                _, old_headers, _ = await request(self.app, before[position])
                path = self.directory / filename
                old_stat = path.stat()
                body = path.read_bytes()
                path.write_bytes(body.replace(b'red', b'tan') if filename.endswith('css') else body.replace(b'1', b'2'))
                os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
                after = self.urls()
                self.assertNotEqual(before[position], after[position])
                self.assertEqual(before[:position] + before[position+1:], after[:position] + after[position+1:])
                status, headers, current = await request(self.app, before[position], headers={
                    'If-None-Match': old_headers['etag'], 'If-Modified-Since': 'Wed, 01 Jan 2099 00:00:00 GMT'})
                self.assertEqual(status, 200)
                self.assertNotEqual(headers['etag'], old_headers['etag'])
                self.assertEqual(headers['cache-control'], 'no-cache')
                self.assertEqual(current, path.read_bytes())
                self.assertIn('immutable', (await request(self.app, after[position]))[1]['cache-control'])

    async def test_unversioned_dynamic_resources_revalidate_by_content(self):
        _, image_headers, _ = await request(self.app, '/static/icon.png')
        for url in ['/static/icon.png', '/static/app.js', '/static/app.js?v=wrong']:
            status, headers, body = await request(self.app, url)
            self.assertEqual(status, 200)
            self.assertEqual(headers['cache-control'], 'no-cache')
            self.assertEqual((await request(self.app, url, headers={'If-None-Match': 'W/' + headers['etag']}))[0], 304)
        self.directory.joinpath('icon.png').write_bytes(b'change')
        self.assertEqual((await request(self.app, '/static/icon.png', headers={'If-None-Match': image_headers['etag']}))[0], 200)

    async def test_html_alias_and_head(self):
        for url in ['/', '/static/index.html', '/static/index.html?v=anything']:
            status, headers, body = await request(self.app, url)
            self.assertEqual(status, 200)
            self.assertEqual(headers['cache-control'], 'no-cache')
            self.assertIn(b'/static/app.js?v=', body)
        url = self.urls()[0]
        _, headers, body = await request(self.app, url)
        status, head_headers, head_body = await request(self.app, url, method='HEAD')
        self.assertEqual((status, head_body), (200, b''))
        self.assertEqual(head_headers, headers)
        self.assertEqual(int(head_headers['content-length']), len(body))

    async def test_missing_files_paths_and_methods_stay_restricted(self):
        for url in ['/static/missing.js?v=abc', '/static/../onair_web.py']:
            self.assertEqual((await request(self.app, url))[0], 404)
        self.assertEqual((await request(self.app, self.urls()[0], method='POST'))[0], 405)

    async def test_real_application_versions_all_local_styles_and_scripts(self):
        import onair_web
        status, headers, body = await request(onair_web.app, '/')
        self.assertEqual(status, 200)
        self.assertEqual(headers['cache-control'], 'no-cache')
        urls = re.findall(r'(?:src|href)="(/static/[^\"]+)"', body.decode())
        expected = {p.relative_to(onair_web.STATIC).as_posix() for p in onair_web.STATIC.rglob('*')
                    if p.suffix in ('.css', '.js')}
        self.assertEqual({urlsplit(url).path.removeprefix('/static/') for url in urls}, expected)
        for url in urls:
            status, headers, body = await request(onair_web.app, url)
            self.assertEqual(status, 200, url)
            self.assertEqual(urlsplit(url).query, 'v=' + sha256(body).hexdigest()[:12])
            self.assertIn('immutable', headers['cache-control'])
            self.assertIn('javascript' if '.js?' in url else 'text/css', headers['content-type'])


if __name__ == '__main__':
    unittest.main()
