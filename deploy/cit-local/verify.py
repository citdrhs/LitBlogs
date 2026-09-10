"""Read-only verification of the actual loopback HTTPS deployment; no mail sent."""

import http.client
import json
import re
import socket
import ssl
import subprocess
from pathlib import Path

STATE = Path('/home/litblogs/.local/state/cit-deploy')
REPO = Path('/home/litblogs/www/LitBlogs')
HOST = 'litblogs.cit.internal'
PORT = 18443


def request(path, *, headers=None, method='GET', body=None):
    context = ssl.create_default_context(cafile=str(STATE / 'https/server.crt'))
    connection = http.client.HTTPSConnection(HOST, PORT, timeout=20, context=context)
    connection._create_connection = lambda *args, **kwargs: socket.create_connection(('127.0.0.1', PORT), timeout=20)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read(12 * 1024 * 1024)
        return response.status, {k.lower(): v for k, v in response.getheaders()}, data
    finally:
        connection.close()


def compose(*args):
    result = subprocess.run([
        '/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'compose', '--project-name', 'litblogs-cit',
        '--project-directory', str(REPO), '--env-file', str(STATE / '.env'),
        '-f', str(REPO / 'docker-compose.yml'), '-f', str(STATE / 'compose.yaml'), *args,
    ], check=True, capture_output=True, timeout=90,
       env={'PATH': '/usr/bin:/bin', 'HOME': '/root', 'LANG': 'C.UTF-8'})
    return result.stdout


def main():
    evidence = {}
    status, headers, body = request('/api/health/ready')
    assert status == 200 and json.loads(body)['status'] == 'ready'
    evidence['https_certificate_hostname_and_readiness'] = True
    status, _, body = request('/api/runtime-config')
    assert status == 200
    config = json.loads(body)
    assert config.get('local_password_registration_enabled') is True
    assert config.get('google_oauth_enabled') is False
    assert config.get('microsoft_oauth_enabled') is False
    evidence['password_registration_and_disabled_oauth'] = True
    for route in ('/', '/index.html', '/help', '/sign-in'):
        status, headers, body = request(route)
        assert status == 200 and b'<html' in body.lower()
        assert 'no-store' in headers.get('cache-control', '')
        assert headers.get('x-content-type-options') == 'nosniff'
        assert 'content-security-policy' in headers
    evidence['frontend_routes_cache_and_security_headers'] = True
    assert request('/api/health/ready', headers={'Host': 'unapproved.invalid'})[0] == 421
    for path in ('/.env', '/uploads/private.txt', '/api/nonexistent', '/assets/missing.js'):
        assert request(path)[0] in (403, 404)
    evidence['host_and_private_path_rejection'] = True
    # Existing repository probe proves DB TLS, least-privilege identity, uploads,
    # malware scanner response, and returns only a public bundled video path.
    source = REPO / 'deploy/container/smoke.py'
    import importlib.util
    spec = importlib.util.spec_from_file_location('litblogs_container_smoke', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    probe = json.loads(compose('exec', '-T', 'app', 'python', '-c', module.RUNTIME_PROBE))
    assert re.fullmatch(r'/assets/[A-Za-z0-9_.-]+\.mp4', probe['video'])
    status, headers, body = request(probe['video'], headers={'Range': 'bytes=0-1023'})
    assert status == 206 and len(body) == 1024 and headers.get('content-range', '').startswith('bytes 0-1023/')
    evidence['database_tls_roles_upload_custody_scanner_and_video_range'] = True
    evidence['smtp_delivery_tested'] = False
    print(json.dumps(evidence, sort_keys=True))
    return evidence


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # noqa: BLE001 - response and subprocess errors may contain private values
        print('LitBlogs verification failed (' + type(error).__name__ + '); no sensitive response was logged.')
        raise SystemExit(1) from None
