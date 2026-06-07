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
        log.warning("image_fetch_failed", post_id=post_id, url=image_url[:80], error=str(e))
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
