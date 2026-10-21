"""Smoke-test static files with local Docker, temporary ports and no inventory."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

import yaml

assets = Path(__file__).resolve().parents[1] / 'project/roles/read-stack/files'
with tempfile.TemporaryDirectory(prefix='readstack-static-') as directory:
    directory = Path(directory)
    for name in ('index.html', 'default.conf', 'compose.yaml'):
        shutil.copy(assets / name, directory / name)
    config = yaml.safe_load((directory / 'compose.yaml').read_text())
    config['services']['retired']['ports'] = ['127.0.0.1::' + str(p) for p in (3000, 4173, 8000)]
    (directory / 'compose.yaml').write_text(yaml.safe_dump(config))
    compose = ['docker', 'compose', '-p', 'readstack-test-' + uuid.uuid4().hex[:8], '-f', str(directory / 'compose.yaml')]

    def run(*args):
        return subprocess.check_output([*compose, *args], text=True)

    try:
        run('config', '--quiet')
        run('run', '--rm', '--no-deps', 'retired', 'nginx', '-t')
        run('up', '-d')
        for port in (3000, 4173, 8000):
            origin = 'http://' + run('port', 'retired', str(port)).strip()
            for path, method in (('/', 'GET'), ('/saved/article', 'GET'), ('/api', 'GET'), ('/api/articles', 'POST'), ('/api/articles', 'HEAD')):
                expected = 410 if port == 8000 or path.startswith('/api') else 200
                for attempt in range(30):
                    try:
                        response = urllib.request.urlopen(urllib.request.Request(origin + path, method=method), timeout=2)
                        break
                    except urllib.error.HTTPError as error:
                        response = error
                        break
                    except urllib.error.URLError:
                        if attempt == 29:
                            raise
                        time.sleep(0.1)
                with response:
                    body = response.read().decode()
                    assert response.code == expected, (port, path, response.code)
                    assert response.headers['Cache-Control'] == 'no-store'
                    if method != 'HEAD':
                        if expected == 200:
                            assert 'ReadStack はサービスを終了しました。' in body
                            assert 'mailto:contact@cp20.dev' in body
                            assert 'name="viewport"' in body
                        else:
                            assert json.loads(body)['message'] == 'ReadStack has ended service.'
        print('PASS Compose/Nginx configuration; static pages and API 410 on all three ports (GET/POST/HEAD)')
    finally:
        subprocess.run([*compose, 'down'], check=True)
