"""Allowlisted exception diagnostics shared by bot, HTTP and background jobs."""

import re
import traceback
from pathlib import Path

from sqlalchemy.exc import DBAPIError


def exception_diagnostic(exception: BaseException) -> str:
    """Only trusted diagnostic fields: arbitrary error text may repeat user input."""
    if not isinstance(exception, DBAPIError):
        return type(exception).__name__
    sqlstate = getattr(exception.orig, "sqlstate", None)
    if not isinstance(sqlstate, str) or not re.fullmatch(r"[A-Z0-9]{5}", sqlstate):
        sqlstate = "unknown"
    return f"{type(exception).__name__} (sqlstate={sqlstate})"


def safe_exception_trace(exception: BaseException) -> str:
    # Exception messages, causes and source lines can contain user input for any
    # error class. Keep code locations without arbitrary text, arguments or locals.
    positions = " -> ".join(
        f"{Path(frame.f_code.co_filename).name}:{line}:{frame.f_code.co_name}"
        for frame, line in traceback.walk_tb(exception.__traceback__)
    )
    return f"{exception_diagnostic(exception)}; stack={positions}"


