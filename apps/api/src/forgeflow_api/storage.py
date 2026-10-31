"""Artifact storage: local directory (dev) or S3-compatible object storage (MinIO in production)."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def blob_key(sha256: str) -> str:
    return f"blobs/sha256/{sha256[:2]}/{sha256}"


class ArtifactStore:
    backend = "abstract"

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        raise NotImplementedError

    def get(self, key: str) -> bytes | None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def put_blob(self, data: bytes) -> str:
        """Content-addressed put; returns the sha256."""
        sha = hashlib.sha256(data).hexdigest()
        key = blob_key(sha)
        if not self.exists(key):
            self.put(key, data)
        return sha

    def get_blob(self, sha256: str) -> bytes | None:
        data = self.get(blob_key(sha256))
        if data is not None and hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError(f"blob {sha256} failed integrity check")
        return data


class LocalArtifactStore(ArtifactStore):
    backend = "local"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("invalid artifact key")
        return p

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, p)

    def get(self, key: str) -> bytes | None:
        p = self._path(key)
        return p.read_bytes() if p.exists() else None

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3ArtifactStore(ArtifactStore):
    backend = "s3"

    def __init__(self, endpoint: str, bucket: str, access_key: str | None, secret_key: str | None,
                 region: str = "us-east-1") -> None:
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=access_key,
                                   aws_secret_access_key=secret_key, region_name=region)
        try:
            self.client.head_bucket(Bucket=bucket)
        except Exception:  # noqa: BLE001
            self.client.create_bucket(Bucket=bucket)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001
            return False
