"""Date & time — current date, time, and timezone info.

Pure-Python (stdlib only), so it runs on every OS with no extra dependencies.
"""
from datetime import datetime, timezone as _tz

from lesysbot.mcp import tool


@tool(description="Get the current date and time, optionally for an IANA timezone like Europe/London")
async def get_datetime(timezone: str = "") -> str:
    """Report the current local date/time, or the time in the given timezone."""
    if timezone:
        try:
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo(timezone))
        except Exception:
            return (
                f"Unknown timezone: {timezone!r} — use an IANA name like "
                "'Europe/London' or 'Asia/Ho_Chi_Minh'"
            )
    else:
        now = datetime.now().astimezone()

    utc_now = datetime.now(_tz.utc)
    return (
        f"Date: {now:%A, %d %B %Y}\n"
        f"Time: {now:%H:%M:%S} ({now.tzname()}, UTC{now:%z})\n"
        f"UTC:  {utc_now:%Y-%m-%d %H:%M:%S}"
    )
