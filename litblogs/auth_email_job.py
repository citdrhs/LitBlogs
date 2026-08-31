"""Run one reset batch and one verification batch in one isolated process."""

from __future__ import annotations

import sys
from collections.abc import Callable
from functools import partial

import auth_email_delivery
import email_verification_delivery
import password_reset_delivery

Dispatch = Callable[[], auth_email_delivery.AuthEmailDispatchOutcome]


def _dispatch_failed(dispatch: Dispatch) -> bool:
    try:
        outcome = dispatch()
    except Exception:
        return True
    return not (
        isinstance(outcome, auth_email_delivery.AuthEmailDispatchOutcome)
        and outcome
        in {
            auth_email_delivery.AuthEmailDispatchOutcome.EMPTY_QUEUE,
            auth_email_delivery.AuthEmailDispatchOutcome.COMPLETED,
        }
    )


def _run_both_dispatches(
    reset_dispatch: Dispatch,
    verification_dispatch: Dispatch,
) -> bool:
    failed = _dispatch_failed(reset_dispatch)
    if _dispatch_failed(verification_dispatch):
        failed = True
    return failed


def run(
    reset_dispatch: Dispatch | None = None,
    verification_dispatch: Dispatch | None = None,
) -> int:
    """Return one fixed status after attempting both available queues."""

    failed = False
    engine = None
    if (reset_dispatch is None) != (verification_dispatch is None):
        failed = True
    elif reset_dispatch is not None and verification_dispatch is not None:
        failed = _run_both_dispatches(
            reset_dispatch,
            verification_dispatch,
        )
    else:
        try:
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
                batch_size=100,
            )
            verification_once = partial(
                email_verification_delivery.dispatch_email_verification_batch_once,
                session_factory=session_factory,
                email_settings=email_settings,
                claim_timeout_seconds=(
                    settings.password_reset_claim_timeout_seconds
                ),
                batch_size=100,
            )
            failed = _run_both_dispatches(reset_once, verification_once)
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
