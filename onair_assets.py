"""Content versions for the small local frontend; no build step or mtime cache."""
from hashlib import sha256
import mimetypes
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from starlette.datastructures import Headers, QueryParams
from starlette.responses import HTMLResponse, Response
from starlette.staticfiles import StaticFiles

ASSET_LINK = re.compile(r'''\b(?:src|href)=(['"])(/static/[^'"<>]+\.(?:css|js)(?:\?[^'"<>]*)?)\1''')


def render_index(directory: Path) -> str:
    directory = directory.resolve()

    def version_link(match):
        url = urlsplit(match[2])
        path = (directory / url.path.removeprefix('/static/')).resolve()
        if not path.is_relative_to(directory):
            raise ValueError('Asset outside static directory')
        version = sha256(path.read_bytes()).hexdigest()[:12]
        query = [(key, value) for key, value in parse_qsl(url.query) if key != 'v']
        query.append(('v', version))
        versioned = urlunsplit(('', '', url.path, urlencode(query), url.fragment))
        return match[0].replace(match[2], versioned)

    return ASSET_LINK.sub(version_link, (directory / 'index.html').read_text(encoding='utf-8'))


def index_response(directory: Path) -> HTMLResponse:
    # A new document must discover new asset URLs even behind a reverse proxy.
    return HTMLResponse(render_index(directory), headers={'Cache-Control': 'no-cache'})


class VersionedStaticFiles(StaticFiles):
    def file_response(self, full_path, stat_result, scope, status_code=200):
        # StaticFiles still validates methods and paths (including symlinks).
        if Path(full_path) == Path(self.directory).resolve() / 'index.html':
            response = index_response(Path(self.directory))
        else:
            # Hash and send the same bytes. Even equal size/mtime replacements
            # receive a new ETag; old version URLs must never become immutable.
            body = Path(full_path).read_bytes()
            digest = sha256(body).hexdigest()
            version = QueryParams(scope['query_string']).get('v')
            policy = 'public, max-age=31536000, immutable' if version == digest[:12] else 'no-cache'
            headers = {'ETag': f'"{digest}"', 'Cache-Control': policy}
            tags = [tag.strip().removeprefix('W/') for tag in
                    Headers(scope=scope).get('if-none-match', '').split(',')]
            if headers['ETag'] in tags or '*' in tags:
                return Response(status_code=304, headers=headers)
            response = Response(body, status_code=status_code, headers=headers,
                                media_type=mimetypes.guess_type(full_path)[0] or 'application/octet-stream')
        if scope['method'] == 'HEAD':
            response.body = b''  # Preserve the GET content-length.
        return response
