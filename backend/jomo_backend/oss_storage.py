from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import mimetypes
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


ROOT_PREFIX = "zhanyu/data/jomo"


@dataclass(frozen=True)
class OssConfig:
    access_key_id: str
    access_key_secret: str
    endpoint: str
    bucket: str
    download_base_url: str


def enabled() -> bool:
    return load_config() is not None


def load_config() -> OssConfig | None:
    access_key_id = os.getenv("OSS_ACCESS_KEY_ID", "").strip()
    access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET", "").strip()
    endpoint = os.getenv("OSS_ENDPOINT", "").strip()
    bucket = os.getenv("OSS_BUCKET", "").strip()
    download_base_url = os.getenv("OSS_DOWNLOAD_BASE_URL", "").strip()
    if not all([access_key_id, access_key_secret, endpoint, bucket]):
        return None
    return OssConfig(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        endpoint=endpoint,
        bucket=bucket,
        download_base_url=download_base_url,
    )


def upload_data_url(*, data_url: str, filename: str = "", username: str = "guest", kind: str = "uploads") -> dict[str, Any]:
    header, _, encoded = data_url.partition(",")
    if not header.startswith("data:") or not encoded:
        raise ValueError("invalid data url")
    content_type = header[5:].split(";", 1)[0] or guess_content_type(filename)
    content = base64.b64decode(encoded)
    suffix = suffix_for(filename=filename, content_type=content_type)
    key = make_object_key(username=username, kind=kind, suffix=suffix)
    return upload_bytes(content, key=key, content_type=content_type, filename=filename)


def upload_file(path: Path, *, username: str = "agent", kind: str = "generated") -> dict[str, Any] | None:
    if not enabled() or not path.exists() or not path.is_file():
        return None
    content_type = guess_content_type(path.name)
    key = make_object_key(username=username, kind=kind, suffix=path.suffix or suffix_for(filename=path.name, content_type=content_type))
    return upload_bytes(path.read_bytes(), key=key, content_type=content_type, filename=path.name)


def upload_bytes(content: bytes, *, key: str, content_type: str, filename: str = "") -> dict[str, Any]:
    config = load_config()
    if not config:
        raise RuntimeError("OSS is not configured")
    date = dt.datetime.now(dt.UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
    resource = f"/{config.bucket}/{key}"
    signature = sign(
        secret=config.access_key_secret,
        value=f"PUT\n\n{content_type}\n{date}\n{resource}",
    )
    url = object_put_url(config, key)
    request = Request(
        url,
        data=content,
        method="PUT",
        headers={
            "Authorization": f"OSS {config.access_key_id}:{signature}",
            "Content-Type": content_type,
            "Date": date,
            "Content-Length": str(len(content)),
        },
    )
    with urlopen(request, timeout=30) as response:
        status = response.status
        if status < 200 or status >= 300:
            raise RuntimeError(f"OSS upload failed: {status}")
    return {
        "url": public_url(config, key),
        "ossUri": f"oss://{config.bucket}/{key}",
        "key": key,
        "contentType": content_type,
        "filename": filename,
        "size": len(content),
    }


def object_put_url(config: OssConfig, key: str) -> str:
    endpoint = config.endpoint
    if not endpoint.startswith(("http://", "https://")):
        endpoint = f"https://{endpoint}"
    parsed = urlparse(endpoint)
    host = parsed.netloc
    if not host.startswith(f"{config.bucket}."):
        host = f"{config.bucket}.{host}"
    path = f"/{quote(key, safe='/')}"
    return parsed._replace(netloc=host, path=path, params="", query="", fragment="").geturl()


def public_url(config: OssConfig, key: str) -> str:
    if config.download_base_url:
        return f"{config.download_base_url.rstrip('/')}/{quote(key, safe='/')}"
    return object_put_url(config, key)


def make_object_key(*, username: str, kind: str, suffix: str) -> str:
    today = dt.datetime.now(dt.UTC).strftime("%Y/%m/%d")
    clean_user = safe_segment(username or "guest")
    clean_kind = safe_segment(kind or "uploads")
    clean_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return f"{ROOT_PREFIX}/{clean_user}/{clean_kind}/{today}/{uuid.uuid4().hex}{clean_suffix.lower()}"


def sign(*, secret: str, value: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def guess_content_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def suffix_for(*, filename: str, content_type: str) -> str:
    suffix = Path(filename).suffix
    if suffix:
        return suffix
    guessed = mimetypes.guess_extension(content_type)
    return guessed or ".bin"


def safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return cleaned[:60] or "item"
