"""Parse, edit and write M3U / M3U8 (extended) playlists.

Only the Python standard library is used, so the module works anywhere
Python 3.8+ runs (Windows, macOS, Linux, Raspberry Pi, Android/Termux).
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
USER_AGENT = "iptv-toolkit/1.0 (+https://github.com/smartvpro-tv/iptv-toolkit)"


@dataclass
class Entry:
    """One channel / item of a playlist."""

    url: str
    name: str = ""
    duration: str = "-1"
    attrs: Dict[str, str] = field(default_factory=dict)
    extra: List[str] = field(default_factory=list)  # e.g. #EXTVLCOPT lines

    @property
    def group(self) -> str:
        return self.attrs.get("group-title", "")

    @property
    def tvg_id(self) -> str:
        return self.attrs.get("tvg-id", "")

    @property
    def logo(self) -> str:
        return self.attrs.get("tvg-logo", "")

    def to_lines(self) -> List[str]:
        attrs = "".join(f' {k}="{v}"' for k, v in self.attrs.items())
        return [f"#EXTINF:{self.duration}{attrs},{self.name}", *self.extra, self.url]


@dataclass
class Playlist:
    entries: List[Entry] = field(default_factory=list)
    header_attrs: Dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    # ------------------------------------------------------------------ io
    def dumps(self) -> str:
        head = "#EXTM3U" + "".join(f' {k}="{v}"' for k, v in self.header_attrs.items())
        lines = [head]
        for e in self.entries:
            lines.extend(e.to_lines())
        return "\n".join(lines) + "\n"

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(self.dumps())

    # ------------------------------------------------------------- editing
    def groups(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for e in self.entries:
            key = e.group or "(no group)"
            out[key] = out.get(key, 0) + 1
        return out

    def dedupe(self) -> int:
        """Remove entries with an identical URL. Returns how many were removed."""
        seen = set()
        kept: List[Entry] = []
        for e in self.entries:
            if e.url in seen:
                continue
            seen.add(e.url)
            kept.append(e)
        removed = len(self.entries) - len(kept)
        self.entries = kept
        return removed

    def sort(self, key: str = "name") -> None:
        if key == "group":
            self.entries.sort(key=lambda e: (e.group.lower(), e.name.lower()))
        else:
            self.entries.sort(key=lambda e: e.name.lower())

    def filter(self, group: Optional[str] = None, name: Optional[str] = None,
               exclude: bool = False) -> "Playlist":
        rx = re.compile(name, re.IGNORECASE) if name else None

        def match(e: Entry) -> bool:
            ok = True
            if group is not None:
                ok = ok and e.group.lower() == group.lower()
            if rx is not None:
                ok = ok and bool(rx.search(e.name))
            return ok

        picked = [e for e in self.entries if match(e) != exclude]
        return Playlist(entries=picked, header_attrs=dict(self.header_attrs))

    def extend(self, other: "Playlist") -> None:
        self.entries.extend(other.entries)
        for k, v in other.header_attrs.items():
            self.header_attrs.setdefault(k, v)


def parse(text: str) -> Playlist:
    """Parse playlist text. Plain (non-extended) M3U files are accepted too."""
    pl = Playlist()
    pending: Optional[Entry] = None
    extra: List[str] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            pl.header_attrs.update(dict(ATTR_RE.findall(line)))
        elif line.startswith("#EXTINF:"):
            body = line[len("#EXTINF:"):]
            # the title is after the first comma that is not inside quotes
            in_q = False
            split_at = -1
            for i, ch in enumerate(body):
                if ch == '"':
                    in_q = not in_q
                elif ch == "," and not in_q:
                    split_at = i
                    break
            meta, title = (body, "") if split_at < 0 else (body[:split_at], body[split_at + 1:])
            duration = meta.split(" ", 1)[0] or "-1"
            pending = Entry(url="", name=title.strip(), duration=duration,
                            attrs=dict(ATTR_RE.findall(meta)))
            extra = []
        elif line.startswith("#"):
            if pending is not None:
                extra.append(line)
        else:
            entry = pending or Entry(url="", name=line.rsplit("/", 1)[-1])
            entry.url = line
            entry.extra = extra
            pl.entries.append(entry)
            pending, extra = None, []
    return pl


def load(source: str, timeout: float = 15.0) -> Playlist:
    """Load a playlist from a local path or an http(s) URL."""
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - user supplied
            text = resp.read().decode("utf-8", errors="replace")
    else:
        with open(source, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    return parse(text)


def merge(playlists: Iterable[Playlist], dedupe: bool = True) -> Playlist:
    out = Playlist()
    for pl in playlists:
        out.extend(pl)
    if dedupe:
        out.dedupe()
    return out
