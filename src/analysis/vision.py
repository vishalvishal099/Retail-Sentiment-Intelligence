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
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

import requests

from src.utils.config import ModelStageConfig
from src.utils.logger import get_logger

log = get_logger("vision")

_OLLAMA_URL_DEFAULT = "http://localhost:11434"


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


# Module-level singleton — caption() loads the model into Ollama's RAM on the
# first call, then subsequent calls are warm (~3s for gemma3:4b on M-series).
_client: Optional[OllamaVisionClient] = None


def get_vision_client(cfg: ModelStageConfig, ollama_url: str = _OLLAMA_URL_DEFAULT) -> OllamaVisionClient:
    global _client
    if _client is None or _client.cfg is not cfg:
        _client = OllamaVisionClient(cfg, ollama_url=ollama_url)
    return _client
