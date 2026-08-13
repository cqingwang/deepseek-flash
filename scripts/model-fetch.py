#!/usr/bin/env python3
"""按 main 分支 dsv4-chunkdl.py 的行为下载任意 Hugging Face 模型。

特性：官方文件清单、20 并发、8 MiB Range 分块、每块重试、.chunks.json 断点、
文件级 SHA-256 校验、失败文件重下和 --verify-only 全量复核。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from urllib.parse import quote

import httpx
from huggingface_hub import HfApi


CHUNK_SIZE = 8 * 1024 * 1024
WORKERS = 20
TIMEOUT = 120.0
RETRIES = 8


class ModelFetcher:
    def __init__(self, repo_id: str, destination: Path, endpoint: str):
        self.repo_id = repo_id
        self.destination = destination
        self.endpoint = endpoint.rstrip("/")
        self.files = []
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=TIMEOUT,
            headers={"User-Agent": "deepseek-flash-model-fetch/1.0"},
            transport=httpx.HTTPTransport(verify=True),
        )
        self.lock = Lock()
        self.stats = {"bytes": 0, "started": time.time()}

    def close(self):
        self.client.close()

    def load_manifest(self):
        token = os.environ.get("HF_TOKEN") or None
        api = HfApi(endpoint=self.endpoint, token=token)
        tree = list(api.list_repo_tree(self.repo_id, repo_type="model", recursive=True, expand=True))
        self.files = sorted(
            [
                {
                    "path": item.path,
                    "size": int(item.size or 0),
                    "sha256": getattr(getattr(item, "lfs", None), "sha256", None),
                }
                for item in tree
                if getattr(item, "size", None) is not None
            ],
            key=lambda item: -item["size"],
        )
        if not self.files:
            raise RuntimeError(f"模型清单为空: {self.repo_id}")
        manifest_path = self.destination / ".fetch-files.json"
        manifest_path.write_text(json.dumps(self.files, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[manifest] {len(self.files)} files, {sum(item['size'] for item in self.files) / 1e9:.2f} GB")

    def file_path(self, relative):
        path = (self.destination / relative).resolve()
        if os.path.commonpath([str(self.destination.resolve()), str(path)]) != str(self.destination.resolve()):
            raise RuntimeError(f"清单路径越界: {relative}")
        return path

    def verify_sha256(self, meta):
        path = self.file_path(meta["path"])
        if not path.is_file() or path.stat().st_size != meta["size"]:
            return False
        expected = meta.get("sha256")
        if not expected:
            return True
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(CHUNK_SIZE):
                digest.update(block)
        actual = digest.hexdigest()
        if actual != expected:
            print(f"[hash-fail] {meta['path']} expected {expected[:16]} got {actual[:16]}", flush=True)
            return False
        return True

    def verify_pass(self):
        failures = []
        checked = 0
        for meta in self.files:
            path = self.file_path(meta["path"])
            if not path.is_file() or path.stat().st_size != meta["size"]:
                failures.append((meta["path"], "missing/size"))
                continue
            if meta.get("sha256"):
                checked += 1
                if not self.verify_sha256(meta):
                    failures.append((meta["path"], "sha256"))
            else:
                checked += 1
                if path.suffix == ".json":
                    try:
                        json.loads(path.read_text(encoding="utf-8"))
                    except Exception as exc:
                        failures.append((meta["path"], f"json:{exc}"))
        print(f"[verify] checked {checked}/{len(self.files)} files, failures: {len(failures)}", flush=True)
        for path, reason in failures[:20]:
            print(f"[verify-FAIL] {path} ({reason})", flush=True)
        return not failures

    def download_chunk(self, relative, offset, size):
        url = f"{self.endpoint}/{self.repo_id}/resolve/main/{quote(relative, safe='/')}"
        last_error = None
        headers = {"Range": f"bytes={offset}-{offset + size - 1}"}
        if os.environ.get("HF_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['HF_TOKEN']}"
        for attempt in range(RETRIES):
            try:
                response = self.client.get(url, headers=headers)
                if response.status_code == 206:
                    data = response.content
                elif response.status_code == 200:
                    if offset != 0 or len(response.content) < size:
                        raise RuntimeError(f"server ignored range (200, off={offset}, len={len(response.content)})")
                    data = response.content[:size]
                else:
                    raise RuntimeError(f"status {response.status_code}")
                if len(data) != size:
                    raise RuntimeError(f"short response {len(data)}<{size}")
                with self.file_path(relative).open("r+b") as stream:
                    stream.seek(offset)
                    stream.write(data)
                with self.lock:
                    self.stats["bytes"] += size
                return True
            except Exception as exc:
                last_error = exc
                time.sleep(min(2 * (attempt + 1), 20))
        print(f"[drop] {relative}@{offset}: {last_error}", flush=True)
        return False

    def download_file(self, meta):
        path = self.file_path(meta["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.verify_sha256(meta):
            print(f"[skip] {meta['path']}", flush=True)
            return True
        sidecar = Path(f"{path}.chunks.json")
        done = set()
        if sidecar.is_file():
            try:
                done = {int(offset) for offset in json.loads(sidecar.read_text(encoding="utf-8"))}
            except Exception:
                done = set()
        if not path.is_file() or path.stat().st_size != meta["size"]:
            done = set()
            with path.open("wb") as stream:
                stream.truncate(meta["size"])
        chunks = [(offset, min(CHUNK_SIZE, meta["size"] - offset)) for offset in range(0, meta["size"], CHUNK_SIZE)]
        valid_offsets = {offset for offset, _ in chunks}
        done &= valid_offsets
        todo = [(offset, size) for offset, size in chunks if offset not in done]
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {executor.submit(self.download_chunk, meta["path"], offset, size): offset for offset, size in todo}
            for future in as_completed(futures):
                offset = futures[future]
                if future.result():
                    done.add(offset)
                else:
                    print(f"[chunk-fail] {meta['path']}@{offset}", flush=True)
        sidecar.write_text(json.dumps(sorted(done)), encoding="utf-8")
        if len(done) != len(chunks):
            print(f"[incomplete] {meta['path']} {len(done)}/{len(chunks)}", flush=True)
            return False
        if self.verify_sha256(meta):
            sidecar.unlink(missing_ok=True)
            print(f"[OK] {meta['path']} ({meta['size'] / 1e9:.2f} GB)", flush=True)
            return True
        sidecar.unlink(missing_ok=True)
        return False

    def run(self, verify_only=False):
        self.destination.mkdir(parents=True, exist_ok=True)
        self.load_manifest()
        if verify_only:
            return self.verify_pass()
        pending = list(self.files)
        for round_number in range(1, 11):
            if not pending:
                break
            print(f"=== round {round_number}: {len(pending)} files ===", flush=True)
            pending = [meta for meta in pending if not self.download_file(meta)]
            if pending:
                time.sleep(20)
        if pending:
            print("STILL_PENDING", [meta["path"] for meta in pending], flush=True)
            return False
        print("ALL_DOWNLOADED", flush=True)
        return self.verify_pass()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--endpoint", default="https://hf-mirror.com")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    fetcher = ModelFetcher(args.repo_id, args.destination, args.endpoint)
    try:
        return 0 if fetcher.run(verify_only=args.verify_only) else 1
    finally:
        fetcher.close()


if __name__ == "__main__":
    sys.exit(main())
