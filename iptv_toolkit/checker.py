"""Check whether the streams of a playlist answer, and how fast."""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, List, Optional

from .m3u import USER_AGENT, Entry

OK, DEAD, TIMEOUT, ERROR = "OK", "DEAD", "TIMEOUT", "ERROR"


@dataclass
class Result:
    name: str
    url: str
    status: str
    http_code: Optional[int] = None
    latency_ms: Optional[int] = None
    content_type: str = ""
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "http_code": self.http_code,
            "latency_ms": self.latency_ms,
            "content_type": self.content_type,
            "detail": self.detail,
        }


def check_url(url: str, name: str = "", timeout: float = 8.0,
              user_agent: str = USER_AGENT) -> Result:
    """Open the URL, read the first bytes and classify the answer.

    * ``OK``      - the server answered 2xx and sent data
                    (for HLS, the body starts with ``#EXTM3U``)
    * ``DEAD``    - 4xx/5xx, empty body, or not a playlist when one was expected
    * ``TIMEOUT`` - no answer within ``timeout`` seconds
    * ``ERROR``   - DNS, TLS or connection error
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent,
                                               "Range": "bytes=0-4095"})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - user supplied
            chunk = resp.read(4096)
            latency = int((time.perf_counter() - start) * 1000)
            ctype = resp.headers.get("Content-Type", "")
            code = resp.status
    except urllib.error.HTTPError as exc:
        return Result(name, url, DEAD, exc.code,
                      int((time.perf_counter() - start) * 1000), detail=str(exc.reason))
    except (socket.timeout, TimeoutError):
        return Result(name, url, TIMEOUT, detail=f"no answer in {timeout:g}s")
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return Result(name, url, TIMEOUT, detail=f"no answer in {timeout:g}s")
        return Result(name, url, ERROR, detail=str(reason))
    except Exception as exc:  # pragma: no cover - defensive
        return Result(name, url, ERROR, detail=str(exc))

    if not chunk:
        return Result(name, url, DEAD, code, latency, ctype, "empty response")
    looks_hls = url.split("?", 1)[0].lower().endswith(".m3u8") or "mpegurl" in ctype.lower()
    if looks_hls and not chunk.lstrip().startswith(b"#EXTM3U"):
        return Result(name, url, DEAD, code, latency, ctype, "HLS URL did not return a playlist")
    return Result(name, url, OK, code, latency, ctype)


def check_entries(entries: List[Entry], timeout: float = 8.0, workers: int = 10,
                  on_result: Optional[Callable[[Result], None]] = None) -> List[Result]:
    """Check many entries in parallel. Results keep the playlist order."""
    def job(e: Entry) -> Result:
        res = check_url(e.url, e.name, timeout=timeout)
        if on_result:
            on_result(res)
        return res

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(job, entries))
