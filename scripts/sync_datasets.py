#!/usr/bin/env python3
"""Publish the verified dataset library to object storage and the serving tree.

Responsibilities:
  1. Read every manifest under ``datasets/manifests``.
  2. Verify each serving file against the recorded sha256 (never publish a
     file whose bytes do not match the manifest).
  3. Upload the file to the S3-compatible bucket (MinIO) under ``object_key``.
  4. Ensure the local read-only serving tree (``datasets/serving``) is present
     for the docker-compose / hostPath deployment path.

The script is idempotent: identical bytes are not re-uploaded.

Usage:
    python scripts/sync_datasets.py [--force] [--skip-upload]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.datasets.manifests import load_manifests, verify_file  # noqa: E402

MANIFESTS = REPO / "datasets" / "manifests"
SERVING = REPO / "datasets" / "serving"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_client():
    """Return an S3 client, or None when object storage is not configured."""
    endpoint = os.environ.get("OPENCE_S3_ENDPOINT", "").strip()
    if not endpoint:
        return None
    try:
        import boto3
    except ImportError:
        print("boto3 is not installed; run inside the backend virtualenv", file=sys.stderr)
        return None
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("OPENCE_S3_ACCESS_KEY", ""),
        aws_secret_access_key=os.environ.get("OPENCE_S3_SECRET_KEY", ""),
        region_name=os.environ.get("OPENCE_S3_REGION", "us-east-1"),
    )


def ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:  # noqa: BLE001 - create when missing
        client.create_bucket(Bucket=bucket)
        print(f"  created bucket {bucket}")


def remote_sha(client, bucket: str, key: str) -> str | None:
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except Exception:  # noqa: BLE001
        return None
    return (head.get("Metadata") or {}).get("sha256")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-upload files even if unchanged")
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="only verify the serving tree locally",
    )
    args = parser.parse_args()

    manifests = load_manifests(MANIFESTS)
    if not manifests:
        print("no manifests found; run scripts/fetch_datasets.py first", file=sys.stderr)
        return 1

    bucket = os.environ.get("OPENCE_S3_BUCKET", "opencs-datasets")
    client = None if args.skip_upload else build_client()
    if not args.skip_upload and client is None:
        print("object storage is not configured; verifying the local serving tree only")
    if client is not None:
        ensure_bucket(client, bucket)

    verified = 0
    uploaded = 0
    skipped = 0
    failures = 0

    for manifest in manifests:
        problems = verify_file(manifest, SERVING)
        if problems:
            failures += 1
            print(f"[{manifest.slug}] FAILED verification: {'; '.join(problems)}", file=sys.stderr)
            continue
        verified += 1

        for version in manifest.versions:
            local = SERVING / version.relative_mount_path
            checksum = sha256_file(local)
            if checksum != version.sha256:
                failures += 1
                print(
                    f"[{manifest.slug}] checksum drift on {local}: "
                    f"{checksum[:12]} != {version.sha256[:12]}",
                    file=sys.stderr,
                )
                continue
            if client is None:
                continue
            existing = remote_sha(client, bucket, version.object_key)
            if existing == checksum and not args.force:
                skipped += 1
                continue
            client.upload_file(
                str(local),
                bucket,
                version.object_key,
                ExtraArgs={"Metadata": {"sha256": checksum, "dataset": manifest.slug}},
            )
            uploaded += 1
            print(f"[{manifest.slug}] uploaded {version.object_key}")

    print(
        f"\nverified {verified}/{len(manifests)} datasets · "
        f"uploaded {uploaded} · skipped {skipped} · failures {failures}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
