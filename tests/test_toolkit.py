import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from iptv_toolkit import m3u
from iptv_toolkit.checker import DEAD, ERROR, OK, check_url
from iptv_toolkit.cli import main
from iptv_toolkit.speed import measure

HERE = os.path.dirname(__file__)
SAMPLE = os.path.join(HERE, "..", "examples", "sample.m3u")

SEGMENT = b"\x47" * 188 * 500  # 94 KB of MPEG-TS sync bytes


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/master.m3u8":
            body = (b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\nlow.m3u8\n"
                    b"#EXT-X-STREAM-INF:BANDWIDTH=5000000\nhigh.m3u8\n")
            self._send(200, body, "application/vnd.apple.mpegurl")
        elif self.path in ("/high.m3u8", "/low.m3u8"):
            body = b"#EXTM3U\n#EXTINF:6,\nseg1.ts\n#EXTINF:6,\nseg2.ts\n"
            self._send(200, body, "application/vnd.apple.mpegurl")
        elif self.path.endswith(".ts"):
            self._send(200, SEGMENT, "video/mp2t")
        elif self.path == "/notaplaylist.m3u8":
            self._send(200, b"<html>login</html>", "text/html")
        elif self.path == "/list.m3u":
            with open(SAMPLE, "rb") as fh:
                self._send(200, fh.read(), "audio/x-mpegurl")
        else:
            self._send(404, b"nope", "text/plain")


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()


class TestParse(unittest.TestCase):
    def test_parse_sample(self):
        pl = m3u.load(SAMPLE)
        self.assertEqual(len(pl), 5)
        self.assertEqual(pl.header_attrs["x-tvg-url"], "https://example.com/epg.xml")
        first = pl.entries[0]
        self.assertEqual(first.name, "News One")
        self.assertEqual(first.group, "News")
        self.assertEqual(first.tvg_id, "news.one")
        self.assertEqual(pl.entries[1].extra, ["#EXTVLCOPT:http-user-agent=Mozilla/5.0"])
        # comma inside the title must stay in the title
        self.assertEqual(pl.entries[3].name, "Kids, Cartoons & More")
        self.assertEqual(pl.entries[4].group, "")

    def test_round_trip(self):
        pl = m3u.load(SAMPLE)
        again = m3u.parse(pl.dumps())
        self.assertEqual([e.url for e in again], [e.url for e in pl])
        self.assertEqual([e.attrs for e in again], [e.attrs for e in pl])

    def test_plain_m3u(self):
        pl = m3u.parse("http://a/1.ts\nhttp://a/2.ts\n")
        self.assertEqual([e.name for e in pl], ["1.ts", "2.ts"])

    def test_dedupe_sort_filter_groups(self):
        pl = m3u.load(SAMPLE)
        self.assertEqual(pl.dedupe(), 1)
        self.assertEqual(len(pl), 4)
        self.assertEqual(pl.groups()["Sports"], 1)
        pl.sort("name")
        self.assertEqual(pl.entries[0].name, "Kids, Cartoons & More")
        self.assertEqual(len(pl.filter(group="sports")), 1)
        self.assertEqual(len(pl.filter(name="one", exclude=True)), 2)

    def test_merge(self):
        a = m3u.load(SAMPLE)
        b = m3u.load(SAMPLE)
        self.assertEqual(len(m3u.merge([a, b])), 4)
        self.assertEqual(len(m3u.merge([m3u.load(SAMPLE), m3u.load(SAMPLE)], dedupe=False)), 10)


class TestNetwork(Base):
    def test_check_states(self):
        self.assertEqual(check_url(self.base + "/master.m3u8").status, OK)
        self.assertEqual(check_url(self.base + "/seg1.ts").status, OK)
        r = check_url(self.base + "/missing.m3u8")
        self.assertEqual((r.status, r.http_code), (DEAD, 404))
        self.assertEqual(check_url(self.base + "/notaplaylist.m3u8").status, DEAD)
        self.assertEqual(check_url("http://127.0.0.1:1/x.ts", timeout=2).status, ERROR)

    def test_load_from_url(self):
        self.assertEqual(len(m3u.load(self.base + "/list.m3u")), 5)

    def test_speed_follows_best_variant(self):
        res = measure(self.base + "/master.m3u8", seconds=5)
        self.assertEqual(res.segments, 2)
        self.assertEqual(res.bytes_read, 2 * len(SEGMENT))
        self.assertGreater(res.mbps, 0)

    def test_cli_check_and_save_working(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.m3u")
            with open(src, "w") as fh:
                fh.write("#EXTM3U\n#EXTINF:-1,Good\n%s/master.m3u8\n#EXTINF:-1,Bad\n%s/gone.mp4\n"
                         % (self.base, self.base))
            out = os.path.join(tmp, "ok.m3u")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["check", src, "-q", "-f", "json", "--save-working", out])
            self.assertEqual(code, 0)
            rows = json.loads(buf.getvalue().split("\nSaved")[0])
            self.assertEqual([r["status"] for r in rows], [OK, DEAD])
            self.assertEqual([e.name for e in m3u.load(out)], ["Good"])


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(list(args))
        return code, buf.getvalue()

    def test_info(self):
        code, out = self.run_cli("info", SAMPLE, "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["entries"], 5)
        self.assertEqual(data["duplicates"], 1)

    def test_clean_merge_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "o.m3u")
            self.assertEqual(self.run_cli("clean", SAMPLE, "-o", out, "--sort", "group")[0], 0)
            self.assertEqual(len(m3u.load(out)), 4)
            self.assertEqual(self.run_cli("merge", SAMPLE, SAMPLE, "-o", out)[0], 0)
            self.assertEqual(len(m3u.load(out)), 4)
            self.assertEqual(self.run_cli("filter", SAMPLE, "-g", "Sports", "-o", out)[0], 0)
            self.assertEqual(len(m3u.load(out)), 2)

    def test_missing_file(self):
        self.assertEqual(main(["info", "does-not-exist.m3u"]), 1)


if __name__ == "__main__":
    unittest.main()
