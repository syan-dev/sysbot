"""GPU temperature — reads NVIDIA GPU temps via nvidia-smi.

Declared for Linux/Windows and gated on `nvidia-smi` being on PATH, so on a
machine without an NVIDIA driver the tool registers but explains itself instead
of failing. Call it in chat or directly with `/gpu_temp`.
"""
import asyncio

from lesysbot.mcp import tool


@tool(
    description="Report current NVIDIA GPU temperature(s) in °C via nvidia-smi",
    platforms=["linux", "windows"],
    requires=["nvidia-smi"],
)
async def gpu_temp() -> str:
    """Return each GPU's temperature, e.g. 'GPU0: 47°C, GPU1: 51°C'."""
    proc = await asyncio.create_subprocess_exec(
        "nvidia-smi",
        "--query-gpu=index,temperature.gpu",
        "--format=csv,noheader,nounits",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return f"nvidia-smi failed: {stderr.decode().strip() or 'unknown error'}"

    readings = []
    for line in stdout.decode().splitlines():
        line = line.strip()
        if not line:
            continue
        index, _, temp = line.partition(",")
        readings.append(f"GPU{index.strip()}: {temp.strip()}°C")

    return ", ".join(readings) if readings else "No GPUs reported."
