"""Start or stop only the installed LitBlogs CIT Compose project."""

import argparse
import os
from pathlib import Path

import lifecycle

STATE = Path('/home/litblogs/.local/state/cit-deploy')
START_SERVICES = ('postgres', 'clamav', 'app', 'email', 'reconcile', 'web')


class ServiceBusyError(RuntimeError):
    """Fixed diagnostic when a manually invoked operation already owns the lock."""


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('start', 'stop'))
    args = parser.parse_args()
    os.umask(0o077)
    if os.geteuid() != 0:
        raise RuntimeError('LitBlogs service action requires root')
    with (STATE / 'operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ServiceBusyError('LitBlogs operation lock is busy; retry after the active operation finishes') from None
        with (STATE / 'logs' / f'service-{args.operation}.log').open('a', encoding='utf-8') as log:
            os.chmod(log.name, 0o600)
            log.write('Existing-container ' + args.operation + ' requested.\n')
            log.flush()
            try:
                if args.operation == 'start' and (STATE / 'update-blocked.json').exists():
                    raise RuntimeError('Pending update recovery requires operator review')
                # Initial installation creates containers separately. Preserve
                # pinned images and replicas without invoking migrations.
                original = lifecycle.capture()
                identifiers = lifecycle.selected_ids(original, START_SERVICES)
                if args.operation == 'start':
                    lifecycle.start_existing(original, identifiers)
                else:
                    lifecycle.stop_existing(original, identifiers)
            except lifecycle.LifecycleError as error:
                log.write('Existing-container operation failed: ' + str(error) + '\n')
                raise
            except Exception:
                log.write('Existing-container operation failed; sensitive details suppressed.\n')
                raise
            log.write('Existing-container ' + args.operation + ' completed.\n')
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
