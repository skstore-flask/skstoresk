"""Uploads product images/videos to Supabase Storage (public buckets).

Works with any file-like object that has `.filename` and `.read()`
(Flask/Werkzeug FileStorage, or the old Streamlit UploadedFile via adapter).
"""
import uuid

from .db import client

IMAGE_BUCKET = "product-images"
VIDEO_BUCKET = "product-videos"
SLIP_BUCKET = "payment-slips"  # PRIVATE bucket — no public read policy

_ALLOWED_IMAGES = {"jpg", "jpeg", "png", "webp"}
_ALLOWED_VIDEOS = {"mp4", "webm", "mov", "m4v"}


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _read_bytes(file) -> bytes:
    if hasattr(file, "getvalue"):  # Streamlit UploadedFile (legacy adapter)
        return file.getvalue()
    data = file.read()  # Werkzeug FileStorage
    try:
        file.seek(0)
    except Exception:
        pass
    return data


def upload_image(file) -> str:
    """Returns public URL of the uploaded image."""
    ext = _ext(getattr(file, "filename", "") or "")
    if ext not in _ALLOWED_IMAGES:
        raise ValueError(f"Image type .{ext} not allowed (jpg, png, webp only)")
    return _upload(IMAGE_BUCKET, file, ext, f"image/{ext}")


def upload_video(file) -> str:
    """Returns public URL of the uploaded video."""
    ext = _ext(getattr(file, "filename", "") or "")
    if ext not in _ALLOWED_VIDEOS:
        raise ValueError(f"Video type .{ext} not allowed (mp4, webm, mov, m4v only)")
    return _upload(VIDEO_BUCKET, file, ext, f"video/{ext}")


def _upload(bucket: str, file, ext: str, content_type: str) -> str:
    sb = client()
    if sb is None:
        raise RuntimeError("Supabase configured nahi hai — env vars check karo.")
    path = f"{uuid.uuid4().hex}.{ext}"
    data = _read_bytes(file)
    sb.storage.from_(bucket).upload(
        path, data, file_options={"content-type": content_type, "upsert": "true"}
    )
    return sb.storage.from_(bucket).get_public_url(path)


def upload_slip(file) -> str:
    """Upload a payment-slip screenshot to the PRIVATE slips bucket.

    Returns the storage PATH (not a public URL). Admin views it via
    get_slip_url(), which mints a 1-hour signed URL.
    """
    ext = _ext(getattr(file, "filename", "") or "")
    if ext not in _ALLOWED_IMAGES:
        raise ValueError(f"Slip type .{ext} not allowed (jpg, png, webp only)")
    sb = client()
    if sb is None:
        raise RuntimeError("Supabase configured nahi hai — env vars check karo.")
    path = f"{uuid.uuid4().hex}.{ext}"
    data = _read_bytes(file)
    sb.storage.from_(SLIP_BUCKET).upload(
        path, data, file_options={"content-type": f"image/{ext}", "upsert": "true"}
    )
    return path


def get_slip_url(path: str, expires_in: int = 3600) -> str:
    """Signed (1-hour) URL for a private payment-slip path. '' when unusable."""
    sb = client()
    if sb is None or not path:
        return ""
    try:
        res = sb.storage.from_(SLIP_BUCKET).create_signed_url(path, expires_in)
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signedUrl") or ""
        return getattr(res, "signed_url", "") or ""
    except Exception:
        return ""


def delete_by_url(url):
    """Best-effort delete of a storage object given its public URL."""
    try:
        sb = client()
        if sb is None or not url:
            return
        for bucket in (IMAGE_BUCKET, VIDEO_BUCKET):
            marker = f"/{bucket}/"
            if marker in url:
                path = url.split(marker, 1)[1].split("?")[0]
                sb.storage.from_(bucket).remove([path])
                return
    except Exception:
        pass
