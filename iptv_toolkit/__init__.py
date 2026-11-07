"""iptv-toolkit: inspect, check, clean and merge M3U playlists and test stream speed."""

__version__ = "1.0.0"

from .m3u import Entry, Playlist, load, merge, parse  # noqa: E402,F401
