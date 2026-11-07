"""Measure the real throughput you get from a stream (HLS or plain)."""

from __future__ import annotations

import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .m3u import USER_AGENT

# Rough bandwidth needed for smooth playback (Mbps). Keep a 1.5x margin on top.
QUALITY_NEEDS: List[Tuple[str, float]] = [
    ("SD (480p)", 3.0),
    ("HD (720p)", 5.0),
    ("Full HD (1080p)", 10.0),
    ("4K (2160p)", 25.0),
]
HEADROOM = 1.5


@dataclass
class SpeedResult:
    url: str
    bytes_read: int
    seconds: float
    segments: int = 0

    @property
    def mbps(self) -> float:
        return 0.0 if self.seconds <= 0 else self.bytes_read * 8 / self.seconds / 1_000_000

    def best_quality(self) -> Optional[str]:
        best = None
        for label, need in QUALITY_NEEDS:
            if self.mbps >= need * HEADROOM:
                best = label
        return best


def _get(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)  # nosec - user supplied


def _media_segments(url: str, text: str, timeout: float, depth: int = 0) -> List[str]:
    """Return absolute segment URLs, following a master playlist to its best variant."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    variants: List[Tuple[int, str]] = []
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF") and i + 1 < len(lines):
            bw = 0
            for part in line.split(","):
                if "BANDWIDTH=" in part and "AVERAGE" not in part:
                    try:
                        bw = int(part.split("=", 1)[1])
                    except ValueError:
                        pass
            variants.append((bw, urllib.parse.urljoin(url, lines[i + 1])))
    if variants and depth < 2:
        best_url = max(variants)[1]
        with _get(best_url, timeout) as resp:
            sub = resp.read().decode("utf-8", errors="replace")
        return _media_segments(best_url, sub, timeout, depth + 1)
    return [urllib.parse.urljoin(url, l) for l in lines if not l.startswith("#")]


def measure(url: str, seconds: float = 10.0, timeout: float = 10.0) -> SpeedResult:
    """Download from ``url`` for about ``seconds`` and return the throughput."""
    deadline = time.perf_counter() + seconds
    total = 0
    segments = 0
    start = time.perf_counter()
    with _get(url, timeout) as resp:
        first = resp.read(65536)
        ctype = resp.headers.get("Content-Type", "").lower()
        is_hls = first.lstrip().startswith(b"#EXTM3U") or "mpegurl" in ctype
        if not is_hls:
            total += len(first)
            while time.perf_counter() < deadline:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
            return SpeedResult(url, total, time.perf_counter() - start)
        text = (first + resp.read()).decode("utf-8", errors="replace")

    start = time.perf_counter()  # do not count playlist download time
    for seg in _media_segments(url, text, timeout):
        if time.perf_counter() >= deadline:
            break
        with _get(seg, timeout) as resp:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
        segments += 1
    return SpeedResult(url, total, time.perf_counter() - start, segments)
