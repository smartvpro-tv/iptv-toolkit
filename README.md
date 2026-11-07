# iptv-toolkit

[![tests](https://github.com/smartvpro-tv/iptv-toolkit/actions/workflows/tests.yml/badge.svg)](https://github.com/smartvpro-tv/iptv-toolkit/actions/workflows/tests.yml)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-smartvpro--tv.github.io-orange.svg)](https://smartvpro-tv.github.io/iptv-toolkit/)

**iptv-toolkit** is a small command-line tool to inspect, check, clean and merge
**M3U / M3U8 playlists**, and to measure the real speed you get from a stream.

It has **zero dependencies**: if you have Python 3.8 or newer, it runs on Windows,
macOS, Linux, a Raspberry Pi or Android (Termux).

* 📋 `info` — how many channels, groups, duplicates, missing EPG ids and logos
* ✅ `check` — test every stream in parallel and keep only the ones that answer
* 🧹 `clean` — remove duplicate URLs and sort by name or group
* 🔗 `merge` — combine several playlists into one
* 🔎 `filter` — keep or drop channels by group or name
* 🚀 `speed` — download from a stream for a few seconds and tell you if your line can play SD, HD, Full HD or 4K

📖 Full documentation and guides: **https://smartvpro-tv.github.io/iptv-toolkit/**

> iptv-toolkit does not include, find or share any channels or playlists.
> Use it only with playlists you are allowed to use, such as the one from your own provider.

## Installation

### From GitHub (recommended)

```sh
pip install git+https://github.com/smartvpro-tv/iptv-toolkit.git
```

### From source

```sh
git clone https://github.com/smartvpro-tv/iptv-toolkit.git
cd iptv-toolkit
pip install .
```

### Without installing

```sh
git clone https://github.com/smartvpro-tv/iptv-toolkit.git
cd iptv-toolkit
python -m iptv_toolkit --help
```

### Upgrading

```sh
pip install --upgrade git+https://github.com/smartvpro-tv/iptv-toolkit.git
```

## Getting started

Every command accepts a local file **or** an `http(s)://` URL.

### See what is inside a playlist

```console
$ iptv-toolkit info examples/sample.m3u
Entries        : 5
Groups         : 4
Duplicate URLs : 1
No tvg-id      : 2
No logo        : 3
EPG source     : https://example.com/epg.xml

  Sports      2
  (no group)  1
  Kids        1
  News        1
```

### Check which streams work

```console
$ iptv-toolkit check my_playlist.m3u --save-working working.m3u
STATUS   CODE     MS  NAME              DETAIL
OK        200    142  News One
OK        200    188  Sports One HD
DEAD      404     95  Old Channel       Not Found
TIMEOUT     -      -  Slow Channel      no answer in 8s

2/4 streams answered.
Saved 2 working entries to working.m3u
```

Useful options:

| Option | Meaning |
| --- | --- |
| `-t 5` | timeout per stream in seconds (default 8) |
| `-w 20` | number of parallel checks (default 10) |
| `-n 50` | only check the first 50 entries |
| `-f csv` / `-f json` | machine-readable report |
| `-o report.csv` | write the report to a file |
| `--save-working FILE` | write a new playlist with only the working streams |

Status values: `OK` (answered with data; for HLS the body is a real `#EXTM3U` playlist),
`DEAD` (HTTP error, empty body, or a login page instead of a stream), `TIMEOUT`, `ERROR`
(DNS, TLS or connection problem).

### Clean, merge and filter

```sh
# remove duplicate URLs and sort by group
iptv-toolkit clean my_playlist.m3u -o clean.m3u --sort group

# merge two playlists (duplicates removed)
iptv-toolkit merge part1.m3u part2.m3u -o all.m3u

# keep only the "Sports" group
iptv-toolkit filter all.m3u -g Sports -o sports.m3u

# drop every channel whose name contains "radio"
iptv-toolkit filter all.m3u -n radio --exclude -o no-radio.m3u

# list groups
iptv-toolkit groups all.m3u
```

### Test your real stream speed

A normal internet speed test measures the line to a nearby test server.
`speed` measures the line **to the stream itself**, which is what matters when a
channel buffers. For HLS it follows the master playlist to the highest-quality
variant and downloads real segments.

```console
$ iptv-toolkit speed "http://your-provider.example/live/channel/index.m3u8"
Downloaded  : 21.4 MB in 10.0s (5 HLS segments)
Throughput  : 17.1 Mbps

  [yes] SD (480p)        needs ~3 Mbps (+50% margin = 4.5)
  [yes] HD (720p)        needs ~5 Mbps (+50% margin = 7.5)
  [yes] Full HD (1080p)  needs ~10 Mbps (+50% margin = 15)
  [no ] 4K (2160p)       needs ~25 Mbps (+50% margin = 37.5)

Result: this connection can play Full HD (1080p) smoothly.
```

If the result is too low, read the [buffering guide](https://smartvpro-tv.github.io/iptv-toolkit/guides/buffering.html).

## Use it from Python

```python
from iptv_toolkit import load, merge
from iptv_toolkit.checker import check_entries

pl = load("my_playlist.m3u")
print(len(pl), pl.groups())

pl.dedupe()
pl.sort("group")
pl.save("clean.m3u")

results = check_entries(pl.entries, timeout=5, workers=20)
print(sum(r.status == "OK" for r in results), "working")
```

## Guides

* [Getting started](https://smartvpro-tv.github.io/iptv-toolkit/guides/getting-started.html)
* [Fix IPTV buffering step by step](https://smartvpro-tv.github.io/iptv-toolkit/guides/buffering.html)
* [The M3U format explained](https://smartvpro-tv.github.io/iptv-toolkit/guides/m3u-format.html)
* Country guides: [USA](https://smartvpro-tv.github.io/iptv-toolkit/usa.html) ·
  [UK](https://smartvpro-tv.github.io/iptv-toolkit/uk.html) ·
  [Canada](https://smartvpro-tv.github.io/iptv-toolkit/canada.html) ·
  [Nederland](https://smartvpro-tv.github.io/iptv-toolkit/nederland.html)

## Running the tests

```sh
python -m unittest discover -s tests -v
```

The tests start a tiny local HTTP server, so they need no internet access.

## Related projects

* [m3u-playlist-checker](https://github.com/smartvpro-tv/m3u-playlist-checker)
* [iptv-troubleshooting](https://github.com/smartvpro-tv/iptv-troubleshooting)
* [iptv-setup-guides](https://github.com/smartvpro-tv/iptv-setup-guides)
* [awesome-iptv-players](https://github.com/smartvpro-tv/awesome-iptv-players)

Maintained by [SmartVPro](https://smartvpro.com/) — IPTV help for
[USA](https://smartvpro.com/), [UK](https://smartvpro.co.uk/iptv-uk/),
[Canada](https://iptvv-ca.ca/) and [Nederland](https://dutchiptvnl.net/).

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
