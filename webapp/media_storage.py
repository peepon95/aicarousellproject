"""Publish generated media to durable storage when running on Vercel."""

from __future__ import annotations

import io
import os
import uuid
import zipfile
from pathlib import Path


IS_VERCEL = bool(os.environ.get("VERCEL"))


def blob_is_configured() -> bool:
    return bool(os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip())


def require_blob() -> None:
    if IS_VERCEL and not blob_is_configured():
        raise RuntimeError(
            "Connect a public Vercel Blob store to this project, then redeploy. "
            "Carousel images need durable storage on Vercel."
        )


def _client():
    try:
        from vercel.blob import BlobClient
    except ImportError as exc:
        raise RuntimeError(
            "The Vercel Blob SDK is unavailable. Reinstall requirements.txt and redeploy."
        ) from exc
    return BlobClient()


def _put_bytes(client, pathname: str, data: bytes):
    return client.put(
        pathname,
        data,
        access="public",
        add_random_suffix=True,
    )


def publish_file(path: str, folder: str = "previews") -> str:
    """Upload one generated file and return its durable public URL."""
    require_blob()
    if not IS_VERCEL:
        return path
    source = Path(path)
    blob = _put_bytes(_client(), f"{folder}/{source.name}", source.read_bytes())
    return blob.url


def _zip_bytes(files: list[tuple[str, Path]]) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in files:
            if path.is_file():
                archive.write(path, arcname=name)
    return data.getvalue()


def publish_carousel(result: dict, out_dir: str, backgrounds_dir: str) -> dict:
    """Upload a completed carousel, its source photos, and download archives."""
    require_blob()
    if not IS_VERCEL:
        return result

    client = _client()
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
        )
        slide_urls[name] = blob.url

    carousel_zip = _put_bytes(
        client,
        f"carousels/{run_id}/carousel-images.zip",
        _zip_bytes(slide_files),
    )

    photo_download_url = ""
    if photo_files:
        photos_zip = _put_bytes(
            client,
            f"carousels/{run_id}/background-photos.zip",
            _zip_bytes(photo_files),
        )
        photo_download_url = photos_zip.download_url

    return {
        **result,
        "slide_urls": slide_urls,
        "carousel_download_url": carousel_zip.download_url,
        "photo_download_url": photo_download_url,
    }
