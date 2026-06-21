"""
Retail Sentiment Intelligence — Vision Client
=============================================
Thin wrapper around Ollama's `/api/generate` for image captioning. Lives in
src/analysis/ next to llm_client.py so the abstraction is symmetrical:
text models live in llm_client, vision models live here.

Default model: gemma3:4b (see config/models.yaml `models.vision`).
Fallback: llava:7b if gemma3:4b returns an error or isn't pulled.

Designed to fail soft: any error returns "" and gets logged. The pipeline
keeps running text-only for that post.

Multi-pass mode (enhanced):
  Pass 1: Structure identification (what type of UI/image is this?)
  Pass 2: If screenshot/document → tile into 2-4 crops at native resolution
  Pass 3: Text extraction per tile with targeted prompt
  Merge:  Combine structure + tile captions into a single description
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

from src.utils.config import ModelStageConfig
from src.utils.logger import get_logger

log = get_logger("vision")

_OLLAMA_URL_DEFAULT = "http://localhost:11434"

# ── Prompts for multi-pass pipeline ─────────────────────────────────────────

STRUCTURE_PROMPT = """Identify the TYPE of this image in one word from this list:
screenshot, receipt, product_page, error_dialog, meme, photo, document, app_screen, other.

Then in one sentence describe what UI elements or objects you see (buttons, text areas, products, etc).
Format: TYPE: <type>\nELEMENTS: <brief list>"""

TILE_TEXT_PROMPT = """Read ALL text visible in this cropped region of an image.
Quote every piece of text verbatim, including:
- Error messages (even in red or small font)
- Prices, item numbers, quantities
- Button labels, link text
- Status messages, headers
If no text is visible, say "NO TEXT"."""

MERGE_PROMPT = """Combine these observations about a Walmart-related image into 2-4 clear sentences.

Image type: {structure}

Text found in different regions:
{tile_texts}

Write a factual description that captures: what type of screen/image this is,
all important text (especially errors, prices, status messages), and what the
customer might be complaining about. Do NOT invent details not mentioned above."""


class OllamaVisionClient:
    """Caption an image with a local multimodal Ollama model."""

    def __init__(self, cfg: ModelStageConfig, ollama_url: str = _OLLAMA_URL_DEFAULT):
        self.cfg = cfg
        self.ollama_url = ollama_url.rstrip("/")
        self.model = cfg.model or "gemma3:4b"
        self.fallback = cfg.fallback_model or "llava:7b"

    @property
    def model_name(self) -> str:
        return self.model

    def caption(self, image_path: Path, prompt: Optional[str] = None) -> str:
        """Return a 1-3 sentence caption. Empty string on any failure."""
        if not self.cfg.enabled:
            return ""
        if not image_path or not Path(image_path).exists():
            log.warning("vision_no_image", path=str(image_path))
            return ""

        try:
            img_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        except Exception as e:
            log.warning("vision_read_failed", path=str(image_path), error=str(e))
            return ""

        use_prompt = (prompt or self.cfg.prompt or "Describe this image.").strip()

        # Try primary model, then fallback if it fails / model not found.
        for attempt_model in (self.model, self.fallback):
            if not attempt_model:
                continue
            text = self._call_ollama(attempt_model, use_prompt, img_b64)
            if text:
                if attempt_model != self.model:
                    log.info("vision_used_fallback", primary=self.model, fallback=attempt_model)
                return text
        return ""

    def _call_ollama(self, model: str, prompt: str, image_b64: str) -> str:
        url = f"{self.ollama_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "keep_alive": self.cfg.keep_alive or "10m",
            "options": {
                "temperature": 0.2,
                "num_predict": 220,
            },
        }
        try:
            r = requests.post(url, json=payload, timeout=self.cfg.request_timeout or 60)
            r.raise_for_status()
            data = r.json()
            return (data.get("response") or "").strip()
        except Exception as e:
            log.warning("vision_call_failed", model=model, error=str(e))
            return ""

    # ── Multi-pass enhanced captioning ──────────────────────────────────────

    def caption_enhanced(self, image_path: Path) -> str:
        """
        Multi-pass caption: structure → tile → text-extract → merge.
        Falls back to single-pass caption() on any failure.
        """
        if not self.cfg.enabled:
            return ""
        if not image_path or not Path(image_path).exists():
            return ""

        try:
            img = Image.open(image_path)
        except Exception as e:
            log.warning("vision_enhanced_open_failed", error=str(e))
            return self.caption(image_path)

        # Pass 1: Identify structure/type
        full_b64 = self._image_to_b64(img)
        structure = self._call_ollama(self.model, STRUCTURE_PROMPT, full_b64)
        if not structure:
            return self.caption(image_path)

        log.info("vision_pass1_structure", result=structure[:100])

        # Determine if tiling is needed (screenshots, documents, app screens)
        needs_tiling = any(kw in structure.lower() for kw in [
            "screenshot", "receipt", "app_screen", "error_dialog",
            "document", "product_page",
        ])

        if not needs_tiling:
            # For photos/memes, single-pass is fine
            return self.caption(image_path)

        # Pass 2: Tile the image at native resolution
        tiles = self._create_tiles(img)
        log.info("vision_pass2_tiling", num_tiles=len(tiles))

        # Pass 3: Extract text from each tile
        tile_texts = []
        for i, tile_b64 in enumerate(tiles):
            text = self._call_ollama(self.model, TILE_TEXT_PROMPT, tile_b64)
            if text and "NO TEXT" not in text.upper():
                tile_texts.append(f"Region {i+1}: {text}")

        if not tile_texts:
            # No text found in tiles, fall back to single pass
            return self.caption(image_path)

        # Pass 4: Merge structure + tile texts into final caption
        merge_input = MERGE_PROMPT.format(
            structure=structure,
            tile_texts="\n".join(tile_texts),
        )
        # Merge call uses text-only (no image) with higher token budget
        merged = self._call_ollama_text(self.model, merge_input)
        if merged:
            log.info("vision_enhanced_complete", tiles=len(tile_texts))
            return merged

        # Fallback: concatenate tile texts directly
        return f"[{structure.split(chr(10))[0]}] " + " | ".join(tile_texts)

    def _image_to_b64(self, img: Image.Image) -> str:
        """Convert PIL Image to base64 JPEG string."""
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def _create_tiles(self, img: Image.Image, max_tiles: int = 4) -> list[str]:
        """
        Split image into tiles at native resolution.
        Returns list of base64-encoded tile images.
        Strategy: 2x2 grid for roughly square, 1xN for tall (phone screenshots).
        """
        w, h = img.size
        aspect = w / h

        if aspect > 1.5:
            # Wide image: 2 columns, 1 row
            cols, rows = 2, 1
        elif aspect < 0.6:
            # Tall image (phone screenshot): 1 column, 3-4 rows
            rows = min(max_tiles, max(3, int(h / w)))
            cols = 1
        else:
            # Roughly square: 2x2
            cols, rows = 2, 2

        tile_w = w // cols
        tile_h = h // rows
        tiles = []

        for r in range(rows):
            for c in range(cols):
                box = (c * tile_w, r * tile_h, (c + 1) * tile_w, (r + 1) * tile_h)
                tile = img.crop(box)
                tiles.append(self._image_to_b64(tile))

        return tiles[:max_tiles]

    def _call_ollama_text(self, model: str, prompt: str) -> str:
        """Text-only Ollama call (no image) for the merge step."""
        url = f"{self.ollama_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.cfg.keep_alive or "10m",
            "options": {
                "temperature": 0.3,
                "num_predict": 300,
            },
        }
        try:
            r = requests.post(url, json=payload, timeout=self.cfg.request_timeout or 60)
            r.raise_for_status()
            data = r.json()
            return (data.get("response") or "").strip()
        except Exception as e:
            log.warning("vision_merge_failed", model=model, error=str(e))
            return ""


# Module-level singleton — caption() loads the model into Ollama's RAM on the
# first call, then subsequent calls are warm (~3s for gemma3:4b on M-series).
_client: Optional[OllamaVisionClient] = None


def get_vision_client(cfg: ModelStageConfig, ollama_url: str = _OLLAMA_URL_DEFAULT) -> OllamaVisionClient:
    global _client
    if _client is None or _client.cfg is not cfg:
        _client = OllamaVisionClient(cfg, ollama_url=ollama_url)
    return _client
