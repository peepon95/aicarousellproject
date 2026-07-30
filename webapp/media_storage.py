"""Publish generated media to durable storage when running on Vercel."""

from __future__ import annotations

import io
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace


IS_VERCEL = bool(os.environ.get("VERCEL"))


def _read_write_token() -> str:
    return (
        os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()
        or os.environ.get("VERCEL_BLOB_READ_WRITE_TOKEN", "").strip()
    )


def _store_id() -> str:
    value = os.environ.get("BLOB_STORE_ID", "").strip()
    return value.removeprefix("store_")


def blob_is_configured(oidc_token: str = "") -> bool:
    return bool(_read_write_token() or (_store_id() and oidc_token.strip()))


def require_blob(oidc_token: str = "") -> None:
    if IS_VERCEL and not blob_is_configured(oidc_token):
        raise RuntimeError(
            "Connect a public Vercel Blob store to this project for the current "
            "environment, then redeploy. Vercel should provide BLOB_STORE_ID "
            "and a rotating OIDC token automatically."
        )


def _legacy_client():
    try:
        from vercel.blob import BlobClient
    except ImportError as exc:
        raise RuntimeError(
            "The Vercel Blob SDK is unavailable. Reinstall requirements.txt and redeploy."
        ) from exc
    return BlobClient(token=_read_write_token())


def _put_oidc(pathname: str, data: bytes, oidc_token: str):
    """Upload through Vercel Blob's OIDC-authenticated HTTP API."""
    store_id = _store_id()
    api_base = os.environ.get("VERCEL_BLOB_API_URL", "https://vercel.com/api/blob")
    url = f"{api_base}/?{urllib.parse.urlencode({'pathname': pathname})}"
    content_type = mimetypes.guess_type(pathname)[0] or "application/octet-stream"
    request = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={
            "Authorization": f"Bearer {oidc_token}",
            "Content-Type": content_type,
            "User-Agent": "ai-carousel-studio/1.0",
            "X-Api-Version": "12",
            "X-Api-Blob-Request-Id": (
                f"{store_id}:{int(time.time() * 1000)}:{uuid.uuid4().hex[:12]}"
            ),
            "X-Api-Blob-Request-Attempt": "0",
            "X-Vercel-Blob-Store-Id": store_id,
            "X-Vercel-Blob-Access": "public",
            "X-Add-Random-Suffix": "1",
            "X-Content-Type": content_type,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", "replace").strip()
        raise RuntimeError(
            f"Vercel Blob upload failed (HTTP {exc.code}): {detail or exc.reason}"
        ) from exc
    return SimpleNamespace(
        url=payload["url"],
        download_url=payload.get("downloadUrl", payload["url"]),
    )


def _put_bytes(client, pathname: str, data: bytes, oidc_token: str = ""):
    if client is not None:
        return client.put(
            pathname,
            data,
            access="public",
            add_random_suffix=True,
        )
    return _put_oidc(pathname, data, oidc_token)


def publish_file(
    path: str,
    folder: str = "previews",
    oidc_token: str = "",
) -> str:
    """Upload one generated file and return its durable public URL."""
    require_blob(oidc_token)
    if not IS_VERCEL:
        return path
    source = Path(path)
    client = _legacy_client() if _read_write_token() else None
    blob = _put_bytes(
        client,
        f"{folder}/{source.name}",
        source.read_bytes(),
        oidc_token,
    )
    return blob.url


def _zip_bytes(files: list[tuple[str, Path]]) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in files:
            if path.is_file():
                archive.write(path, arcname=name)
    return data.getvalue()


def publish_carousel(
    result: dict,
    out_dir: str,
    backgrounds_dir: str,
    oidc_token: str = "",
) -> dict:
    """Upload a completed carousel, its source photos, and download archives."""
    require_blob(oidc_token)
    if not IS_VERCEL:
        return result

    client = _legacy_client() if _read_write_token() else None
    run_id = uuid.uuid4().hex[:12]
    slide_files = [
        (name, Path(out_dir, name))
        for name in result.get("slides", [])
        if Path(out_dir, name).is_file()
    ]
    photo_files = [
        (name, Path(backgrounds_dir, name))
        for name in result.get("photos", [])
        if Path(backgrounds_dir, name).is_file()
    ]

    slide_urls: dict[str, str] = {}
    for name, path in slide_files:
        blob = _put_bytes(
            client,
            f"carousels/{run_id}/slides/{name}",
            path.read_bytes(),
            oidc_token,
        )
        slide_urls[name] = blob.url

    carousel_zip = _put_bytes(
        client,
        f"carousels/{run_id}/carousel-images.zip",
        _zip_bytes(slide_files),
        oidc_token,
    )

    photo_download_url = ""
    if photo_files:
        photos_zip = _put_bytes(
            client,
            f"carousels/{run_id}/background-photos.zip",
            _zip_bytes(photo_files),
            oidc_token,
        )
        photo_download_url = photos_zip.download_url

    return {
        **result,
        "slide_urls": slide_urls,
        "carousel_download_url": carousel_zip.download_url,
        "photo_download_url": photo_download_url,
    }
