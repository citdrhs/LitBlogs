"""Exercise the actual public or loopback canary route without sending email."""

import argparse
import http.client
import json
import re
import socket
import ssl
from http.cookies import SimpleCookie
from pathlib import Path

STATE = Path('/home/litblogs/.local/state/cit-deploy')
HOST = 'drhscit.org'
BASE = '/dren'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canary-port', type=int)
    args = parser.parse_args()
    if args.canary_port is not None and args.canary_port != 18444:
        raise ValueError('Only the reserved loopback canary port is supported')
    credentials = json.loads((STATE / 'bootstrap-admin.json').read_text())
    cookies = SimpleCookie()
    evidence = {}

    def call(method, path, body=None, *, csrf=False, headers=None):
        connection = http.client.HTTPSConnection(HOST, 443, timeout=25, context=ssl.create_default_context())
        if args.canary_port:
            connection._create_connection = lambda *a, **k: socket.create_connection(('127.0.0.1', args.canary_port), timeout=25)
        request_headers = {'Host': HOST, 'Origin': f'https://{HOST}', 'Content-Type': 'application/json'}
        applicable = {key: value for key, value in cookies.items()
                      if path.startswith(value['path']) and value.value}
        if applicable:
            request_headers['Cookie'] = '; '.join(f'{key}={value.value}' for key, value in applicable.items())
        if csrf:
            request_headers['X-CSRF-Token'] = applicable['__Secure-litblogs-csrf'].value
        request_headers.update(headers or {})
        try:
            connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=request_headers)
            response = connection.getresponse()
            output = response.read(12 * 1024 * 1024)
            for key, value in response.getheaders():
                if key.lower() == 'set-cookie':
                    cookies.load(value)
            return response.status, {k.lower(): v for k, v in response.getheaders()}, output
        finally:
            connection.close()

    status, headers, _ = call('GET', BASE)
    assert status == 308 and headers['location'] == f'https://{HOST}{BASE}/'
    evidence['canonical_lowercase_route'] = True
    pages = []
    for route in ('/', '/help', '/sign-in'):
        status, headers, body = call('GET', BASE + route)
        assert status == 200 and b'<html' in body.lower()
        assert 'no-store' in headers.get('cache-control', '')
        assert headers.get('x-content-type-options') == 'nosniff'
        assert 'content-security-policy' in headers
        pages.append(body.decode())
    assets = set(re.findall(r'(?:src|href)="(/dren/assets/[^"<>]+)"', pages[0]))
    assert assets and any(path.endswith('.js') for path in assets)
    video_paths = set()
    pending = sorted(assets)
    visited = set()
    while pending:
        path = pending.pop(0)
        if path in visited:
            continue
        assert len(visited) < 32, 'Unexpected production module graph size'
        visited.add(path)
        status, headers, body = call('GET', path)
        assert status == 200 and body and b'<html' not in body[:100].lower()
        video_paths.update(re.findall(rb'/dren/assets/[A-Za-z0-9_.-]+\.mp4', body))
        if path.endswith('.js'):
            # Vite's small entry imports the actual application as another chunk.
            dependencies = re.findall(rb'["\'](?:/dren/assets/|\./)([A-Za-z0-9_.-]+\.js)["\']', body)
            pending.extend(BASE + '/assets/' + value.decode() for value in dependencies)
    assert video_paths, 'The production bundle must reference the prefixed welcome video'
    status, headers, body = call('GET', sorted(video_paths)[0].decode(), headers={'Range': 'bytes=0-1023'})
    assert status == 206 and len(body) == 1024
    assert headers.get('content-range', '').startswith('bytes 0-1023/')
    evidence['pages_assets_security_headers_and_video_range'] = True
    for route in ('/.env', '/uploads/private.txt', '/api/nonexistent', '/assets/missing.js'):
        assert call('GET', BASE + route)[0] in (403, 404)
    assert call('GET', BASE + '/api/health/ready', headers={'Host': 'unapproved.invalid'})[0] == 421
    status, _, body = call('GET', BASE + '/api/health/ready')
    assert status == 200 and json.loads(body)['status'] == 'ready'
    status, _, body = call('GET', BASE + '/api/runtime-config')
    assert status == 200
    config = json.loads(body)
    assert config['cookie_path'] == BASE + '/'
    assert config['session_cookie_name'] == '__Secure-litblogs-session'
    assert config['csrf_cookie_name'] == '__Secure-litblogs-csrf'
    evidence['readiness_runtime_contract_and_private_path_rejection'] = True
    assert call('GET', BASE + '/api/auth/session')[0] == 401
    status, _, body = call('POST', BASE + '/api/auth/login', {key: credentials[key] for key in ('email', 'password')})
    account = json.loads(body)
    assert status == 200 and account['role'] == 'ADMIN' and account['is_admin'] is True
    assert account['username'] == credentials['username']
    for key in ('__Secure-litblogs-session', '__Secure-litblogs-csrf'):
        cookie = cookies[key]
        assert cookie['secure'] and cookie['path'] == BASE + '/' and not cookie['domain']
        assert cookie['samesite'].lower() == 'strict'
    assert cookies['__Secure-litblogs-session']['httponly']
    assert not cookies['__Secure-litblogs-csrf']['httponly']
    assert call('GET', BASE + '/api/auth/session')[0] == 200
    assert call('POST', BASE + '/api/auth/logout')[0] == 403
    assert call('POST', BASE + '/api/auth/logout', csrf=True)[0] == 204
    assert not cookies['__Secure-litblogs-session'].value
    assert cookies['__Secure-litblogs-session']['path'] == BASE + '/'
    assert call('GET', BASE + '/api/auth/session')[0] == 401
    evidence['administrator_login_cookie_path_csrf_and_logout'] = True
    evidence['smtp_delivery_tested'] = False
    evidence['canary'] = bool(args.canary_port)
    print(json.dumps(evidence, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # noqa: BLE001 - never expose responses or credentials
        print('Public-route verification failed (' + type(error).__name__ + '); private values withheld.')
        raise SystemExit(1) from None
