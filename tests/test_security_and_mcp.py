"""Comprehensive L1 Security, L2 Economics/MCP, and CLI Regression Suite (v2.6.0).

Engineered by Neal Frazier Tech (@1nc0gn30) • NullAI Platform.
"""

from __future__ import annotations

import http.client
import io
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import zipfile
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from etsy_pod_forge import __version__
from etsy_pod_forge.listing_synthesizer import ProfitMetrics
from etsy_pod_forge.mcp_server import MCP_TOOLS_DEFINITIONS, handle_jsonrpc_message
from etsy_pod_forge.server import ForgeServer


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestHardenedServerSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.port = _free_port()
        cls.server = ForgeServer(host="127.0.0.1", port=cls.port, public_dir=str(REPO_ROOT / "public"))
        cls.server.start(block=False)
        time.sleep(0.35)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()

    def _raw_req(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5.0)
        req_headers = {"Host": f"127.0.0.1:{self.port}"}
        if headers:
            req_headers.update(headers)
        try:
            conn.request(method, path, body=body, headers=req_headers)
        except (BrokenPipeError, ConnectionResetError):
            pass
        resp = conn.getresponse()
        data = resp.read()
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, hdrs, data

    def _assert_security_headers(self, hdrs: dict[str, str]) -> None:
        self.assertEqual(hdrs.get("x-frame-options"), "SAMEORIGIN")
        self.assertEqual(hdrs.get("x-content-type-options"), "nosniff")
        self.assertEqual(hdrs.get("referrer-policy"), "strict-origin-when-cross-origin")
        csp = hdrs.get("content-security-policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'self' http://127.0.0.1:* http://localhost:*", csp)
        self.assertEqual(hdrs.get("vary"), "Origin")
        self.assertNotEqual(hdrs.get("access-control-allow-origin"), "*")

    def test_host_dns_rebinding_rejected_403(self) -> None:
        status, hdrs, _ = self._raw_req("GET", "/health", headers={"Host": "evil.example.invalid"})
        self.assertEqual(status, 403)
        self._assert_security_headers(hdrs)

    def test_cors_port_suffix_and_external_origin_403_all_methods(self) -> None:
        for bad_origin in ("http://127.0.0.1:81070", "https://evil.example"):
            for method, path in (
                ("GET", "/health"),
                ("HEAD", "/health"),
                ("OPTIONS", "/api/generate-canvas"),
                ("POST", "/api/generate-canvas"),
            ):
                body = b'{"cadre":"apparel"}' if method == "POST" else None
                hdr = {"Origin": bad_origin}
                if method == "POST":
                    hdr["Content-Type"] = "application/json"
                status, hdrs, _ = self._raw_req(method, path, body=body, headers=hdr)
                self.assertEqual(status, 403, f"{method} {path} Origin={bad_origin}")
                self._assert_security_headers(hdrs)
                self.assertNotIn("access-control-allow-origin", hdrs)

    def test_valid_loopback_origin_reflected_with_vary(self) -> None:
        origin = f"http://127.0.0.1:{self.port}"
        status, hdrs, data = self._raw_req("GET", "/health", headers={"Origin": origin})
        self.assertEqual(status, 200)
        self._assert_security_headers(hdrs)
        self.assertEqual(hdrs.get("access-control-allow-origin"), origin)
        parsed = json.loads(data.decode("utf-8"))
        self.assertEqual(parsed["port"], self.port)
        self.assertEqual(parsed["version"], __version__)
        self.assertEqual(parsed["mcp_tools"], 6)

    def test_directory_listing_and_traversal_blocked(self) -> None:
        status, hdrs, data = self._raw_req("GET", "/assets/")
        self.assertIn(status, (403, 404))
        self.assertNotIn(b"Directory listing", data)
        self._assert_security_headers(hdrs)

        for trav in ("/../server.py", "/%2e%2e/server.py"):
            st, h, _ = self._raw_req("GET", trav)
            self.assertIn(st, (403, 404), trav)
            self._assert_security_headers(h)

    def test_head_endpoints_200_empty_body(self) -> None:
        for ep in ("/", "/health", "/api/health", "/api/stats", "/api/cadres", "/api/prompts", "/api/mcp/tools"):
            status, hdrs, data = self._raw_req("HEAD", ep)
            self.assertEqual(status, 200, ep)
            self.assertEqual(data, b"", ep)
            self._assert_security_headers(hdrs)

    def test_body_cap_1mib_returns_413(self) -> None:
        oversized = b'{"cadre":"apparel","title":"' + (b"A" * 1_100_000) + b'"}'
        status, hdrs, _ = self._raw_req(
            "POST",
            "/api/generate-canvas",
            body=oversized,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 413)
        self._assert_security_headers(hdrs)

    def test_malformed_and_bad_type_json_returns_400(self) -> None:
        for payload in (b"{bad json", b"[1,2,3]", b'{"cadre":12345}', b'{"cadre":"unknown_cadre"}'):
            status, hdrs, _ = self._raw_req(
                "POST",
                "/api/generate-canvas",
                body=payload,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(status, 400, payload)
            self._assert_security_headers(hdrs)

    def test_export_kit_zip_slip_blocked_400_and_get_post_200(self) -> None:
        # POST Zip-Slip blocked
        st_post, hdrs_post, _ = self._raw_req(
            "POST",
            "/api/export-kit",
            body=json.dumps({"cadre": "../../evil", "title": "Test"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(st_post, 400)
        self._assert_security_headers(hdrs_post)

        # GET Zip-Slip blocked
        st_get_bad, _, _ = self._raw_req("GET", "/api/export-kit?cadre=../../evil")
        self.assertEqual(st_get_bad, 400)

        # Valid GET /api/export-kit?cadre=apparel returns real 200 application/zip
        st_get, hdrs_get, data = self._raw_req("GET", "/api/export-kit?cadre=apparel&title=Garden&retail=34.99")
        self.assertEqual(st_get, 200)
        self.assertEqual(hdrs_get.get("content-type"), "application/zip")
        self.assertEqual(hdrs_get.get("content-disposition"), 'attachment; filename="etsy_kit_apparel.zip"')
        self._assert_security_headers(hdrs_get)
        zf = zipfile.ZipFile(io.BytesIO(data))
        self.assertEqual(
            set(zf.namelist()),
            {"apparel_print_canvas.png", "apparel_lifestyle_mockup.jpg", "listing_details.txt", "listing_data.json"},
        )


class TestEconomicsMcpAndCli(unittest.TestCase):
    def test_offsite_ads_0_12_15_and_break_even(self) -> None:
        p0 = ProfitMetrics.calculate(34.99, 12.50, shipping_charged=4.99, shipping_cost=4.75, offsite_ads_rate=0.0)
        p12 = ProfitMetrics.calculate(34.99, 12.50, shipping_charged=4.99, shipping_cost=4.75, offsite_ads_rate=0.12)
        p15 = ProfitMetrics.calculate(34.99, 12.50, shipping_charged=4.99, shipping_cost=4.75, offsite_ads_rate=0.15)
        self.assertEqual(p0.gross_revenue, 39.98)
        self.assertEqual(p12.etsy_offsite_ads_fee, round(39.98 * 0.12, 2))
        self.assertEqual(p15.etsy_offsite_ads_fee, round(39.98 * 0.15, 2))
        self.assertGreater(p0.net_profit, p12.net_profit)
        self.assertGreater(p12.net_profit, p15.net_profit)
        self.assertLess(p0.break_even_price, p12.break_even_price)
        self.assertLess(p12.break_even_price, p15.break_even_price)

    def test_mcp_stdio_protocol_and_6_tools(self) -> None:
        self.assertEqual(len(MCP_TOOLS_DEFINITIONS), 6)
        init_resp = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(init_resp["result"]["serverInfo"]["version"], __version__)

        list_resp = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tool_names = [t["name"] for t in list_resp["result"]["tools"]]
        self.assertEqual(
            tool_names,
            [
                "pod_list_cadres",
                "pod_generate_canvas",
                "pod_generate_mockup",
                "pod_synthesize_listing",
                "pod_calculate_margins",
                "pod_search_prompts",
            ],
        )

        # Call pod_calculate_margins
        call_resp = handle_jsonrpc_message({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "pod_calculate_margins",
                "arguments": {"retail_price": 21.99, "production_cost": 6.80, "offsite_ads_rate": 0.12},
            },
        })
        self.assertFalse(call_resp["result"]["isError"])
        payload = json.loads(call_resp["result"]["content"][0]["text"])
        self.assertEqual(payload["retail_price"], 21.99)
        self.assertEqual(payload["offsite_ads_rate"], 0.12)

        # Live subprocess stdio check
        stdin_data = (
            json.dumps({"jsonrpc": "2.0", "id": 10, "method": "initialize", "params": {}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 11, "method": "tools/list", "params": {}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 12, "method": "tools/call", "params": {"name": "pod_list_cadres", "arguments": {}}}) + "\n"
        )
        env = dict(os.environ, PYTHONPATH=str(SRC_DIR))
        proc = subprocess.run(
            [sys.executable, "-m", "etsy_pod_forge.cli", "mcp"],
            input=stdin_data,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [json.loads(line) for line in proc.stdout.strip().splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(lines[1]["result"]["tools"]), 6)

    def test_cli_json_manifest_listing_status_and_desktop(self) -> None:
        bin_path = str(REPO_ROOT / "bin" / "etsy-pod-forge")
        tui_path = str(REPO_ROOT / "bin" / "etsy-pod-forge-tui")
        home_marker = "/home/" + os.environ.get("USER", "zoth")

        # 1. --json manifest (zero literal /home/<user> leak)
        r_json = subprocess.run([sys.executable, bin_path, "--json"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r_json.returncode, 0, r_json.stderr)
        self.assertNotIn(home_marker, r_json.stdout)
        manifest = json.loads(r_json.stdout)
        self.assertEqual(manifest["version"], __version__)
        self.assertEqual(manifest["mcp_tools"], 6)

        # 2. listing --cadre apparel --json (pure JSON, no ANSI banner)
        r_list = subprocess.run(
            [sys.executable, bin_path, "listing", "--cadre", "apparel", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(r_list.returncode, 0, r_list.stderr)
        parsed = json.loads(r_list.stdout)
        self.assertEqual(parsed["cadre"], "apparel")
        self.assertEqual(len(parsed["tags"]), 13)

        # 3. --status and desktop --dry-run
        r_stat = subprocess.run([sys.executable, bin_path, "--status", "--json"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r_stat.returncode, 0, r_stat.stderr)
        self.assertEqual(json.loads(r_stat.stdout)["version"], __version__)

        r_desk = subprocess.run([sys.executable, bin_path, "desktop", "--dry-run"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r_desk.returncode, 0, r_desk.stderr)

        # 4. Braille TUI --once --json (zero /home/<user>, zero math.sin)
        r_tui = subprocess.run([sys.executable, tui_path, "--once", "--json"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r_tui.returncode, 0, r_tui.stderr)
        self.assertNotIn(home_marker, r_tui.stdout)
        tui_data = json.loads(r_tui.stdout)
        self.assertEqual(tui_data["cadre_count"], 5)
        self.assertEqual(tui_data["prompt_count"], 53)
        self.assertEqual(tui_data["mcp_tool_count"], 6)


if __name__ == "__main__":
    unittest.main()
