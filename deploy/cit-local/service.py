"""Start or stop only the installed LitBlogs CIT Compose project."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

STATE = Path('/home/litblogs/.local/state/cit-deploy')
REPO = Path('/home/litblogs/www/LitBlogs')
PREFIX = ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'compose',
          '--project-name', 'litblogs-cit', '--project-directory', str(REPO),
          '--env-file', str(STATE / '.env'), '-f', str(REPO / 'docker-compose.yml'),
          '-f', str(STATE / 'compose.yaml')]
START_SERVICES = ('postgres', 'clamav', 'app', 'email', 'reconcile', 'web')


class ServiceBusyError(RuntimeError):
    """Fixed diagnostic when a manually invoked operation already owns the lock."""


def services_ready(raw):
    """Every singleton and every existing app replica must be healthy."""
    try:
        if len(raw) > 131072:
            return False
        text = raw.decode('utf-8').strip()
        rows = json.loads(text) if text.startswith('[') else [json.loads(line) for line in text.splitlines()]
        counts = {name: 0 for name in START_SERVICES}
        for row in rows:
            name = row.get('Service')
            if name not in counts:
                continue
            if row.get('State') != 'running' or row.get('Health') != 'healthy':
                return False
            counts[name] += 1
        return 1 <= counts['app'] <= 3 and all(counts[name] == 1 for name in START_SERVICES if name != 'app')
    except (AttributeError, TypeError, ValueError, UnicodeError):
        return False


def wait_ready(env, log, *, timeout=900):
    # Compose versions available locally do not implement `start --wait`.
    # Poll state only; never `up`, recreate containers, or run dependencies here.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run([*PREFIX, 'ps', '--all', '--format', 'json'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=log, env=env, timeout=min(20, max(1, deadline - time.monotonic())), check=False)
        if result.returncode == 0 and services_ready(result.stdout):
            return
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise RuntimeError('Existing LitBlogs services did not become healthy before the startup deadline')


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('start', 'stop'))
    args = parser.parse_args()
    os.umask(0o077)
    if os.geteuid() != 0:
        raise RuntimeError('LitBlogs service action requires root')
    env = {'PATH': '/usr/bin:/bin', 'HOME': '/root', 'LANG': 'C.UTF-8',
           'COMPOSE_PROGRESS': 'plain', 'COMPOSE_ANSI': 'never'}
    with (STATE / 'operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ServiceBusyError('LitBlogs operation lock is busy; retry after the active operation finishes') from None
        if args.operation == 'start':
            if (STATE / 'update-blocked.json').exists():
                raise RuntimeError('Pending update recovery requires operator review')
            # Initial installation creates containers separately. Boot preserves
            # their pinned images and replica count and never invokes migrations.
            command = ['start', *START_SERVICES]
        else:
            command = ['stop', '--timeout', '60', 'web', 'app', 'email', 'reconcile', 'clamav', 'postgres']
        with (STATE / 'logs' / f'service-{args.operation}.log').open('ab') as log:
            subprocess.run([*PREFIX, *command], check=True, timeout=150, env=env,
                           stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            if args.operation == 'start':
                wait_ready(env, log)
        print('LitBlogs ' + args.operation + ' completed.')


if __name__ == '__main__':
    try:
        main()
    except ServiceBusyError:
        print('LitBlogs operation lock is busy; retry after the active operation finishes.')
        raise SystemExit(1) from None
    except Exception as error:  # noqa: BLE001 - keep deployment errors behind the sanitized CLI boundary
        print('LitBlogs service action failed (' + type(error).__name__ + '); inspect private logs.')
        raise SystemExit(1) from None
