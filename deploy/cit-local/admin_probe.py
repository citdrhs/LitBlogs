"""Verify an existing administrator session using a private credential file."""

import argparse
import http.client
import json
import socket
import ssl
from http.cookies import SimpleCookie
from pathlib import Path

from verify import HOST, PORT, STATE, load_settings, runtime_cookies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', type=Path, default=STATE / 'bootstrap-admin.json')
    args = parser.parse_args()
    credentials = json.loads(args.credentials.read_text())
    settings = load_settings()
    cookies = SimpleCookie()
    context = ssl.create_default_context(cafile=str(STATE / 'https/server.crt'))

    def call(method, path, body=None, *, csrf=False):
        connection = http.client.HTTPSConnection(HOST, PORT, timeout=20, context=context)
        connection._create_connection = lambda *a, **k: socket.create_connection(('127.0.0.1', PORT), timeout=20)
        headers = {'Host': settings['host'], 'Origin': settings['origin'], 'Content-Type': 'application/json'}
        if cookies:
            headers['Cookie'] = '; '.join(f'{key}={item.value}' for key, item in cookies.items())
        if csrf:
            headers['X-CSRF-Token'] = cookies[csrf_name].value
        try:
            connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
            response = connection.getresponse()
            output = response.read(1024 * 1024)
            for key, value in response.getheaders():
                if key.lower() == 'set-cookie':
                    cookies.load(value)
            return response.status, json.loads(output) if output else None
        finally:
            connection.close()

    status, config = call('GET', '/api/runtime-config')
    assert status == 200
    session_name, csrf_name, cookie_path = runtime_cookies(config, settings)
    assert call('GET', '/api/auth/session')[0] == 401
    status, account = call('POST', '/api/auth/login', {key: credentials[key] for key in ('email', 'password')})
    assert status == 200 and account['role'] == 'ADMIN' and account['is_admin'] is True
    assert account['username'] == credentials['username']
    for key in (session_name, csrf_name):
        assert cookies[key]['secure'] and cookies[key]['path'] == cookie_path and not cookies[key]['domain']
    assert cookies[session_name]['httponly']
    assert not cookies[csrf_name]['httponly']
    assert call('GET', '/api/auth/session')[0] == 200
    assert call('POST', '/api/auth/logout')[0] == 403
    assert call('POST', '/api/auth/logout', csrf=True)[0] == 204
    assert not cookies[session_name].value
    assert call('GET', '/api/auth/session')[0] == 401
    evidence = {'admin_login': True, 'admin_role': True, 'secure_host_cookies': True,
                'csrf_rejection': True, 'logout': True, 'email_delivery_attempted': False}
    (STATE / 'admin-verification.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # noqa: BLE001 - keep credentials behind the sanitized CLI boundary
        print('Administrator verification failed (' + type(error).__name__ + '); credentials and session values withheld.')
        raise SystemExit(1) from None
