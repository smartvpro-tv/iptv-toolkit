"""Command line interface: ``iptv-toolkit <command> ...``"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import List, Optional

from . import __version__
from .checker import OK, check_entries
from .m3u import load, merge
from .speed import HEADROOM, QUALITY_NEEDS, measure

DOCS = "https://smartvpro-tv.github.io/iptv-toolkit/"


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")


def cmd_info(args) -> int:
    pl = load(args.playlist)
    urls = [e.url for e in pl]
    dupes = len(urls) - len(set(urls))
    no_id = sum(1 for e in pl if not e.tvg_id)
    no_logo = sum(1 for e in pl if not e.logo)
    groups = pl.groups()
    if args.json:
        _out(json.dumps({"entries": len(pl), "groups": groups, "duplicates": dupes,
                         "missing_tvg_id": no_id, "missing_logo": no_logo,
                         "epg": pl.header_attrs.get("url-tvg") or pl.header_attrs.get("x-tvg-url", "")},
                        indent=2, ensure_ascii=False))
        return 0
    _out(f"Entries        : {len(pl)}")
    _out(f"Groups         : {len(groups)}")
    _out(f"Duplicate URLs : {dupes}")
    _out(f"No tvg-id      : {no_id}")
    _out(f"No logo        : {no_logo}")
    epg = pl.header_attrs.get("url-tvg") or pl.header_attrs.get("x-tvg-url")
    _out(f"EPG source     : {epg or '-'}")
    if groups:
        _out("")
        width = max(len(g) for g in groups)
        for g, n in sorted(groups.items(), key=lambda kv: (-kv[1], kv[0])):
            _out(f"  {g.ljust(width)}  {n}")
    return 0


def cmd_check(args) -> int:
    pl = load(args.playlist)
    entries = pl.entries[: args.limit] if args.limit else pl.entries
    if not entries:
        _out("Playlist is empty.")
        return 1

    done = [0]

    def progress(_res):
        done[0] += 1
        if not args.quiet and sys.stderr.isatty():
            sys.stderr.write(f"\rchecked {done[0]}/{len(entries)}")
            sys.stderr.flush()

    results = check_entries(entries, timeout=args.timeout, workers=args.workers,
                            on_result=progress)
    if not args.quiet and sys.stderr.isatty():
        sys.stderr.write("\n")

    rows = [r.as_dict() for r in results]
    if args.format == "json":
        text = json.dumps(rows, indent=2, ensure_ascii=False)
    elif args.format == "csv":
        import io
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        text = buf.getvalue().rstrip("\n")
    else:
        name_w = min(40, max(4, *(len(r.name) for r in results)))
        lines = [f"{'STATUS':8} {'CODE':>4} {'MS':>6}  {'NAME'.ljust(name_w)}  DETAIL"]
        for r in results:
            lines.append(f"{r.status:8} {str(r.http_code or '-'):>4} "
                         f"{str(r.latency_ms if r.latency_ms is not None else '-'):>6}  "
                         f"{r.name[:name_w].ljust(name_w)}  {r.detail}")
        ok = sum(1 for r in results if r.status == OK)
        lines.append("")
        lines.append(f"{ok}/{len(results)} streams answered.")
        text = "\n".join(lines)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as fh:
            fh.write(text + "\n")
        _out(f"Saved report to {args.output}")
    else:
        _out(text)

    if args.save_working:
        ok_urls = {r.url for r in results if r.status == OK}
        pl.entries = [e for e in entries if e.url in ok_urls]
        pl.save(args.save_working)
        _out(f"Saved {len(pl)} working entries to {args.save_working}")
    return 0 if any(r.status == OK for r in results) else 2


def cmd_clean(args) -> int:
    pl = load(args.playlist)
    before = len(pl)
    removed = pl.dedupe() if not args.keep_duplicates else 0
    if args.drop_empty_group:
        pl.entries = [e for e in pl if e.group]
    if args.sort:
        pl.sort(args.sort)
    pl.save(args.output)
    _out(f"{before} -> {len(pl)} entries ({removed} duplicates removed). Saved to {args.output}")
    return 0


def cmd_merge(args) -> int:
    out = merge((load(p) for p in args.playlists), dedupe=not args.keep_duplicates)
    if args.sort:
        out.sort(args.sort)
    out.save(args.output)
    _out(f"Merged {len(args.playlists)} playlists into {len(out)} entries. Saved to {args.output}")
    return 0


def cmd_filter(args) -> int:
    pl = load(args.playlist)
    out = pl.filter(group=args.group, name=args.name, exclude=args.exclude)
    out.save(args.output)
    _out(f"Kept {len(out)} of {len(pl)} entries. Saved to {args.output}")
    return 0


def cmd_groups(args) -> int:
    pl = load(args.playlist)
    for g, n in sorted(pl.groups().items()):
        _out(f"{n:6}  {g}")
    return 0


def cmd_speed(args) -> int:
    res = measure(args.url, seconds=args.seconds, timeout=args.timeout)
    _out(f"Downloaded  : {res.bytes_read / 1_000_000:.1f} MB in {res.seconds:.1f}s"
         + (f" ({res.segments} HLS segments)" if res.segments else ""))
    _out(f"Throughput  : {res.mbps:.1f} Mbps")
    _out("")
    for label, need in QUALITY_NEEDS:
        target = need * HEADROOM
        mark = "yes" if res.mbps >= target else "no "
        _out(f"  [{mark}] {label.ljust(16)} needs ~{need:g} Mbps (+{int((HEADROOM - 1) * 100)}% margin = {target:g})")
    best = res.best_quality()
    _out("")
    if best:
        _out(f"Result: this connection can play {best} smoothly.")
    else:
        _out("Result: too slow for smooth playback. See the buffering guide:")
        _out(f"        {DOCS}guides/buffering.html")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="iptv-toolkit",
        description="Inspect, check, clean and merge M3U/M3U8 playlists and test stream speed.",
        epilog=f"Documentation: {DOCS}",
    )
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    s = sub.add_parser("info", help="summary of a playlist (entries, groups, duplicates)")
    s.add_argument("playlist", help="path or http(s) URL of an .m3u/.m3u8 file")
    s.add_argument("--json", action="store_true", help="print JSON")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("check", help="test every stream and report which ones answer")
    s.add_argument("playlist")
    s.add_argument("-t", "--timeout", type=float, default=8.0, help="seconds per stream (default 8)")
    s.add_argument("-w", "--workers", type=int, default=10, help="parallel checks (default 10)")
    s.add_argument("-n", "--limit", type=int, default=0, help="only check the first N entries")
    s.add_argument("-f", "--format", choices=["table", "csv", "json"], default="table")
    s.add_argument("-o", "--output", help="write the report to a file")
    s.add_argument("--save-working", metavar="FILE", help="write a playlist with only working streams")
    s.add_argument("-q", "--quiet", action="store_true", help="no progress counter")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("clean", help="remove duplicates, sort, drop ungrouped entries")
    s.add_argument("playlist")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--sort", choices=["name", "group"])
    s.add_argument("--keep-duplicates", action="store_true")
    s.add_argument("--drop-empty-group", action="store_true", help="drop entries without group-title")
    s.set_defaults(func=cmd_clean)

    s = sub.add_parser("merge", help="merge several playlists into one")
    s.add_argument("playlists", nargs="+")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--sort", choices=["name", "group"])
    s.add_argument("--keep-duplicates", action="store_true")
    s.set_defaults(func=cmd_merge)

    s = sub.add_parser("filter", help="keep (or drop) entries by group and/or name")
    s.add_argument("playlist")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("-g", "--group", help="exact group-title (case-insensitive)")
    s.add_argument("-n", "--name", help="regular expression on the channel name")
    s.add_argument("-x", "--exclude", action="store_true", help="drop matches instead of keeping them")
    s.set_defaults(func=cmd_filter)

    s = sub.add_parser("groups", help="list groups and how many entries each has")
    s.add_argument("playlist")
    s.set_defaults(func=cmd_groups)

    s = sub.add_parser("speed", help="measure real throughput from one stream URL")
    s.add_argument("url")
    s.add_argument("-s", "--seconds", type=float, default=10.0, help="test length (default 10)")
    s.add_argument("-t", "--timeout", type=float, default=10.0)
    s.set_defaults(func=cmd_speed)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        sys.stderr.write(f"error: file not found: {exc.filename}\n")
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # network errors etc.
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
