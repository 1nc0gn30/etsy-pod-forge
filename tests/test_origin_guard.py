"""Exact-port loopback Origin and Host header guards (CSRF / DNS-rebinding defense)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from etsy_pod_forge.server import _is_local_origin, _is_valid_host


class TestOriginGuard(unittest.TestCase):
    def test_allowed_generic(self):
        for o in (None, "", "http://127.0.0.1:8107", "http://localhost:3000", "http://[::1]:8107"):
            self.assertTrue(_is_local_origin(o), o)

    def test_allowed_exact_port(self):
        for o in (
            None,
            "",
            "http://127.0.0.1:8107",
            "http://localhost:8107",
            "http://[::1]:8107",
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ):
            self.assertTrue(_is_local_origin(o, server_port=8107), o)

    def test_blocked_port_suffix_and_external(self):
        for o in (
            "https://evil.example",
            "http://127.0.0.1:81070",
            "http://localhost:81070",
            "http://127.0.0.1:9999",
            "https://127.0.0.1:8107",
            "null",
            "http://127.0.0.1.evil.com",
            "file://",
            "chrome-extension://abc",
        ):
            self.assertFalse(_is_local_origin(o, server_port=8107), o)

    def test_host_header_guard(self):
        for h in ("127.0.0.1:8107", "localhost:8107", "[::1]:8107", "127.0.0.1", "localhost"):
            self.assertTrue(_is_valid_host(h, 8107), h)
        for bad in (None, "", "evil.example.invalid", "127.0.0.1:81070", "127.0.0.1:9999", "evil.com:8107"):
            self.assertFalse(_is_valid_host(bad, 8107), bad)


if __name__ == "__main__":
    unittest.main()
