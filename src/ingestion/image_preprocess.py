"""
Retail Sentiment Intelligence — Image Preprocessor
====================================================
Pure-Python plumbing for the vision branch of the pipeline. No models here.

Responsibilities (and only these):
  1. Decide whether a post carries an image worth processing.
  2. Fetch the image bytes with a hard size + time cap.
  3. Normalize: resize so the longest edge ≤ max_dim, re-encode to JPEG.
  4. Cache to disk under data/image_cache/<post_id>.jpg.
  5. Hand the cache path off to the vision model in src/analysis/vision.py.

Designed to fail soft: any error returns None and gets logged. The pipeline
keeps running text-only for that post.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

from src.utils.config import ModelStageConfig
from src.utils.logger import get_logger

log = get_logger("image_preprocess")

_IMAGE_DOMAINS = ("i.redd.it", "imgur.com", "i.imgur.com", "preview.redd.it")
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def has_image(unit: dict) -> bool:
    """True if a post smells like it has a worth-captioning image."""
    if unit.get("is_video"):
        return False
    if unit.get("post_hint") == "image":
        return True
    if unit.get("is_gallery"):
        return True
    url = (unit.get("media_url") or unit.get("url") or "").lower()
    if any(d in url for d in _IMAGE_DOMAINS):
        return True
    if any(url.endswith(ext) for ext in _IMAGE_EXT):
        return True
    return False


def pick_image_url(unit: dict) -> Optional[str]:
    """Best-guess at the highest-fidelity image URL on a normalized post."""
    for key in ("media_url", "image_url", "thumbnail_url"):
        v = unit.get(key)
        if v:
            return v
    url = unit.get("url") or ""
    if any(d in url.lower() for d in _IMAGE_DOMAINS):
        return url
    if any(url.lower().endswith(ext) for ext in _IMAGE_EXT):
        return url
    return None


def cached_path(post_id: str, cache_dir: str) -> Path:
    return Path(cache_dir) / f"{post_id}.jpg"


def fetch_and_normalize(
    post_id: str,
    image_url: str,
    cfg: ModelStageConfig,
) -> Optional[Path]:
    """Download, resize, JPEG-encode, cache. Returns the cache path or None.

    Pure Python — no model is loaded here. Hard caps on bytes + time keep
    pathological posts (10 MB animated GIFs, slow servers) from stalling the
    pipeline.
    """
    cache_dir = Path(cfg.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{post_id}.jpg"

    # Idempotent — if we already cached this one, reuse it.
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path

    # 1. Fetch with caps
    try:
        with requests.get(image_url, timeout=cfg.fetch_timeout, stream=True) as r:
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "").lower()
            if "image" not in ctype:
                log.info("image_skip_non_image", post_id=post_id, ctype=ctype)
                return None
            buf = io.BytesIO()
            total = 0
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > cfg.max_image_bytes:
                    log.info("image_skip_too_large", post_id=post_id, bytes=total)
                    return None
                buf.write(chunk)
    except Exception as e:
        # Common, expected failures — the URL is dead or throttled. Demote
        # to INFO so the log isn't dominated by them. Only truly unexpected
        # errors (5xx, network stack, decode) stay at WARNING.
        msg = str(e)
        is_expected = any(code in msg for code in (
            "404 Client Error",   # Deleted / removed post
            "403 Client Error",   # Forbidden (private / age-gated)
            "410 Client Error",   # Gone
            "429 Client Error",   # Rate limit (esp. imgur)
        ))
        level = log.info if is_expected else log.warning
        level("image_fetch_failed", post_id=post_id, url=image_url[:80], error=msg)
        return None

    # 2. Resize + re-encode to JPEG
    try:
        buf.seek(0)
        img = Image.open(buf)
        # Animated formats (GIF) — take first frame only.
        if getattr(img, "is_animated", False):
            img.seek(0)
        img = img.convert("RGB")
        max_dim = cfg.max_image_dimension or 768
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / float(max(w, h))
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        img.save(out_path, format="JPEG", quality=85, optimize=True)
    except Exception as e:
        log.warning("image_normalize_failed", post_id=post_id, error=str(e))
        try:
            os.unlink(out_path)
        except FileNotFoundError:
            pass
        return None

    log.info("image_cached", post_id=post_id, path=str(out_path), size=out_path.stat().st_size)
    return out_path


# ─── Rich-status variant used by _enrich_with_vision so the outcome (fetched,
#     deleted, throttled, ...) is preserved on the post itself and can be shown
#     in the Pipeline UI. Wraps fetch_and_normalize; identical logic, extra
#     bookkeeping.
def fetch_with_status(
    post_id: str,
    image_url: str,
    cfg: ModelStageConfig,
) -> tuple[Optional[Path], dict]:
    """Same as fetch_and_normalize but also returns a status dict.

    Status dict fields:
      - status:       'fetched' | 'deleted' | 'forbidden' | 'gone' | 'throttled'
                      | 'too_large' | 'not_image' | 'server_error'
                      | 'connection_error' | 'decode_error' | 'client_error'
      - http_code:    int if known (from HTTPError), else None
      - error:        Short error message (truncated)
      - checked_at:   ISO-8601 UTC timestamp of the fetch attempt
    """
    from datetime import datetime, timezone
    cache_dir = Path(cfg.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{post_id}.jpg"
    checked_at = datetime.now(timezone.utc).isoformat()

    # Cache hit — already have it, no network call.
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path, {
            "status": "fetched",
            "http_code": None,
            "error": None,
            "checked_at": checked_at,
            "cached": True,
        }

    try:
        with requests.get(image_url, timeout=cfg.fetch_timeout, stream=True) as r:
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "").lower()
            if "image" not in ctype:
                log.info("image_skip_non_image", post_id=post_id, ctype=ctype)
                return None, {"status": "not_image", "http_code": r.status_code,
                              "error": f"content-type={ctype}", "checked_at": checked_at}
            buf = io.BytesIO()
            total = 0
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > cfg.max_image_bytes:
                    log.info("image_skip_too_large", post_id=post_id, bytes=total)
                    return None, {"status": "too_large", "http_code": r.status_code,
                                  "error": f"bytes>{cfg.max_image_bytes}", "checked_at": checked_at}
                buf.write(chunk)
    except requests.HTTPError as e:
        code = getattr(e.response, "status_code", None)
        status_map = {404: "deleted", 410: "gone", 403: "forbidden", 429: "throttled"}
        status = status_map.get(code, ("client_error" if code and code < 500 else "server_error"))
        is_expected = code in status_map
        level = log.info if is_expected else log.warning
        level("image_fetch_failed", post_id=post_id, url=image_url[:80], error=str(e))
        return None, {"status": status, "http_code": code, "error": str(e)[:200], "checked_at": checked_at}
    except Exception as e:
        # Connection reset, DNS, timeout, TLS handshake, etc.
        log.warning("image_fetch_failed", post_id=post_id, url=image_url[:80], error=str(e))
        return None, {"status": "connection_error", "http_code": None,
                      "error": str(e)[:200], "checked_at": checked_at}

    # Normalize step
    try:
        buf.seek(0)
        img = Image.open(buf)
        if getattr(img, "is_animated", False):
            img.seek(0)
        img = img.convert("RGB")
        max_dim = cfg.max_image_dimension or 768
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / float(max(w, h))
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        img.save(out_path, format="JPEG", quality=85, optimize=True)
    except Exception as e:
        log.warning("image_normalize_failed", post_id=post_id, error=str(e))
        try:
            os.unlink(out_path)
        except FileNotFoundError:
            pass
        return None, {"status": "decode_error", "http_code": None,
                      "error": str(e)[:200], "checked_at": checked_at}

    log.info("image_cached", post_id=post_id, path=str(out_path), size=out_path.stat().st_size)
    return out_path, {
        "status": "fetched",
        "http_code": None,
        "error": None,
        "checked_at": checked_at,
        "cached": False,
    }
