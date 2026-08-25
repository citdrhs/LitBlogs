"""Reconcile upload registry and object storage outside the web process."""

from __future__ import annotations

import sys
from collections.abc import Callable


def _default_reconcile() -> bool:
    from main import _reconcile_upload_assets_once

    return _reconcile_upload_assets_once()


def run(reconcile: Callable[[], bool] | None = None) -> int:
    """Return nonzero when reconciliation did not commit successfully."""

    try:
        completed = (reconcile or _default_reconcile)()
    except Exception:
        completed = False
    if completed is not True:
        print("upload-reconciliation-job: failed", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
