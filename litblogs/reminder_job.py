import sys

from main import _dispatch_assignment_push_reminders_once


def main() -> int:
    return 0 if _dispatch_assignment_push_reminders_once() else 1


if __name__ == "__main__":
    sys.exit(main())
