"""Content-addressed local development storage; files never use user-supplied paths."""

import hashlib
import io
import os
import stat
import zipfile
from pathlib import Path

from nexus.orchestration.contracts import Blocked

MAX_FILE = 5 * 1024 * 1024
MAX_TOTAL = 30 * 1024 * 1024


def source_files(root: Path) -> dict[str, bytes]:
    result = {}
    total = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(
            "\\" in part or ":" in part or any(ord(char) < 32 for char in part)
            for part in relative.parts
        ):
            raise Blocked("unsafe_artifact_path")
        if any(part in {".git", "node_modules", ".next", "__pycache__"} for part in relative.parts):
            continue
        if path.is_symlink():
            raise Blocked("unsafe_workspace_symlink")
        if path.is_dir():
            continue
        if len(result) >= 1000:
            raise Blocked("artifact_file_limit")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
                raise Blocked("unsafe_artifact_file")
            data = stream.read(MAX_FILE + 1)
        total += len(data)
        if len(data) > MAX_FILE or total > MAX_TOTAL:
            raise Blocked("artifact_size_limit")
        result[relative.as_posix()] = data
    if not result:
        raise Blocked("empty_artifact")
    return result


def archive(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            bundle.writestr(info, data)
    return output.getvalue()


class LocalObjects:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes) -> tuple[str, int]:
        digest = hashlib.sha256(data).hexdigest()
        path = self.root / digest
        if not path.exists():
            temporary = self.root / f"{digest}.{os.urandom(8).hex()}.tmp"
            temporary.write_bytes(data)
            os.replace(temporary, path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise Blocked("artifact_hash_mismatch")
        return digest, len(data)

    def read(self, key: str, digest: str) -> bytes:
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise Blocked("invalid_object_key")
        data = (self.root / key).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise Blocked("artifact_hash_mismatch")
        return data


class S3Objects:
    def __init__(self, bucket: str, endpoint: str | None = None):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            config=Config(
                connect_timeout=5, read_timeout=30, retries={"max_attempts": 2, "mode": "standard"}
            ),
        )

    def put(self, data: bytes) -> tuple[str, int]:
        digest = hashlib.sha256(data).hexdigest()
        self.client.put_object(
            Bucket=self.bucket,
            Key=digest,
            Body=data,
            ContentType="application/octet-stream",
            Metadata={"sha256": digest},
        )
        # Verify actual bytes, not just untrusted metadata or multipart ETags.
        self.read(digest, digest)
        return digest, len(data)

    def read(self, key: str, digest: str) -> bytes:
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise Blocked("invalid_object_key")
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        try:
            data = response["Body"].read(MAX_TOTAL + 1024 * 1024)
        finally:
            response["Body"].close()
        if hashlib.sha256(data).hexdigest() != digest:
            raise Blocked("artifact_hash_mismatch")
        return data


def configured_objects():
    bucket = os.getenv("NEXUS_S3_BUCKET")
    if bucket:
        return S3Objects(bucket, os.getenv("NEXUS_S3_ENDPOINT"))
    return LocalObjects(os.getenv("NEXUS_ARTIFACT_ROOT", ".data/artifacts"))
