"""Fairly dispatch reset and verification email in one isolated process."""

from __future__ import annotations

import sys
from collections.abc import Callable
from functools import partial
from time import monotonic

import auth_email_delivery
import email_verification_delivery
import password_reset_delivery

Dispatch = Callable[[], auth_email_delivery.AuthEmailDispatchOutcome]
MonotonicClock = Callable[[], float]

AUTH_EMAIL_JOB_DEADLINE_SECONDS = 240.0
AUTH_EMAIL_JOB_PER_QUEUE_CAP = 25


def _dispatch_once(dispatch: Dispatch) -> tuple[bool, bool]:
    """Return ``(failed, still_active)`` without exposing failure details."""

    try:
        outcome = dispatch()
    except Exception:
        return True, False
    if not isinstance(outcome, auth_email_delivery.AuthEmailDispatchOutcome):
        return True, False
    if outcome is auth_email_delivery.AuthEmailDispatchOutcome.EMPTY_QUEUE:
        return False, False
    if outcome is auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED:
        return False, True
    return True, False


def _run_fair_dispatches(
    reset_dispatch: Dispatch,
    verification_dispatch: Dispatch,
    *,
    deadline: float,
    monotonic_clock: MonotonicClock,
) -> bool:
    """Alternate one delivery per queue, beginning with verification."""

    dispatches = (verification_dispatch, reset_dispatch)
    active = [True, True]
    attempts = [0, 0]
    failed = False

    while any(active):
        for index, dispatch in enumerate(dispatches):
            if not active[index]:
                continue
            if attempts[index] >= AUTH_EMAIL_JOB_PER_QUEUE_CAP:
                active[index] = False
                continue
            if monotonic_clock() >= deadline:
                return failed

            attempts[index] += 1
            dispatch_failed, still_active = _dispatch_once(dispatch)
            if dispatch_failed:
                failed = True
            active[index] = (
                still_active
                and attempts[index] < AUTH_EMAIL_JOB_PER_QUEUE_CAP
            )
    return failed


def run(
    reset_dispatch: Dispatch | None = None,
    verification_dispatch: Dispatch | None = None,
    *,
    monotonic_clock: MonotonicClock = monotonic,
) -> int:
    """Return one fixed status after fairly servicing both available queues."""

    failed = False
    engine = None
    try:
        deadline = monotonic_clock() + AUTH_EMAIL_JOB_DEADLINE_SECONDS
        if (reset_dispatch is None) != (verification_dispatch is None):
            failed = True
        elif reset_dispatch is not None and verification_dispatch is not None:
            failed = _run_fair_dispatches(
                reset_dispatch,
                verification_dispatch,
                deadline=deadline,
                monotonic_clock=monotonic_clock,
            )
        else:
            settings = auth_email_delivery.load_auth_email_worker_settings()
            engine = auth_email_delivery.create_auth_email_engine(settings)
            auth_email_delivery.check_auth_email_database_readiness(engine)
            session_factory = (
                auth_email_delivery.create_auth_email_session_factory(engine)
            )
            email_settings = (
                auth_email_delivery.auth_email_settings_from_worker(settings)
            )
            reset_once = partial(
                password_reset_delivery.dispatch_password_reset_batch_once,
                session_factory=session_factory,
                email_settings=email_settings,
                claim_timeout_seconds=(
                    settings.password_reset_claim_timeout_seconds
                ),
                batch_size=1,
            )
            verification_once = partial(
                email_verification_delivery.dispatch_email_verification_batch_once,
                session_factory=session_factory,
                email_settings=email_settings,
                claim_timeout_seconds=(
                    settings.password_reset_claim_timeout_seconds
                ),
                batch_size=1,
            )
            failed = _run_fair_dispatches(
                reset_once,
                verification_once,
                deadline=deadline,
                monotonic_clock=monotonic_clock,
            )
    except Exception:
        failed = True
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                failed = True

    if failed:
        print("auth-email-job: failed", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
