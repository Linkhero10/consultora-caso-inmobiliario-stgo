import hashlib
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fulltext_acquisition import fetch_url, write_manifest_record


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/ok":
            payload = b"hello external source"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args):
        return


class ExternalSourceAcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=2)

    def test_fetch_url_saves_raw_and_hashes_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = fetch_url(f"{self.base_url}/ok", pathlib.Path(tmp), "F-TEST", timeout=5)
            expected = hashlib.sha256(b"hello external source").hexdigest()
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["sha256"], expected)
            self.assertTrue(pathlib.Path(result["raw_path"]).exists())

    def test_fetch_url_distinguishes_http_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = fetch_url(f"{self.base_url}/missing", pathlib.Path(tmp), "F-TEST", timeout=5)
            self.assertEqual(result["status"], "http_error")
            self.assertEqual(result["http_status"], 404)
            self.assertIsNone(result["sha256"])

    def test_write_manifest_record_is_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "manifest.jsonl"
            write_manifest_record(path, {"source_id": "F-TEST", "status": "ok"})
            row = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(row["source_id"], "F-TEST")


if __name__ == "__main__":
    unittest.main()
