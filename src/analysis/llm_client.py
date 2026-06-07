"""
Retail Sentiment Intelligence — Model-Agnostic LLM Client
Supports: HuggingFace (free), Azure OpenAI, OpenAI.
Code is modular per R3.3 — swap models by changing config.
"""

import json
from abc import ABC, abstractmethod
from typing import Optional

from src.utils.config import LLMConfig
from src.utils.cost_tracker import CostTracker
from src.utils.logger import get_logger

log = get_logger("llm_client")


class BaseLLMClient(ABC):
    """Abstract LLM client interface."""

    @abstractmethod
    def analyze_sentiment(self, text: str) -> dict:
        """Analyze sentiment of a single text. Returns structured result."""
        ...

    @abstractmethod
    def analyze_batch(self, texts: list[str]) -> list[dict]:
        """Analyze a batch of texts."""
        ...

    @abstractmethod
    def check_credibility(self, text: str, metadata: dict) -> dict:
        """Trust/credibility check on a post."""
        ...

    def generate_reply(
        self,
        post_title: str,
        post_text: str,
        subreddit: str,
        author: str,
        aspects: list[str],
        examples: Optional[list[dict]] = None,
    ) -> dict:
        """Draft a personalized customer-care reply to a negative post.

        `examples` is a list of past human-validated replies used as few-shot
        prompts so the model adapts to the brand's preferred tone over time.
        Each example: {"post_text": str, "reply_text": str}.

        Returns: {"reply": str, "model_used": str, "source": "llm"|"template"}.
        Subclasses should override; the default uses a smart template.
        """
        return _template_reply(post_title, post_text, subreddit, author, aspects)

    def generate_reply_pair(
        self,
        post_title: str,
        post_text: str,
        subreddit: str,
        author: str,
        aspects: list[str],
        examples: Optional[list[dict]] = None,
    ) -> dict:
        """Draft TWO side-by-side reply candidates so the analyst can pick
        whichever sounds better. Subclasses can override to provide one
        LLM-generated draft + one smart-composer draft. Default returns two
        differently-seeded smart-composer drafts."""
        import random as _random
        import time as _time
        seed_a = int(_time.time() * 1000) ^ _random.randint(0, 1_000_000)
        seed_b = seed_a ^ _random.randint(1, 999_999)
        text_a = _smart_compose_reply(
            post_title, post_text, subreddit, author, aspects, examples, seed=seed_a
        )
        text_b = _smart_compose_reply(
            post_title, post_text, subreddit, author, aspects, examples, seed=seed_b
        )
        return {
            "drafts": [
                {"reply": text_a, "model_used": "smart-composer", "source": "smart-template"},
                {"reply": text_b, "model_used": "smart-composer", "source": "smart-template"},
            ]
        }


    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @property
    @abstractmethod
    def model_version(self) -> str:
        ...


# Module-level template used as a safety net when no generative LLM is available
_ASPECT_LABELS = {
    "delivery": "your delivery / pickup experience",
    "product_quality": "the quality of what you received",
    "returns": "your return or refund issue",
    "customer_support": "the support you got",
    "pricing": "the pricing concern you raised",
    "app_website": "the app or website issue you ran into",
    "store experience": "your in-store experience",
    "online/app": "the online / app issue",
    "delivery/pickup": "your delivery / pickup experience",
    "customer service": "the support you got",
    "product quality": "the quality of what you received",
}

# Words/phrases we look for in the post body to make replies more specific.
_COMPLAINT_KEYWORDS = {
    "refund": "refund",
    "refunded": "refund",
    "return": "return",
    "returns": "return",
    "broken": "damaged item",
    "damaged": "damaged item",
    "missing": "missing item",
    "wrong": "wrong item",
    "expired": "expired product",
    "rotten": "spoiled product",
    "spoiled": "spoiled product",
    "moldy": "spoiled product",
    "late": "late delivery",
    "delayed": "delayed delivery",
    "never arrived": "missing delivery",
    "never came": "missing delivery",
    "cancelled": "cancelled order",
    "canceled": "cancelled order",
    "charged": "billing issue",
    "charge": "billing issue",
    "overcharged": "overcharge",
    "scammed": "this experience",
    "rude": "the staff interaction",
    "manager": "the management issue",
    "associate": "the associate interaction",
    "register": "the checkout issue",
    "self-checkout": "the self-checkout issue",
    "pickup": "the pickup",
    "delivery": "the delivery",
    "order": "your order",
    "app": "the app issue",
    "website": "the site issue",
}


def _extract_topic(post_title: str, post_text: str) -> str:
    """Find the most specific complaint hook from the post (a noun phrase the
    customer actually used). Falls back to empty string if nothing matches."""
    blob = f"{post_title or ''} {post_text or ''}".lower()
    for kw, phrase in _COMPLAINT_KEYWORDS.items():
        if kw in blob:
            return phrase
    return ""


def _smart_compose_reply(
    post_title: str,
    post_text: str,
    subreddit: str,
    author: str,
    aspects: list[str],
    examples: Optional[list[dict]] = None,
    seed: Optional[int] = None,
) -> str:
    """Compose a varied, customer-specific reply WITHOUT any LLM.

    Combines: extracted complaint topic + aspect phrase + a randomly chosen
    opening / acknowledgment / action / closing. Two consecutive calls on the
    same post will produce different replies because we randomize the phrase
    pools every time.
    """
    import random
    rng = random.Random(seed)

    handle = (author or "there").lstrip("u/")

    # Aspect phrase
    aspect_phrase = ""
    for asp in aspects or []:
        if asp in _ASPECT_LABELS:
            aspect_phrase = _ASPECT_LABELS[asp]
            break
    if not aspect_phrase and aspects:
        aspect_phrase = f"the issue with {aspects[0].replace('_', ' ')}"

    topic = _extract_topic(post_title, post_text)
    snippet = (post_title or "").strip()
    if not snippet:
        for line in (post_text or "").split("\n"):
            line = line.strip()
            if 25 <= len(line) <= 160:
                snippet = line
                break
    snippet = snippet[:140]

    # Pools — every category has 4-6 alternatives so consecutive replies differ
    openings = [
        f"Hi u/{handle},",
        f"Hey u/{handle} —",
        f"Hi u/{handle} — thanks for flagging this.",
        f"u/{handle}, thanks for reaching out.",
        f"Hey u/{handle}, appreciate you sharing this.",
    ]
    acknowledgments_with_topic = [
        f"we're really sorry to hear about {topic}.",
        f"that's not the experience we want anyone to have with {topic}.",
        f"completely understand the frustration around {topic}.",
        f"this isn't the standard we hold ourselves to when it comes to {topic}.",
        f"{topic.capitalize()} like this absolutely shouldn't happen.",
    ]
    acknowledgments_with_aspect = [
        f"we're sorry to hear about {aspect_phrase}.",
        f"{aspect_phrase.capitalize()} should never go this way.",
        f"this isn't what we'd expect from {aspect_phrase}.",
        f"we hear you on {aspect_phrase}, and that's on us to fix.",
        f"that sounds genuinely frustrating regarding {aspect_phrase}.",
    ]
    acknowledgments_generic = [
        "we're sorry this fell short of what you expected.",
        "this is not the experience we want our customers to have.",
        "we hear you, and that's not okay.",
        "thanks for taking the time to call this out — it matters.",
        "we appreciate the honesty, and we want to make it right.",
    ]
    actions = [
        "Can you DM us your order number (or store/date) so we can look into it directly?",
        "If you DM us a few details (order #, store, or pickup window), we'll dig in right away.",
        "Send us a DM with the order details and we'll get someone on it.",
        "Drop us a private message with the order # or store info and we'll take it from here.",
        "DM us the details when you have a moment and we'll start looking into the specifics.",
    ]
    closings = [
        "— Walmart Care",
        "Thanks, Walmart Care",
        "— The Walmart Care team",
        "Appreciate you, — Walmart Care",
        "— Walmart Care 💙",
    ]

    opening = rng.choice(openings)
    if topic:
        ack = rng.choice(acknowledgments_with_topic)
    elif aspect_phrase:
        ack = rng.choice(acknowledgments_with_aspect)
    else:
        ack = rng.choice(acknowledgments_generic)
    action = rng.choice(actions)
    closing = rng.choice(closings)

    # Subtle nod to past tone — borrow a closing emoji/sign-off pattern from
    # the most recent posted reply when available.
    if examples:
        for ex in examples:
            ref = (ex.get("reply_text") or "").strip()
            if ref and ref.endswith(("!", "💙", "❤️", "🙏")):
                closing = closing.rstrip(".") + ref[-1]
                break

    return f"{opening} {ack} {action} {closing}"


def _template_reply(
    post_title: str, post_text: str, subreddit: str, author: str, aspects: list[str]
) -> dict:
    """Customer-specific reply composed from real post content. Marked as
    `source: "smart-template"` so the UI can be transparent about whether it
    came from an LLM or our composer."""
    body = _smart_compose_reply(post_title, post_text, subreddit, author, aspects)
    return {"reply": body, "model_used": "smart-composer", "source": "smart-template"}



class HuggingFaceSentimentClient(BaseLLMClient):
    """
    Free OSS model using HuggingFace transformers.
    Default: cardiffnlp/twitter-roberta-base-sentiment-latest
    + Zero-shot classification for aspect extraction.
    """

    # Default retail aspects per requirements
    ASPECTS = [
        "pricing",
        "product quality",
        "customer service",
        "store experience",
        "online/app",
        "delivery/pickup",
    ]

    def __init__(self, config: LLMConfig, cost_tracker: Optional[CostTracker] = None):
        self.config = config
        self.cost_tracker = cost_tracker
        self._pipeline = None
        self._zero_shot = None
        self._model_name = config.model
        log.info("hf_client_init", model=self._model_name)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return "v1.0-hf"

    def _get_pipeline(self):
        if self._pipeline is None:
            from transformers import pipeline
            self._pipeline = pipeline(
                "sentiment-analysis",
                model=self._model_name,
                tokenizer=self._model_name,
                max_length=512,
                truncation=True,
            )
        return self._pipeline

    def _get_zero_shot(self):
        """Lazy-load zero-shot classification pipeline for aspects.

        Model is config-driven: `models.aspects.model` in config/models.yaml.
        Default is MoritzLaurer/deberta-v3-base-zeroshot-v2.0, which beats the
        old facebook/bart-large-mnli on every zero-shot benchmark and is ~3x
        smaller. Falls back to BART if DeBERTa fails to load.
        """
        if self._zero_shot is None:
            from transformers import pipeline
            try:
                from src.utils.config import load_config
                _cfg = load_config()
                aspect_model = _cfg.models.aspects.model or "MoritzLaurer/deberta-v3-base-zeroshot-v2.0"
                fallback = _cfg.models.aspects.fallback_model or "facebook/bart-large-mnli"
            except Exception:
                aspect_model = "MoritzLaurer/deberta-v3-base-zeroshot-v2.0"
                fallback = "facebook/bart-large-mnli"
            try:
                self._zero_shot = pipeline(
                    "zero-shot-classification",
                    model=aspect_model,
                    max_length=512,
                    truncation=True,
                )
                log.info("aspect_model_loaded", model=aspect_model)
            except Exception as e:
                log.warning("aspect_model_load_failed", model=aspect_model, error=str(e), fallback=fallback)
                self._zero_shot = pipeline(
                    "zero-shot-classification",
                    model=fallback,
                    max_length=512,
                    truncation=True,
                )
        return self._zero_shot

    def _get_reply_generator(self):
        """Lazy-load a small instruction-tuned generator for drafting replies.

        Uses google/flan-t5-base (~250MB). Loaded only when the first reply is
        requested, so this cost is not paid by the rest of the pipeline.
        """
        if getattr(self, "_reply_gen", None) is None:
            from transformers import pipeline
            self._reply_gen = pipeline(
                "text2text-generation",
                model="google/flan-t5-base",
                max_length=220,
            )
        return self._reply_gen

    def generate_reply(
        self,
        post_title: str,
        post_text: str,
        subreddit: str,
        author: str,
        aspects: list[str],
        examples: Optional[list[dict]] = None,
    ) -> dict:
        """Customer-specific reply.

        Strategy:
          1. Generate N candidate replies with FLAN-T5 at varied temperatures.
          2. Score each candidate (length, doesn't parrot the input, mentions
             relevant complaint nouns).
          3. If any candidate passes the quality bar → return the best one.
          4. Otherwise → use the smart composer (which is now itself varied
             and customer-specific, not a static template).

        The smart composer is also re-seeded per call so consecutive
        Regenerate clicks produce different replies, fixing the "always the
        same reply" problem the user reported.
        """
        import random as _random
        import time as _time

        handle = (author or "there").lstrip("u/")
        complaint = (post_title or "").strip()
        body = (post_text or "").strip()
        if body and body != complaint:
            complaint = f"{complaint}. {body}" if complaint else body
        complaint = complaint[:350]
        aspect_str = aspects[0].replace("_", " ") if aspects else "experience"

        # Style hint from past replies — fed as a single tone reference.
        tone_hint = ""
        if examples:
            for ex in examples:
                if ex.get("reply_text"):
                    tone_hint = (
                        f" Match the tone of this past reply: "
                        f"'{ex['reply_text'][:200]}'."
                    )
                    break

        prompt = (
            "You are Walmart Care responding to an unhappy customer on Reddit. "
            "Write a short, empathetic, 2-sentence reply that acknowledges their "
            f"specific {aspect_str} issue and offers to help via DM. Do not repeat "
            f"the customer's words verbatim.{tone_hint}\n\n"
            f"Customer complaint: {complaint}\n\n"
            "Reply:"
        )

        best_candidate: Optional[str] = None
        best_score = -1
        candidates_tried = 0
        seen_candidates: set[str] = set()
        try:
            gen = self._get_reply_generator()
            # Try a few different sampling configurations — small models
            # produce more variety this way than with a single call.
            sampling_configs = [
                {"temperature": 0.7, "top_p": 0.92},
                {"temperature": 0.95, "top_p": 0.95},
                {"temperature": 1.1, "top_p": 0.98},
            ]
            for cfg in sampling_configs:
                candidates_tried += 1
                try:
                    out = gen(
                        prompt,
                        do_sample=True,
                        max_new_tokens=120,
                        **cfg,
                    )
                    raw = (out[0].get("generated_text") or "").strip()
                except Exception as inner_e:
                    log.warning("flan_sample_failed", error=str(inner_e))
                    continue

                # Strip the prompt echoes FLAN-T5-base produces.
                text = raw
                for marker in (
                    "Reply:",
                    "Customer complaint:",
                    "Customer post:",
                    "Walmart Care reply:",
                ):
                    if marker in text:
                        text = text.split(marker, 1)[1].strip()
                text = text.split("\n\n")[0].strip()
                seen_candidates.add(text)

                score = self._score_reply(text, complaint, aspect_str)
                if score > best_score:
                    best_score = score
                    best_candidate = text

            # If FLAN-T5 produced identical text every time, the model has
            # collapsed onto a canonical response — that's a sign it's not
            # actually generating per-post content. Fall back to the smart
            # composer which has real per-call variety.
            identical_collapse = (
                candidates_tried >= 2 and len(seen_candidates) == 1
            )

            # Quality bar — score ≥ 3 means it's at least non-parroting,
            # reasonably long, and mentions something topic-relevant.
            if best_candidate and best_score >= 3 and not identical_collapse:
                text = best_candidate
                if not text.lower().startswith(("hi", "hey", "hello")):
                    text = f"Hi u/{handle} — {text}"
                if (
                    "walmart care" not in text.lower()
                    and "— walmart" not in text.lower()
                ):
                    text = text.rstrip(". ") + ". — Walmart Care"

                if self.cost_tracker:
                    self.cost_tracker.record(
                        provider="huggingface",
                        model="google/flan-t5-base",
                        input_tokens=len(prompt.split()) * candidates_tried,
                        output_tokens=len(text.split()),
                        stage="reply_generation",
                    )

                return {
                    "reply": text,
                    "model_used": "google/flan-t5-base",
                    "source": "llm",
                    "candidates_tried": candidates_tried,
                    "quality_score": best_score,
                }
        except Exception as e:
            log.warning("reply_generation_failed", error=str(e))

        # Smart-composer fallback. Seed with current time + a random nonce so
        # back-to-back Regenerate clicks produce different replies.
        seed = int(_time.time() * 1000) ^ _random.randint(0, 1_000_000)
        body_text = _smart_compose_reply(
            post_title, post_text, subreddit, author, aspects, examples, seed=seed
        )
        if self.cost_tracker:
            self.cost_tracker.record(
                provider="local",
                model="smart-composer",
                input_tokens=0,
                output_tokens=len(body_text.split()),
                stage="reply_generation",
            )
        return {
            "reply": body_text,
            "model_used": "smart-composer",
            "source": "smart-template",
            "candidates_tried": candidates_tried,
            "quality_score": best_score if best_score >= 0 else 0,
        }

    def _score_reply(self, text: str, complaint: str, aspect_str: str) -> int:
        """Score a FLAN-T5 candidate reply. Higher = better.

        Rules:
          +2 length is 40–400 chars (sweet spot for a reply)
          +1 mentions the aspect word or a complaint-keyword from the post
          +1 contains an empathy / action verb
          -3 starts with 'customer', 'u/there', or 'reply' (prompt leakage)
          -3 first 40 chars of the input appear in the reply (parroting)
        """
        if not text:
            return -10
        t = text.lower()
        score = 0
        if 40 <= len(text) <= 400:
            score += 2
        if aspect_str.lower() in t or any(
            kw in t for kw in ("refund", "order", "store", "delivery", "pickup", "team")
        ):
            score += 1
        if any(
            v in t for v in ("sorry", "apologize", "understand", "make it right", "help", "look into", "dm")
        ):
            score += 1
        if t.startswith(("customer", "u/there", "reply", "walmart care reply")):
            score -= 3
        if complaint and complaint[:40].lower() in t:
            score -= 3
        return score

    def generate_reply_pair(
        self,
        post_title: str,
        post_text: str,
        subreddit: str,
        author: str,
        aspects: list[str],
        examples: Optional[list[dict]] = None,
    ) -> dict:
        """Return two side-by-side drafts: one from the smart composer (always
        varied, content-aware) and one from FLAN-T5 (if available). The
        analyst picks whichever sounds better in the UI."""
        import random as _random
        import time as _time

        # Draft A — smart composer, always available, always varied.
        seed = int(_time.time() * 1000) ^ _random.randint(0, 1_000_000)
        draft_a_text = _smart_compose_reply(
            post_title, post_text, subreddit, author, aspects, examples, seed=seed
        )
        draft_a = {
            "reply": draft_a_text,
            "model_used": "smart-composer",
            "source": "smart-template",
            "label": "Smart composer (content-aware)",
        }

        # Draft B — FLAN-T5. Reuse generate_reply for consistency. It may
        # return a real LLM output or fall back to a smart-composer reply
        # itself; in either case we surface the actual source.
        try:
            draft_b_full = self.generate_reply(
                post_title, post_text, subreddit, author, aspects, examples
            )
            draft_b = {
                "reply": draft_b_full.get("reply", ""),
                "model_used": draft_b_full.get("model_used", "google/flan-t5-base"),
                "source": draft_b_full.get("source", "llm"),
                "label": "Neural model (FLAN-T5)",
                "quality_score": draft_b_full.get("quality_score"),
                "candidates_tried": draft_b_full.get("candidates_tried"),
            }
        except Exception as e:
            log.warning("draft_b_generation_failed", error=str(e))
            seed2 = seed ^ _random.randint(1, 999_999)
            draft_b = {
                "reply": _smart_compose_reply(
                    post_title, post_text, subreddit, author, aspects, examples, seed=seed2
                ),
                "model_used": "smart-composer",
                "source": "smart-template",
                "label": "Smart composer (alt)",
                "error": str(e),
            }

        # Avoid showing two identical drafts: re-roll A if it matches B.
        if draft_a["reply"].strip() == draft_b["reply"].strip():
            seed3 = seed ^ _random.randint(1, 999_999)
            draft_a["reply"] = _smart_compose_reply(
                post_title, post_text, subreddit, author, aspects, examples, seed=seed3
            )

        return {"drafts": [draft_a, draft_b]}





    def _extract_aspects(self, text: str) -> list[dict]:
        """Extract aspects from text using zero-shot classification."""
        try:
            classifier = self._get_zero_shot()
            result = classifier(text[:512], self.ASPECTS, multi_label=True)

            aspects = []
            for label, score in zip(result["labels"], result["scores"]):
                if score > 0.3:  # Only include aspects with reasonable confidence
                    aspects.append({
                        "aspect": label,
                        "confidence": round(score, 3),
                    })
            return aspects[:3]  # Top 3 aspects max
        except Exception as e:
            log.warning("aspect_extraction_failed", error=str(e))
            return []

    def analyze_sentiment(self, text: str) -> dict:
        """Analyze sentiment + aspects using HuggingFace models."""
        pipe = self._get_pipeline()
        result = pipe(text[:512])[0]

        # Map cardiffnlp labels to our 3-class taxonomy
        sentiment = self._map_label(result["label"])
        confidence = result["score"]

        # Extract aspects via zero-shot classification
        aspects = self._extract_aspects(text)
        # Attach per-aspect sentiment
        for asp in aspects:
            asp["sentiment"] = sentiment  # Inherit post-level sentiment

        # Track cost (free model, but track for consistency)
        if self.cost_tracker:
            self.cost_tracker.record(
                provider="huggingface",
                model=self._model_name,
                input_tokens=len(text.split()),
                output_tokens=0,
                stage="analysis",
            )

        return {
            "sentiment": sentiment,
            "sentiment_confidence": confidence,
            "aspects": aspects,
            "key_phrases": [],
            "summary": "",
            "model_used": self._model_name,
            "model_version": self.model_version,
        }

    def analyze_batch(self, texts: list[str]) -> list[dict]:
        """Batch sentiment + aspect analysis."""
        pipe = self._get_pipeline()
        truncated = [t[:512] for t in texts]
        results = pipe(truncated)

        analyzed = []
        for text, result in zip(texts, results):
            sentiment = self._map_label(result["label"])
            aspects = self._extract_aspects(text)
            for asp in aspects:
                asp["sentiment"] = sentiment

            analyzed.append({
                "sentiment": sentiment,
                "sentiment_confidence": result["score"],
                "aspects": aspects,
                "key_phrases": [],
                "summary": "",
                "model_used": self._model_name,
                "model_version": self.model_version,
            })

        if self.cost_tracker:
            total_tokens = sum(len(t.split()) for t in texts)
            self.cost_tracker.record(
                provider="huggingface",
                model=self._model_name,
                input_tokens=total_tokens,
                output_tokens=0,
                stage="analysis",
            )

        return analyzed

    def check_credibility(self, text: str, metadata: dict) -> dict:
        """HF model doesn't do credibility — return neutral score."""
        return {
            "is_genuine": True,
            "credibility_score": 0.5,
            "flags": ["hf_model_no_credibility_check"],
            "reasoning": "HuggingFace sentiment model does not support credibility analysis",
        }

    def _map_label(self, label: str) -> str:
        """Map model-specific labels to our 3-class taxonomy."""
        label_lower = label.lower()
        # cardiffnlp uses: LABEL_0 (negative), LABEL_1 (neutral), LABEL_2 (positive)
        # or: negative, neutral, positive
        if "positive" in label_lower or label_lower == "label_2":
            return "positive"
        elif "negative" in label_lower or label_lower == "label_0":
            return "negative"
        else:
            return "neutral"


class AzureOpenAIClient(BaseLLMClient):
    """
    Azure OpenAI client (gpt-4o-mini).
    Activated when LLM_PROVIDER=azure_openai and credentials are set.
    """

    def __init__(self, config: LLMConfig, cost_tracker: Optional[CostTracker] = None):
        self.config = config
        self.cost_tracker = cost_tracker
        self._client = None
        log.info("azure_openai_client_init", model=config.azure_deployment)

    @property
    def model_name(self) -> str:
        return self.config.azure_deployment

    @property
    def model_version(self) -> str:
        return f"{self.config.azure_deployment}-{self.config.azure_api_version}"

    def _get_client(self):
        if self._client is None:
            from openai import AzureOpenAI
            self._client = AzureOpenAI(
                azure_endpoint=self.config.azure_endpoint,
                api_key=self.config.azure_key,
                api_version=self.config.azure_api_version,
            )
        return self._client

    def analyze_sentiment(self, text: str) -> dict:
        """Full sentiment + aspect analysis via gpt-4o-mini."""
        from src.analysis.prompts import SENTIMENT_ASPECT_SYSTEM_PROMPT, SENTIMENT_ASPECT_FEW_SHOT

        client = self._get_client()
        messages = [
            {"role": "system", "content": SENTIMENT_ASPECT_SYSTEM_PROMPT},
            *SENTIMENT_ASPECT_FEW_SHOT,
            {"role": "user", "content": f"Post: {text}"},
        ]

        response = client.chat.completions.create(
            model=self.config.azure_deployment,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=500,
        )

        result_text = response.choices[0].message.content
        usage = response.usage

        if self.cost_tracker:
            self.cost_tracker.record(
                provider="azure_openai",
                model=self.config.azure_deployment,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                stage="analysis",
            )

        try:
            parsed = json.loads(result_text)
            parsed["model_used"] = self.model_name
            parsed["model_version"] = self.model_version
            return parsed
        except json.JSONDecodeError:
            log.error("json_parse_failed", response=result_text[:200])
            return {
                "sentiment": "neutral",
                "sentiment_confidence": 0.0,
                "aspects": [],
                "key_phrases": [],
                "summary": "",
                "model_used": self.model_name,
                "model_version": self.model_version,
                "parse_error": True,
            }

    def analyze_batch(self, texts: list[str]) -> list[dict]:
        """Analyze batch sequentially (Azure OpenAI doesn't support true batching in a single call)."""
        results = []
        for text in texts:
            results.append(self.analyze_sentiment(text))
        return results

    def check_credibility(self, text: str, metadata: dict) -> dict:
        """LLM-based credibility check."""
        from src.analysis.prompts import TRUST_SYSTEM_PROMPT, TRUST_FEW_SHOT

        client = self._get_client()
        user_msg = f"Post: \"{text}\"\nMetadata: account_age={metadata.get('account_age_days', 0)} days, karma={metadata.get('total_karma', 0)}, posts_last_7d={metadata.get('post_frequency_7d', 0)}"

        messages = [
            {"role": "system", "content": TRUST_SYSTEM_PROMPT},
            *TRUST_FEW_SHOT,
            {"role": "user", "content": user_msg},
        ]

        response = client.chat.completions.create(
            model=self.config.azure_deployment,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=200,
        )

        result_text = response.choices[0].message.content
        usage = response.usage

        if self.cost_tracker:
            self.cost_tracker.record(
                provider="azure_openai",
                model=self.config.azure_deployment,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                stage="trust",
            )

        try:
            return json.loads(result_text)
        except json.JSONDecodeError:
            return {"is_genuine": True, "credibility_score": 0.5, "flags": ["parse_error"], "reasoning": ""}

    def generate_reply(
        self,
        post_title: str,
        post_text: str,
        subreddit: str,
        author: str,
        aspects: list[str],
        examples: Optional[list[dict]] = None,
    ) -> dict:
        """Azure OpenAI reply generation with past validated replies as few-shot."""
        client = self._get_client()
        handle = (author or "there").lstrip("u/")

        system = (
            "You are Walmart Care responding to unhappy customers on Reddit. "
            "Write ONE short, empathetic, customer-specific reply (2-3 sentences). "
            "Reference the actual complaint, offer to help via DM, and sign as "
            "'— Walmart Care'. Never invent facts. Match the tone of the example "
            "replies provided."
        )

        messages: list[dict] = [{"role": "system", "content": system}]
        for ex in (examples or [])[:5]:
            if not ex.get("reply_text"):
                continue
            messages.append({"role": "user", "content": f"Customer post: {ex.get('post_text', '')[:500]}"})
            messages.append({"role": "assistant", "content": ex["reply_text"][:500]})

        post_blob = (post_title + " — " + post_text).strip(" —")[:1500]
        messages.append({
            "role": "user",
            "content": (
                f"Aspects flagged: {', '.join(aspects) or 'general'}\n"
                f"Subreddit: r/{subreddit}\n"
                f"Customer u/{handle} posted: {post_blob}\n"
                f"Reply addressed to u/{handle}:"
            ),
        })

        try:
            response = client.chat.completions.create(
                model=self.config.azure_deployment,
                messages=messages,
                temperature=0.5,
                max_tokens=220,
            )
            text = (response.choices[0].message.content or "").strip()
            usage = response.usage
            if self.cost_tracker and usage:
                self.cost_tracker.record(
                    provider="azure_openai",
                    model=self.config.azure_deployment,
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                    stage="reply_generation",
                )
            if not text:
                fb = _template_reply(post_title, post_text, subreddit, author, aspects)
                fb["source"] = "template_fallback"
                return fb
            return {"reply": text, "model_used": self.model_name, "source": "llm"}
        except Exception as e:
            log.warning("azure_reply_generation_failed", error=str(e))
            fb = _template_reply(post_title, post_text, subreddit, author, aspects)
            fb["source"] = "template_fallback"
            fb["error"] = str(e)
            return fb


class OllamaClient(BaseLLMClient):
    """Local LLM via Ollama (`llama3.1:8b`, `mistral:7b-instruct`, …).

    Only used for reply drafting today; sentiment + aspect extraction stay on
    the HuggingFace pipeline because it's faster and free. If Ollama is
    unreachable, every reply falls back to the smart template — the dashboard
    keeps working.
    """

    def __init__(self, config: LLMConfig, cost_tracker: Optional[CostTracker] = None):
        self.config = config
        self.cost_tracker = cost_tracker
        # Reuse the HF pipeline for sentiment + aspects so we don't lose
        # accuracy — Ollama is purely the reply drafter here.
        self._hf = HuggingFaceSentimentClient(config, cost_tracker)

    @property
    def model_name(self) -> str:
        return self.config.ollama_model

    @property
    def model_version(self) -> str:
        return "ollama"

    # Delegate the analysis methods to HF — keeps the rest of the pipeline
    # behaviour identical when you switch provider to ollama.
    def analyze_sentiment(self, text: str) -> dict:
        return self._hf.analyze_sentiment(text)

    def analyze_batch(self, texts: list[str]) -> list[dict]:
        return self._hf.analyze_batch(texts)

    def check_credibility(self, text: str, metadata: dict) -> dict:
        return self._hf.check_credibility(text, metadata)

    # ---- reply drafting --------------------------------------------------

    def _build_prompt(
        self,
        post_title: str,
        post_text: str,
        subreddit: str,
        author: str,
        aspects: list[str],
        examples: Optional[list[dict]],
    ) -> str:
        aspect_str = ", ".join(aspects) if aspects else "general feedback"
        few_shot = ""
        for ex in (examples or [])[:3]:
            p = (ex.get("post_text") or "").strip().replace("\n", " ")[:240]
            r = (ex.get("reply_text") or "").strip().replace("\n", " ")[:240]
            if p and r:
                few_shot += f"\nExample customer post: {p}\nExample analyst reply: {r}\n"
        post_blob = (post_title + "\n\n" + post_text).strip()[:1200]
        return (
            "You are a senior Walmart customer-care analyst replying on Reddit.\n"
            "Write ONE reply to the customer below. Keep it 2-4 sentences,\n"
            "empathetic, specific to their complaint, no corporate jargon,\n"
            "no hashtags, no emojis. Do NOT promise refunds you can't verify;\n"
            "invite them to DM order details if action is needed. Sign off as\n"
            "a real person, not a brand.\n"
            f"{few_shot}\n"
            f"Subreddit: r/{subreddit}\n"
            f"Customer ({author}) complaint about: {aspect_str}\n"
            f"Customer post:\n{post_blob}\n\n"
            "Reply:"
        )

    def _ollama_generate(self, prompt: str, temperature: float) -> str:
        """Single Ollama call. Returns reply text or '' on any failure."""
        import requests
        url = self.config.ollama_url.rstrip("/") + "/api/generate"
        payload = {
            "model": self.config.ollama_model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.config.ollama_keep_alive,
            "options": {
                "temperature": temperature,
                "num_predict": 220,
                "top_p": 0.9,
            },
        }
        try:
            r = requests.post(url, json=payload, timeout=self.config.ollama_request_timeout)
            r.raise_for_status()
            data = r.json()
            text = (data.get("response") or "").strip()
            # Some models echo "Reply:" — strip it.
            for prefix in ("Reply:", "reply:", "REPLY:"):
                if text.startswith(prefix):
                    text = text[len(prefix):].strip()
            return text
        except Exception as e:
            log.warning("ollama_generate_failed", error=str(e), model=self.config.ollama_model)
            return ""

    def generate_reply(
        self,
        post_title: str,
        post_text: str,
        subreddit: str,
        author: str,
        aspects: list[str],
        examples: Optional[list[dict]] = None,
    ) -> dict:
        prompt = self._build_prompt(post_title, post_text, subreddit, author, aspects, examples)
        text = self._ollama_generate(prompt, temperature=0.5)
        if not text:
            fb = _template_reply(post_title, post_text, subreddit, author, aspects)
            fb["source"] = "template_fallback"
            return fb
        return {"reply": text, "model_used": self.model_name, "source": "llm"}

    def generate_reply_pair(
        self,
        post_title: str,
        post_text: str,
        subreddit: str,
        author: str,
        aspects: list[str],
        examples: Optional[list[dict]] = None,
    ) -> dict:
        """Two side-by-side drafts: one LLM (warm), one smart composer.

        Giving analysts an LLM draft AND a deterministic-template draft lets
        them compare tones and pick the better one. If Ollama is down, both
        slots fall back to differently-seeded smart-composer drafts so the UI
        always renders two options.
        """
        import random as _random
        import time as _time
        prompt = self._build_prompt(post_title, post_text, subreddit, author, aspects, examples)
        llm_text = self._ollama_generate(prompt, temperature=0.55)
        seed = int(_time.time() * 1000) ^ _random.randint(0, 1_000_000)
        composer_text = _smart_compose_reply(
            post_title, post_text, subreddit, author, aspects, examples, seed=seed
        )
        if llm_text:
            drafts = [
                {"reply": llm_text, "model_used": self.model_name, "source": "llm"},
                {"reply": composer_text, "model_used": "smart-composer", "source": "smart-template"},
            ]
        else:
            # Ollama unreachable — keep the analyst-facing contract (always 2)
            seed_b = seed ^ _random.randint(1, 999_999)
            composer_b = _smart_compose_reply(
                post_title, post_text, subreddit, author, aspects, examples, seed=seed_b
            )
            drafts = [
                {"reply": composer_text, "model_used": "smart-composer", "source": "smart-template"},
                {"reply": composer_b, "model_used": "smart-composer", "source": "smart-template"},
            ]
        return {"drafts": drafts}


def create_llm_client(config: LLMConfig, cost_tracker: Optional[CostTracker] = None) -> BaseLLMClient:
    """Factory: create the appropriate LLM client based on config."""
    if config.provider == "azure_openai" and config.azure_endpoint and config.azure_key:
        return AzureOpenAIClient(config, cost_tracker)
    if config.provider == "ollama":
        return OllamaClient(config, cost_tracker)
    # Default to free HuggingFace model
    return HuggingFaceSentimentClient(config, cost_tracker)
