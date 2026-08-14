import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "model-fetch.py"
SPEC = importlib.util.spec_from_file_location("model_fetch", MODULE_PATH)
model_fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model_fetch)


class FakeResponse:
    def __init__(self, payload, next_url=None):
        self._payload = payload
        self.links = {"next": {"url": next_url}} if next_url else {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if len(self.calls) == 1:
            return FakeResponse(
                [{"path": "config.json", "size": 2, "lfs": {"sha256": "a" * 64}}],
                "https://hf-mirror.com/api/models/org/model/tree/main?page=2",
            )
        return FakeResponse([{"path": "weights.bin", "size": 3, "lfs": None}])

    def close(self):
        return None


class RetryClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.failures = 2

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.failures:
            self.failures -= 1
            raise model_fetch.httpx.RemoteProtocolError("server disconnected")
        return FakeResponse([{"path": "config.json", "size": 2, "lfs": None}])


class ManifestTests(unittest.TestCase):
    def test_manifest_uses_shared_client_and_reads_all_pages(self):
        with tempfile.TemporaryDirectory() as destination, mock.patch.dict(
            os.environ, {"HF_TOKEN": "test-token"}, clear=False
        ):
            fetcher = model_fetch.ModelFetcher("org/model", Path(destination), "https://hf-mirror.com")
            fake_client = FakeClient()
            fetcher.client.close()
            fetcher.client = fake_client
            try:
                fetcher.load_manifest()
            finally:
                fetcher.close()

        self.assertEqual([item["path"] for item in fetcher.files], ["weights.bin", "config.json"])
        self.assertEqual(fake_client.calls[0][1]["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(fake_client.calls[0][1]["params"], {"recursive": "true", "expand": "true"})
        self.assertIsNone(fake_client.calls[1][1]["params"])

    def test_manifest_does_not_require_huggingface_hub_client(self):
        self.assertNotIn("huggingface_hub", MODULE_PATH.read_text(encoding="utf-8"))

    def test_manifest_retries_transient_disconnect(self):
        with tempfile.TemporaryDirectory() as destination, mock.patch.object(model_fetch.time, "sleep") as sleep:
            fetcher = model_fetch.ModelFetcher("org/model", Path(destination), "https://hf-mirror.com")
            retry_client = RetryClient()
            fetcher.client.close()
            fetcher.client = retry_client
            try:
                fetcher.load_manifest()
            finally:
                fetcher.close()

        self.assertEqual(len(retry_client.calls), 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
