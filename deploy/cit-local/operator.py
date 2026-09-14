#!/usr/bin/python3 -I
"""The installed, fixed-target LitBlogs operator command; no shell exports needed."""

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

STATE = Path('/home/litblogs/.local/state/cit-deploy')
REPO = Path('/home/litblogs/www/LitBlogs')
ENTRYPOINT = Path(__file__).absolute()
UNIT = 'litblogs-cit.service'
SERVICES = ('postgres', 'clamav', 'app', 'email', 'reconcile', 'web')
CLEAN_ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/root', 'LANG': 'C.UTF-8',
             'COMPOSE_PROGRESS': 'plain', 'COMPOSE_ANSI': 'never'}
MAX_LOG_BYTES = 2 * 1024 * 1024


class OperatorError(RuntimeError):
    """Only fixed messages may cross the operator command boundary."""


def validate_path(path, *, directory=False, modes):
    metadata = path.lstat()
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if (path.resolve() != path or not expected_type(metadata.st_mode)
            or metadata.st_uid != 0 or metadata.st_gid != 0
            or stat.S_IMODE(metadata.st_mode) not in modes
            or (not directory and metadata.st_nlink != 1)):
        raise OperatorError('LitBlogs private installation has unexpected ownership or permissions.')


def validate_paths():
    if os.name != 'posix' or os.geteuid() != 0:
        raise OperatorError('Run this command with sudo on the LitBlogs host.')
    validate_path(STATE, directory=True, modes={0o700})
    validate_path(STATE / 'logs', directory=True, modes={0o700})
    validate_path(STATE / '.env', modes={0o600})
    validate_path(STATE / 'compose.yaml', modes={0o600, 0o644})
    for name in ('service.py', 'lifecycle.py', 'verify.py'):
        validate_path(STATE / name, modes={0o600, 0o644})
    validate_path(ENTRYPOINT, modes={0o755})


def compose(*arguments):
    return ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'compose',
            '--project-name', 'litblogs-cit', '--project-directory', str(REPO),
            '--env-file', str(STATE / '.env'), '-f', str(REPO / 'docker-compose.yml'),
            '-f', str(STATE / 'compose.yaml'), *arguments]


def run(arguments, *, timeout=90, max_bytes=131072, tail=False):
    try:
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True,
                                check=False, timeout=timeout, env=CLEAN_ENV.copy(), cwd=str(STATE))
    except (OSError, subprocess.SubprocessError):
        raise OperatorError('LitBlogs command could not complete; inspect the private operation logs.') from None
    if result.returncode:
        raise OperatorError('LitBlogs command failed; inspect the private operation logs.')
    if len(result.stdout) > max_bytes and not tail:
        raise OperatorError('LitBlogs command returned an unexpected response size.')
    return result.stdout[-max_bytes:] if tail else result.stdout


def unit_state():
    value = run(['/usr/bin/systemctl', 'show', '--property=ActiveState', '--value', UNIT],
                timeout=20, max_bytes=32).decode('ascii').strip()
    if value not in {'active', 'inactive', 'failed', 'activating', 'deactivating', 'reloading', 'maintenance'}:
        raise OperatorError('LitBlogs unit state is unavailable.')
    return value


def recovery_blocked():
    # A dangling symlink must not bypass the recovery latch.
    path = STATE / 'update-blocked.json'
    return path.exists() or path.is_symlink()


def start():
    if recovery_blocked():
        raise OperatorError('LitBlogs recovery is blocked pending review of the last maintenance operation.')
    current = unit_state()
    if current == 'active':
        # RemainAfterExit means systemctl start alone would do nothing here.
        # The corrected installed helper starts validated exact container IDs.
        run(['/usr/bin/python3', '-E', '-s', str(STATE / 'service.py'), 'start'], timeout=1100)
    elif current in {'inactive', 'failed'}:
        run(['/usr/bin/systemctl', 'start', UNIT], timeout=1150)
        if unit_state() != 'active':
            raise OperatorError('LitBlogs startup did not activate its service; inspect the private operation logs.')
    else:
        raise OperatorError('LitBlogs service is changing state; retry after the current operation finishes.')
    print('LitBlogs start completed; all installed application services passed their health checks.')


def status():
    raw = run(compose('ps', '--all', '--format', 'json')).decode('utf-8').strip()
    rows = json.loads(raw) if raw.startswith('[') else [json.loads(line) for line in raw.splitlines()]
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise OperatorError('LitBlogs returned an unexpected container inventory.')
    counts = {name: {'containers': 0, 'running': 0, 'healthy': 0} for name in SERVICES}
    for row in rows:
        name = row.get('Service')
        if name not in counts:
            continue
        counts[name]['containers'] += 1
        counts[name]['running'] += row.get('State') == 'running'
        counts[name]['healthy'] += row.get('State') == 'running' and row.get('Health') == 'healthy'
    print(json.dumps({'unit': unit_state(), 'recovery_blocked': recovery_blocked(), 'services': counts},
                     sort_keys=True))


def logs():
    # Application logs may include private details. Keep them root-only, never
    # print them into a shared terminal transcript, and do not follow indefinitely.
    content = run(compose('logs', '--no-color', '--since', '24h', '--tail', '100', *SERVICES),
                  max_bytes=MAX_LOG_BYTES, tail=True)
    target = STATE / 'logs' / 'operator-latest.log'
    descriptor, temporary = tempfile.mkstemp(prefix='.operator-', dir=STATE / 'logs')
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(content[-MAX_LOG_BYTES:])
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Private LitBlogs log snapshot: ' + str(target))
    print('Startup diagnostics: ' + str(STATE / 'logs' / 'service-start.log'))


def check():
    run(['/usr/bin/python3', '-E', '-s', str(STATE / 'verify.py')], timeout=180)
    print('LitBlogs check passed: private HTTPS, application readiness, assets and runtime controls. No mail sent.')


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    operations = {'status': status, 'start': start, 'logs': logs, 'check': check}
    if not arguments or arguments == ['--help']:
        print('Usage: sudo litblogs {status|start|logs|check}')
        return
    if len(arguments) != 1 or arguments[0] not in operations:
        raise OperatorError('Use exactly one command: status, start, logs or check. Extra arguments are not accepted.')
    os.umask(0o077)
    validate_paths()
    operations[arguments[0]]()


if __name__ == '__main__':
    try:
        main()
    except OperatorError as error:
        print(str(error))
        raise SystemExit(1) from None
    except Exception:  # noqa: BLE001 - never echo private subprocess/configuration data
        print('LitBlogs command failed; check the private installation and operation logs.')
        raise SystemExit(1) from None
