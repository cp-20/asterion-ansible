"""Local Docker integration test; never uses the production inventory or secrets.

Run with Python with PyYAML installed and ansible-playbook on PATH; install the
community.docker collection and requests for Ansible's Python interpreter.
Names, deployment paths and host ports are isolated for this test. The role's
ownership checks, container lifecycle, templates and HTTP behavior are exercised.
"""
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

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'project/roles/read-stack'
KEY = 'readstack-test-' + uuid.uuid4().hex[:10]
IMAGE = yaml.safe_load((ROLE / 'templates/docker-compose-deploy.yaml.j2').read_text())['services']['retired']['image']


def run(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check)


def inspect(name):
    return json.loads(run('docker', 'inspect', name).stdout)[0]


with tempfile.TemporaryDirectory(prefix=KEY) as work:
    work = Path(work)
    legacy = work / 'legacy'
    retired = work / 'retired'
    legacy.mkdir()
    sentinel = legacy / 'data-sentinel'
    sentinel.write_text('saved articles must survive')
    old_compose = legacy / 'docker-compose-deploy.yaml'
    old_compose.write_text('services: {old-app: {image: example.invalid/old}}\n')
    original_compose = old_compose.read_text()
    names = {service: KEY + '-' + service for service in ('web', 'server', 'swagger-viewer')}
    worker, unrelated, database = KEY + '-worker', KEY + '-unrelated', KEY + '-database'
    retirement_collision = KEY + '-collision'
    all_names = [*names.values(), worker, unrelated, database, retirement_collision]
    volume = KEY + '-data'
    run('docker', 'volume', 'create', volume)

    # Adapt only host paths, test container names, project name and published ports.
    tasks = (ROLE / 'tasks/main.yaml').read_text()
    tasks = tasks.replace('/srv/read-stack-retired', str(retired)).replace('/srv/read-stack', str(legacy))
    tasks = tasks.replace("== 'read-stack'", "== '" + KEY + "'")
    tasks = tasks.replace('com.docker.compose.project=read-stack-retired', 'com.docker.compose.project=' + KEY)
    tasks = tasks.replace('com.docker.compose.project=read-stack', 'com.docker.compose.project=' + KEY + '-legacy')
    tasks = tasks.replace("== '" + KEY + "'", "== '" + KEY + "-legacy'")
    tasks = tasks.replace("['web', 'server', 'swagger-viewer']", repr(list(names.values())))
    for service, name in names.items():
        tasks = tasks.replace('    - ' + service + '\n', '    - ' + name + '\n')
    assets = work / 'assets'
    shutil.copytree(ROLE / 'files', assets)
    tasks = tasks.replace("src: '{{ item }}'", "src: '" + str(assets) + "/{{ item }}'")
    template = yaml.safe_load((ROLE / 'templates/docker-compose-deploy.yaml.j2').read_text())
    template['services']['retired']['ports'] = ['127.0.0.1::' + str(p) for p in (3000, 8000, 4173)]
    template_path = work / 'compose-template.yaml'
    template_path.write_text(yaml.safe_dump(template))
    tasks = tasks.replace('src: docker-compose-deploy.yaml.j2', 'src: ' + str(template_path))
    tasks = tasks.replace('project_name: read-stack-retired', 'project_name: ' + KEY)
    tasks = tasks.replace('      - read-stack-retired\n', '      - ' + KEY + '\n')
    tasks_path = work / 'tasks.yaml'
    tasks_path.write_text(tasks)
    playbook = work / 'playbook.yaml'
    playbook.write_text(yaml.safe_dump([{'hosts': 'all', 'gather_facts': False,
                                       'tasks': [{'ansible.builtin.import_tasks': str(tasks_path)}]}]))
    command = ['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(playbook),
               '-e', 'ansible_python_interpreter=' + shutil.which('python'),
               '-e', 'ansible_remote_tmp=' + str(work / 'ansible-tmp')]

    def fixture(name, directory, service=None, project=KEY + '-legacy'):
        mounts = ['--mount', 'type=volume,src=' + volume + ',dst=/persist'] if name == names['server'] else []
        run('docker', 'run', '-d', '--name', name, '--restart', 'always',
            '--label', 'com.docker.compose.project.working_dir=' + directory,
            '--label', 'com.docker.compose.project=' + project,
            '--label', 'com.docker.compose.service=' + (service or name),
            *mounts, IMAGE, 'sleep', 'infinity')

    try:
        for name in names.values():
            fixture(name, str(legacy))
        fixture(worker, str(legacy), service=names['server'])
        fixture(unrelated, str(legacy), project=KEY + '-other')
        fixture(database, str(legacy), service='database')
        run('docker', 'exec', names['server'], 'sh', '-c', 'printf saved-articles > /persist/sentinel')
        # A colliding generic name must stop the play before any legacy stop.
        run('docker', 'rm', '-f', names['web'])
        fixture(names['web'], str(legacy), project=KEY + '-other')
        rejected = run(*command, check=False)
        assert rejected.returncode != 0, 'ownership conflict unexpectedly accepted'
        assert 'Verify legacy container ownership' in rejected.stdout, rejected.stdout + rejected.stderr
        assert 'unreachable=0' in rejected.stdout and 'failed=1' in rejected.stdout, rejected.stdout
        assert all(inspect(name)['State']['Running'] for name in all_names if name != retirement_collision)
        assert old_compose.read_text() == original_compose
        print('PASS ownership conflict aborts before stopping any container')
        run('docker', 'rm', '-f', names['web'])
        fixture(names['web'], str(legacy))
        unknown = run(*command, check=False)
        assert unknown.returncode != 0
        assert 'Require every discovered service' in unknown.stdout, unknown.stdout + unknown.stderr
        assert 'unreachable=0' in unknown.stdout and 'failed=1' in unknown.stdout
        assert all(inspect(name)['State']['Running'] for name in all_names if name != retirement_collision)
        assert old_compose.read_text() == original_compose
        print('PASS unknown service/database aborts before stopping any container or modifying Compose')
        run('docker', 'rm', '-f', database)
        fixture(retirement_collision, '/unrelated', service='retired', project=KEY)
        collision = run(*command, check=False)
        assert collision.returncode != 0
        assert 'Verify retirement project ownership' in collision.stdout, collision.stdout + collision.stderr
        assert all(inspect(name)['State']['Running'] for name in all_names if name != database)
        assert old_compose.read_text() == original_compose
        run('docker', 'rm', '-f', retirement_collision)
        print('PASS retirement project collision aborts before staging or stopping')
        original_ids = {name: inspect(name)['Id'] for name in all_names if name not in (database, retirement_collision)}

        valid_config = (assets / 'default.conf').read_text()
        (assets / 'default.conf').write_text('invalid-nginx-directive;\n')
        invalid = run(*command, check=False)
        assert invalid.returncode != 0
        assert 'Validate Nginx without publishing service ports' in invalid.stdout, invalid.stdout + invalid.stderr
        assert 'unreachable=0' in invalid.stdout and 'failed=1' in invalid.stdout
        assert all(inspect(name)['State']['Running'] for name in original_ids)
        assert old_compose.read_text() == original_compose
        (assets / 'default.conf').write_text(valid_config)
        print('PASS invalid static configuration aborts while legacy applications keep running')

        result = run(*command, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        for name in [*names.values(), worker]:
            info = inspect(name)
            assert info['Id'] == original_ids[name]
            assert not info['State']['Running']
            assert info['HostConfig']['RestartPolicy']['Name'] == 'no'
        assert inspect(unrelated)['State']['Running']
        assert sentinel.read_text() == 'saved articles must survive'
        assert run('docker', 'run', '--rm', '--mount', 'type=volume,src=' + volume + ',dst=/persist,readonly',
                   IMAGE, 'cat', '/persist/sentinel').stdout == 'saved-articles'
        assert yaml.safe_load(old_compose.read_text()) == {'services': {}}
        assert any(p.read_text() == original_compose for p in legacy.glob('docker-compose-deploy.yaml.*~'))
        print('PASS legacy web/API/Swagger/server replica stopped; other project in same directory and data preserved; backup retained')

        def request(port, path, expected, method='GET'):
            binding = run('docker', 'compose', '-p', KEY, '-f', str(retired / 'compose.yaml'),
                          'port', 'retired', str(port)).stdout.strip()
            url = 'http://' + binding + path
            for attempt in range(30):
                try:
                    response = urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=2)
                    break
                except urllib.error.HTTPError as error:
                    response = error
                    break
                except (OSError, urllib.error.URLError):
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
                    else:
                        assert json.loads(body)['message'] == 'ReadStack has ended service.'
                return body

        for port in (3000, 4173):
            for path in ('/', '/saved/article', '/_next/old.js', '/swagger'):
                request(port, path, 200)
            for path in ('/api', '/api/articles?url=https://example.com', '/API/test'):
                request(port, path, 410)
            request(port, '/api/articles', 410, 'POST')
            request(port, '/', 200, 'HEAD')
        for path in ('/', '/api/articles', '/anything'):
            request(8000, path, 410)
            request(8000, path, 410, 'POST')
        print('PASS HTTP: static pages on 3000/4173; API 410 on every old port; GET/HEAD/POST')

        second = run(*command, check=False)
        assert second.returncode == 0, second.stdout + second.stderr
        assert 'changed=0' in second.stdout, second.stdout
        print('PASS second role execution is idempotent')
        with (assets / 'index.html').open('a') as page:
            page.write('\n<!-- retirement-update -->\n')
        update = run(*command, check=False)
        assert update.returncode == 0, update.stdout + update.stderr
        assert 'retirement-update' in request(3000, '/', 200)
        unchanged = run(*command, check=False)
        assert unchanged.returncode == 0, unchanged.stdout + unchanged.stderr
        assert 'changed=0' in unchanged.stdout, unchanged.stdout
        print('PASS static asset update reaches HTTP; following execution is idempotent')
        for name in [*names.values(), worker]:
            run('docker', 'rm', name)
        absent = run(*command, check=False)
        assert absent.returncode == 0, absent.stdout + absent.stderr
        assert inspect(unrelated)['State']['Running']
        print('PASS rerun also succeeds when legacy containers are absent')
    finally:
        run('docker', 'compose', '-p', KEY, '-f', str(retired / 'compose.yaml'), 'down', check=False)
        for name in all_names:
            run('docker', 'rm', '-f', name, check=False)
        run('docker', 'volume', 'rm', volume, check=False)
