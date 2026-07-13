from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from market_liquidity_radar.cli import access_urls, run_self_check  # noqa: E402
from market_liquidity_radar.server import create_server  # noqa: E402
from quant_dashboard.market_heatmap import create_service  # noqa: E402


class LauncherTests(unittest.TestCase):
    def test_start_script_help_is_offline(self) -> None:
        result = subprocess.run(
            [sys.executable, "start.py", "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--print-urls-only", result.stdout)
        self.assertIn("--self-check", result.stdout)

    def test_local_url_is_first_when_listening_on_all_interfaces(self) -> None:
        urls = access_urls("0.0.0.0", 8772)
        self.assertEqual("http://127.0.0.1:8772/", urls[0])

    def test_loopback_host_does_not_advertise_lan(self) -> None:
        self.assertEqual(["http://127.0.0.1:8872/"], access_urls("127.0.0.1", 8872))

    def test_self_check_creates_private_runtime_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "runtime-data"
            self.assertEqual(0, run_self_check(data_dir))
            self.assertTrue(data_dir.is_dir())
            self.assertFalse((data_dir / ".write-test").exists())

    def test_custom_data_dir_isolates_sqlite_and_json_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            service = create_service(root)
            self.assertEqual(root / "market_heatmap" / "market_heatmap_intraday.sqlite3", service.history_store.path)
            self.assertEqual(root / "market_heatmap" / "latest_industry.json", service._cache_path("industry"))
            self.assertEqual(root / "market_heatmap" / "latest_concept.json", service._cache_path("concept"))

    def test_health_endpoint_and_full_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = create_server("127.0.0.1", 0, Path(temporary))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertEqual("市场流动性雷达", payload["service"])
                self.assertEqual(str(Path(temporary).resolve()), payload["data_dir"])
                with urlopen(f"http://127.0.0.1:{port}/market-liquidity-radar", timeout=2) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("多板块资金赛马", html)
                self.assertIn("stockTerminalDialog", html)
                with urlopen(f"http://127.0.0.1:{port}/api/market_heatmap/session_axis?trade_date=2026-07-13", timeout=2) as response:
                    axis = json.loads(response.read().decode("utf-8"))
                self.assertEqual(242, len(axis["session_axis"]["labels"]))
                self.assertEqual("15:00", axis["session_axis"]["display_end"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
