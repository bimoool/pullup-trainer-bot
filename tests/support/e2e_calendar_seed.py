"""Invoke the existing seed CLI; reserve the calendar adapter for exact pairs."""

import asyncio
import sys

from tests.support.plan_calendar import (
    CALENDAR_SCENARIOS,
    frozen_datetime,
    guarded_calendar_environment,
    install_plan_calendar,
)


def main():
    at = guarded_calendar_environment()
    from scripts import e2e_seed

    if len(sys.argv) == 3 and CALENDAR_SCENARIOS.get(int(sys.argv[2])) == sys.argv[1]:
        install_plan_calendar(at, CALENDAR_SCENARIOS)
        e2e_seed.datetime = frozen_datetime(at)
    elif len(sys.argv) == 3 and int(sys.argv[2]) in CALENDAR_SCENARIOS:
        raise RuntimeError("calendar fixture scenario mismatch")
    asyncio.run(e2e_seed.main())


if __name__ == "__main__":
    main()
