"""Run one bounded password-reset delivery batch outside the web process."""

from __future__ import annotations

import sys
from collections.abc import Callable

import password_reset_delivery


def _default_dispatch() -> password_reset_delivery.PasswordResetDispatchOutcome:
    return password_reset_delivery.dispatch_password_reset_emails_once()


def run(
    dispatch: Callable[[], password_reset_delivery.PasswordResetDispatchOutcome]
    | None = None,
) -> int:
    """Return a systemd-friendly status without reflecting delivery secrets."""

    try:
        outcome = (dispatch or _default_dispatch)()
    except Exception:
        print("password-reset-job: failed", file=sys.stderr)
        return 1
    if not isinstance(
        outcome,
        password_reset_delivery.PasswordResetDispatchOutcome,
    ) or outcome not in {
        password_reset_delivery.PasswordResetDispatchOutcome.EMPTY_QUEUE,
        password_reset_delivery.PasswordResetDispatchOutcome.COMPLETED,
    }:
        print("password-reset-job: failed", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
