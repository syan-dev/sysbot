"""Internet speed test — measures download throughput and latency.

Uses Cloudflare's public speed-test endpoints (``speed.cloudflare.com``) over
plain HTTPS via the standard library, so it needs no external binary and no pip
dependency — just outbound internet. Works on any OS.

Download speed is measured by fetching a fixed number of bytes and timing the
transfer; latency is the fastest of a few small round trips. The urllib calls
are blocking, so they run in a worker thread to avoid stalling the event loop.
"""
from __future__ import annotations

import asyncio
import time
import urllib.request

from lesysbot.mcp import tool

_DOWN_URL = "https://speed.cloudflare.com/__down?bytes={bytes}"
_PING_URL = "https://speed.cloudflare.com/__down?bytes=0"
_TIMEOUT = 30.0  # seconds per HTTP request
# Cloudflare 403s the default "Python-urllib/x.y" User-Agent, so present a normal one.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeSysBot/1.0; +speedtest)"}


def _open(url: str):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=_HEADERS), timeout=_TIMEOUT
    )


def _measure_latency_ms(samples: int = 4) -> float | None:
    """Fastest round trip (ms) of a few zero-byte requests, or None on failure."""
    best: float | None = None
    for _ in range(samples):
        try:
            start = time.perf_counter()
            with _open(_PING_URL) as resp:
                resp.read()
            elapsed = (time.perf_counter() - start) * 1000
        except OSError:
            continue
        if best is None or elapsed < best:
            best = elapsed
    return best


def _measure_download_mbps(size_bytes: int) -> tuple[float, float]:
    """Download ``size_bytes`` and return (megabits_per_second, seconds)."""
    url = _DOWN_URL.format(bytes=size_bytes)
    start = time.perf_counter()
    downloaded = 0
    with _open(url) as resp:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            downloaded += len(chunk)
    seconds = time.perf_counter() - start
    if seconds <= 0:
        return 0.0, 0.0
    mbps = (downloaded * 8) / seconds / 1_000_000
    return mbps, seconds


def _run(size_mb: float) -> str:
    size_bytes = max(1, int(size_mb * 1_000_000))
    latency = _measure_latency_ms()
    try:
        mbps, seconds = _measure_download_mbps(size_bytes)
    except OSError as exc:
        return f"Speed test failed — could not reach the test server: {exc}"

    lines = ["Internet speed test (via speed.cloudflare.com):"]
    if latency is not None:
        lines.append(f"  Latency:  {latency:.0f} ms")
    else:
        lines.append("  Latency:  unavailable")
    lines.append(f"  Download: {mbps:.1f} Mbps  ({size_mb:.0f} MB in {seconds:.1f}s)")
    return "\n".join(lines)


@tool(
    description=(
        "Measure the current internet connection speed — download throughput "
        "(Mbps) and latency (ms). Use for questions like 'how fast is my "
        "internet' or 'current internet speed'."
    ),
)
async def speedtest(size_mb: float = 10.0) -> str:
    """Run a download-speed test. ``size_mb`` is how many megabytes to fetch
    (larger = more accurate but slower; default 10 MB)."""
    return await asyncio.to_thread(_run, size_mb)
