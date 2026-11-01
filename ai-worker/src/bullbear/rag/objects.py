"""Immutable SHA-256 objects. Credentials belong to the SDK credential chain."""
from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path
from typing import Protocol
from uuid import uuid4


class ArchiveCorruptError(RuntimeError):
    """Saved bytes or relational history no longer match their identity."""


class ObjectStorageError(RuntimeError):
    """Bounded error safe for callers; never contains SDK credentials or URLs."""


def checked(key: str, payload: bytes) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", key) or hashlib.sha256(payload).hexdigest() != key:
        raise ArchiveCorruptError("object hash mismatch")
    return payload


class ObjectStore(Protocol):
    def put(self, key: str, payload: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...


class LocalObjectStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key):
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ArchiveCorruptError("invalid object key")
        target = self.directory / key
        if target.is_symlink():
            raise ArchiveCorruptError("object symlink is forbidden")
        return target

    def get(self, key):
        try:
            return checked(key, self._path(key).read_bytes())
        except OSError:
            raise ObjectStorageError("object read failed") from None

    def put(self, key, payload):
        checked(key, payload)
        target = self._path(key)
        temp = self.directory / f".{uuid4().hex}.tmp"
        try:
            with temp.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # Atomic create, never overwrite even a corrupt existing object.
                os.link(temp, target)
            except FileExistsError:
                if self.get(key) != payload:
                    raise ArchiveCorruptError("existing object mismatch")
        except OSError:
            raise ObjectStorageError("object write failed") from None
        finally:
            temp.unlink(missing_ok=True)


class S3ObjectStore:
    def __init__(self, bucket: str, *, prefix="rag/objects", endpoint_url=None, client=None):
        if not bucket or not prefix or any(part in {"", ".", ".."} for part in prefix.split("/")):
            raise ValueError("invalid object storage configuration")
        self.bucket, self.prefix = bucket, prefix
        if client is None:
            try:
                import boto3
                from botocore.config import Config
                client = boto3.client("s3", endpoint_url=endpoint_url, config=Config(
                    connect_timeout=3, read_timeout=10, retries={"mode": "standard", "total_max_attempts": 3}))
            except Exception:
                raise ObjectStorageError("object client configuration failed") from None
        self.client = client

    def _key(self, key):
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ArchiveCorruptError("invalid object key")
        return f"{self.prefix}/{key}"

    def get(self, key):
        remote = self._key(key)
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=remote)["Body"]
            try:
                payload = body.read()
            finally:
                body.close()
        except Exception:
            raise ObjectStorageError("object read failed") from None
        return checked(key, payload)

    def put(self, key, payload):
        checked(key, payload)
        for attempt in range(3):
            try:
                self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=payload,
                    IfNoneMatch="*", ChecksumSHA256=base64.b64encode(bytes.fromhex(key)).decode("ascii"))
                return
            except Exception as exc:
                status = getattr(exc, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
                if status == 412:
                    if self.get(key) != payload:
                        raise ArchiveCorruptError("existing object mismatch")
                    return
                if status == 409 and attempt < 2:
                    continue
                raise ObjectStorageError("object write failed") from None


class CachedObjectStore:
    """Verified immutable local cache; only a missing entry causes a remote read."""
    def __init__(self, remote: ObjectStore, directory: Path):
        self.remote = remote
        self.cache = LocalObjectStore(directory)

    def put(self, key, payload):
        self.remote.put(key, payload)
        self.cache.put(key, payload)

    def get(self, key):
        if self.cache._path(key).exists():
            return self.cache.get(key)
        payload = self.remote.get(key)
        self.cache.put(key, payload)
        return payload
