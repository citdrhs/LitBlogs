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


def load_settings():
    """Read only nonsecret routing values; never trust a URL as a connection target."""
    values = {}
    names = {'LITBLOGS_ORIGIN', 'LITBLOGS_BASE_PATH', 'LITBLOGS_GATEWAY_HOST'}
    for line in (STATE / '.env').read_text().splitlines():
        key = line.partition('=')[0]
        if key not in names:
            continue
        match = re.fullmatch(r"[A-Z_]+=(?:'([^'\r\n]*)'|([^'\s#]*))", line)
        if match is None or key in values:
            raise ValueError('Invalid routing setting')
        values[key] = match[1] if match[1] is not None else match[2]
    origin = values.get('LITBLOGS_ORIGIN', f'https://{HOST}:{PORT}')
    match = re.fullmatch(r'https://([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)(?::([0-9]{1,5}))?', origin)
    if match is None or (match[2] and not 1 <= int(match[2]) <= 65535):
        raise ValueError('Invalid HTTPS origin')
    host = origin.removeprefix('https://').lower()
    if values.get('LITBLOGS_GATEWAY_HOST', host).lower() != host:
        raise ValueError('Gateway Host must match the configured origin')
    base = values.get('LITBLOGS_BASE_PATH', '')
    if len(base) > 256 or (base and re.fullmatch(r'(?:/[A-Za-z0-9][A-Za-z0-9_-]*)+', base) is None):
        raise ValueError('Invalid public base path')
    return {'origin': origin.lower(), 'host': host, 'base_path': base, 'cookie_path': base + '/'}


def request(path, *, headers=None, method='GET', body=None, settings=None):
    settings = settings if settings is not None else load_settings()
    context = ssl.create_default_context(cafile=str(STATE / 'https/server.crt'))
    connection = http.client.HTTPSConnection(HOST, PORT, timeout=20, context=context)
    connection._create_connection = lambda *args, **kwargs: socket.create_connection(('127.0.0.1', PORT), timeout=20)
    try:
        connection.request(method, path, body=body, headers={'Host': settings['host'], **(headers or {})})
        response = connection.getresponse()
        data = response.read(12 * 1024 * 1024)
        return response.status, {k.lower(): v for k, v in response.getheaders()}, data
    finally:
        connection.close()


def runtime_cookies(config, settings):
    """Use runtime names while enforcing host-only secure cookie conventions."""
    prefix = '__Secure-' if settings['base_path'] else '__Host-'
    session = config.get('session_cookie_name', '__Host-litblogs-session')
    csrf = config.get('csrf_cookie_name', '__Host-litblogs-csrf')
    path = config.get('cookie_path', '/')
    for name in (session, csrf):
        if not isinstance(name, str) or re.fullmatch(prefix + r'[A-Za-z0-9_.-]{1,128}', name) is None:
            raise ValueError('Unexpected secure cookie name')
    if session == csrf or path != settings['cookie_path']:
        raise ValueError('Unexpected cookie scope')
    return session, csrf, path


def compose(*args):
    result = subprocess.run([
        '/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'compose', '--project-name', 'litblogs-cit',
        '--project-directory', str(REPO), '--env-file', str(STATE / '.env'),
        '-f', str(REPO / 'docker-compose.yml'), '-f', str(STATE / 'compose.yaml'), *args,
    ], check=True, capture_output=True, timeout=90,
       env={'PATH': '/usr/bin:/bin', 'HOME': '/root', 'LANG': 'C.UTF-8'})
    return result.stdout


def main():
    settings = load_settings()
    evidence = {}
    status, headers, body = request('/api/health/ready', settings=settings)
    assert status == 200 and json.loads(body)['status'] == 'ready'
    evidence['https_certificate_hostname_and_readiness'] = True
    status, _, body = request('/api/runtime-config', settings=settings)
    assert status == 200
    config = json.loads(body)
    assert config.get('local_password_registration_enabled') is True
    assert config.get('google_oauth_enabled') is False
    assert config.get('microsoft_oauth_enabled') is False
    runtime_cookies(config, settings)
    evidence['password_registration_and_disabled_oauth'] = True
    assets = set()
    for route in ('/', '/index.html', '/help', '/sign-in'):
        status, headers, body = request(route, settings=settings)
        assert status == 200 and b'<html' in body.lower()
        assert 'no-store' in headers.get('cache-control', '')
        assert headers.get('x-content-type-options') == 'nosniff'
        assert 'content-security-policy' in headers
        urls = re.findall(r'''(?:src|href)=["']([^"']+)["']''', body.decode('utf-8'))
        for url in urls:
            if '/assets/' not in url:
                continue
            if re.fullmatch(re.escape(settings['base_path']) + r'/assets/[A-Za-z0-9_.-]+', url) is None:
                raise ValueError('Frontend asset prefix does not match deployment')
            assets.add(url[len(settings['base_path']):])
    evidence['frontend_routes_cache_and_security_headers'] = True
    assert any(path.endswith('.js') for path in assets)
    for path in sorted(assets):
        if not path.endswith(('.js', '.css')):
            continue
        status, headers, body = request(path, settings=settings)
        assert status == 200 and body
        expected_type = 'javascript' if path.endswith('.js') else 'text/css'
        assert expected_type in headers.get('content-type', '')
    evidence['frontend_asset_prefix_and_delivery'] = True
    assert request('/api/health/ready', headers={'Host': 'unapproved.invalid'}, settings=settings)[0] == 421
    for path in ('/.env', '/uploads/private.txt', '/api/nonexistent', '/assets/missing.js'):
        assert request(path, settings=settings)[0] in (403, 404)
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
    status, headers, body = request(probe['video'], headers={'Range': 'bytes=0-1023'}, settings=settings)
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
