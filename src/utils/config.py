"""
Retail Sentiment Intelligence — Configuration Loader
Loads from config/pipeline_config.yaml + environment variables.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import yaml
from dotenv import load_dotenv


# Load .env file if present
load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "pipeline_config.yaml"


@dataclass
class LLMConfig:
    provider: str = "huggingface"
    model: str = "cardiffnlp/twitter-roberta-base-sentiment-latest"
    batch_size: int = 50
    max_retries: int = 3
    timeout_seconds: int = 30
    cost_tracking_enabled: bool = True
    cost_log_file: str = "data/llm_costs.jsonl"
    daily_limit_usd: float = 0.0

    # Azure OpenAI
    azure_endpoint: str = ""
    azure_key: str = ""
    azure_api_version: str = "2024-12-01-preview"
    azure_deployment: str = "gpt-4o-mini"

    # HuggingFace
    hf_token: str = ""

    # Ollama (local llama / mistral via http://host:11434)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "mistral:7b-instruct"
    ollama_keep_alive: str = "10m"
    ollama_request_timeout: int = 60

    # Walmart LLM Gateway (STG/Sandbox)
    wmt_gateway_url: str = "https://wmtllmgateway.stage.walmart.com/wmtllmgateway/v1"
    wmt_gateway_key: str = ""
    wmt_gateway_model: str = "gpt-4o"
    # Required Walmart API routing headers
    wmt_consumer_id: str = "UC09153"
    wmt_svc_name: str = "isl-ai-engine"
    wmt_svc_env: str = "stage"

    # Direct OpenAI fallback — used for reply drafts when the gateway is unreachable
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"


@dataclass
class IngestionConfig:
    interval_minutes: int = 60
    backfill_days: int = 90
    subreddits_file: str = "data/subreddits_clean.csv"
    max_comments_per_post: int = 10
    comment_min_score: int = 3
    comment_max_depth: int = 2
    english_only: bool = True

    # Source provider: "arctic_shift" (no creds, free) | "praw" (needs Reddit API creds)
    fetcher_provider: str = "arctic_shift"

    # Reddit credentials (only required when fetcher_provider == "praw")
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "RetailSentimentIntelligence/1.0"


@dataclass
class StorageConfig:
    provider: str = "sqlite"  # "cosmos" | "sqlite"
    cosmos_endpoint: str = ""
    cosmos_key: str = ""
    cosmos_database: str = "retail_sentiment"
    sqlite_path: str = "data/local.db"


@dataclass
class TrustConfig:
    threshold: float = 0.5
    weight_metadata: float = 0.4
    weight_dedup: float = 0.3
    weight_llm: float = 0.3
    low_trust_action: str = "flag"  # "flag" not "drop"
    # New (Phase 1): combined gate. When formula == "score_x_confidence" the
    # dashboard counts a post as trusted iff trust_score * sentiment_confidence >= tau.
    gate_formula: str = "score_x_confidence"
    gate_tau: float = 0.35
    # New (Phase 1): per-signal metadata weights with a `base` floor so a
    # post with no author metadata still has a chance to clear the gate.
    metadata_weight_age: float = 0.20
    metadata_weight_karma: float = 0.20
    metadata_weight_length: float = 0.30
    metadata_weight_engagement: float = 0.15
    metadata_weight_base: float = 0.15


@dataclass
class AnalysisConfig:
    sentiment_classes: list = field(default_factory=lambda: ["positive", "negative", "neutral"])
    aspects: list = field(default_factory=lambda: [
        "delivery", "product_quality", "returns",
        "customer_support", "pricing", "app_website"
    ])
    confidence_threshold: float = 0.7
    multi_aspect: bool = True


@dataclass
class PrivacyConfig:
    hash_usernames: bool = True
    retention_days: int = 365


@dataclass
class DashboardConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    websocket_enabled: bool = True
    auth: str = "none"


@dataclass
class RedditOAuthConfig:
    """Phase 3 — Reddit OAuth for posting replies.

    `dry_run=True` is the default safe mode: the poster logs the intent and
    returns a mock success without hitting Reddit. Flip to `False` once
    `client_id` and `client_secret` are populated.
    """
    enabled: bool = True
    dry_run: bool = True
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "http://localhost:8000/api/auth/reddit/callback"
    user_agent: str = "RetailSentimentIntelligence/1.0"
    scope: str = "identity submit edit history"
    rate_limit_seconds: int = 600  # 1 reply per 10 min


@dataclass
class SlackChannelConfig:
    enabled: bool = False
    dry_run: bool = True
    webhook_url: str = ""
    channel: str = "#walmart-sentiment-alerts"
    # Concord (Walmart internal Slack) — optional. If concord_org is set,
    # the Slack adapter routes through Concord instead of the webhook_url.
    # Defaults come from .env so setting CONCORD_ORG turns it on globally.
    # Token is read from env $CONCORD_API_TOKEN (never stored in config).
    concord_url: str = field(default_factory=lambda: os.environ.get(
        "CONCORD_API_URL", "https://concord.prod.walmart.com/api/v1/process"))
    concord_org: str = field(default_factory=lambda: os.environ.get("CONCORD_ORG", ""))
    concord_project: str = field(default_factory=lambda: os.environ.get(
        "CONCORD_PROJECT", "magic-slack-notifications"))
    concord_repo: str = field(default_factory=lambda: os.environ.get(
        "CONCORD_REPO", "magic-slack-notifications"))
    concord_entry_point: str = field(default_factory=lambda: os.environ.get(
        "CONCORD_ENTRY_POINT", "postRichMessage"))
    concord_active_profiles: str = field(default_factory=lambda: os.environ.get(
        "CONCORD_ACTIVE_PROFILES", "prod"))
    concord_footer: str = field(default_factory=lambda: os.environ.get(
        "CONCORD_FOOTER", "Retail Sentiment Intelligence"))


@dataclass
class EmailChannelConfig:
    enabled: bool = False
    dry_run: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    use_tls: bool = True
    from_addr: str = "alerts@retail-sentiment.local"
    recipients: list = field(default_factory=list)


@dataclass
class NotificationsConfig:
    """Phase 4 — Slack + Email fan-out for negative-post alerts."""
    auto_lifecycle: bool = True
    confidence_threshold: float = 0.7
    slack: SlackChannelConfig = field(default_factory=SlackChannelConfig)
    email: EmailChannelConfig = field(default_factory=EmailChannelConfig)


# =============================================================================
# Model registry — flexible per-stage model configuration loaded from
# config/models.yaml. Each stage (sentiment, aspects, vision, reply,
# embeddings) is independently swappable: change one YAML line, restart,
# done. See config/models.yaml for documentation of each field.
# =============================================================================


@dataclass
class ModelStageConfig:
    """Generic per-stage config. Knobs that don't apply to a given stage are
    just ignored (e.g. `temperature` on the sentiment stage)."""
    enabled: bool = True
    provider: str = "huggingface"
    model: str = ""
    fallback_model: str = ""
    device: str = "auto"
    max_length: int = 512
    # Sentiment / aspect knobs
    confidence_threshold: float = 0.7
    min_score: float = 0.30
    max_per_post: int = 3
    multi_label: bool = True
    candidate_labels: list = field(default_factory=list)
    # Vision knobs
    max_image_bytes: int = 5_242_880
    max_image_dimension: int = 768
    fetch_timeout: int = 10
    cache_dir: str = "data/image_cache"
    prompt: str = ""
    # When true, the pipeline calls OllamaVisionClient.caption_enhanced()
    # (multi-pass: structure → tile → merge) instead of the single-shot
    # caption(). Slower but produces higher-quality captions for
    # complex screenshots with lots of small text.
    enhanced_captioning: bool = False
    # Reply / generation knobs
    temperature: float = 0.55
    max_tokens: int = 220
    num_drafts: int = 2
    # Ollama-specific
    keep_alive: str = "10m"
    request_timeout: int = 60


@dataclass
class ModelsConfig:
    sentiment: ModelStageConfig = field(default_factory=ModelStageConfig)
    aspects: ModelStageConfig = field(default_factory=ModelStageConfig)
    vision: ModelStageConfig = field(default_factory=lambda: ModelStageConfig(enabled=False))
    reply: ModelStageConfig = field(default_factory=ModelStageConfig)
    embeddings: ModelStageConfig = field(default_factory=lambda: ModelStageConfig(enabled=False))


@dataclass
class ToolsConfig:
    """Non-AI infrastructure choices. Kept here so 'what does the project use?'
    has a single answer (the models.yaml file)."""
    ingestion_source: str = "arctic_shift"
    ingestion_interval_minutes: int = 60
    ingestion_backfill_days: int = 90
    ingestion_english_only: bool = True
    ingestion_min_text_chars: int = 10
    preprocess_dedup: str = "md5_content_hash"
    preprocess_language_detect: str = "langdetect"
    storage_provider: str = "sqlite"
    storage_sqlite_path: str = "data/local.db"
    privacy_hash_usernames: bool = True
    privacy_retention_days: int = 365
    trust_formula: str = "score_x_confidence"
    trust_tau: float = 0.30
    trust_threshold_legacy: float = 0.5
    trust_low_trust_action: str = "flag"


@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    ingestion: IngestionConfig = field(default_factory=IngestionConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    trust: TrustConfig = field(default_factory=TrustConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    # New (Phase 3): per-stage model registry loaded from config/models.yaml
    models: ModelsConfig = field(default_factory=ModelsConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    # Phase 3: Reddit OAuth for live reply posting (dry-run by default).
    reddit_oauth: RedditOAuthConfig = field(default_factory=RedditOAuthConfig)
    # Phase 4: Slack + Email notifications + post lifecycle automation.
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load configuration from YAML + environment variables. Env vars override YAML."""
    path = config_path or CONFIG_PATH
    yaml_data = {}

    if path.exists():
        with open(path) as f:
            yaml_data = yaml.safe_load(f) or {}

    # Build config from YAML defaults + env overrides
    llm_yaml = yaml_data.get("llm", {})
    cost_yaml = llm_yaml.get("cost_tracking", {})

    config = AppConfig(
        llm=LLMConfig(
            ollama_url=os.getenv("OLLAMA_URL", llm_yaml.get("ollama_url", "http://localhost:11434")),
            ollama_model=os.getenv("OLLAMA_MODEL", llm_yaml.get("ollama_model", "mistral:7b-instruct")),
            ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", llm_yaml.get("ollama_keep_alive", "10m")),
            ollama_request_timeout=int(os.getenv("OLLAMA_REQUEST_TIMEOUT", str(llm_yaml.get("ollama_request_timeout", 60)))),
            provider=os.getenv("LLM_PROVIDER", llm_yaml.get("provider", "huggingface")),
            model=os.getenv("LLM_MODEL", llm_yaml.get("model", "cardiffnlp/twitter-roberta-base-sentiment-latest")),
            batch_size=int(os.getenv("BATCH_SIZE", llm_yaml.get("batch_size", 50))),
            max_retries=llm_yaml.get("max_retries", 3),
            timeout_seconds=llm_yaml.get("timeout_seconds", 30),
            cost_tracking_enabled=cost_yaml.get("enabled", True),
            cost_log_file=cost_yaml.get("log_file", "data/llm_costs.jsonl"),
            daily_limit_usd=cost_yaml.get("daily_limit_usd", 0.0),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            azure_key=os.getenv("AZURE_OPENAI_KEY", ""),
            azure_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
            hf_token=os.getenv("HF_TOKEN", ""),
            wmt_gateway_url=os.getenv("WMT_LLM_GATEWAY_URL", "https://wmtllmgateway.stage.walmart.com/v1"),
            wmt_gateway_key=os.getenv("WMT_LLM_GATEWAY_KEY", ""),
            wmt_gateway_model=os.getenv("WMT_LLM_GATEWAY_MODEL", "gpt-4o-mini"),
            wmt_consumer_id=os.getenv("WMT_CONSUMER_ID", ""),
            wmt_svc_name=os.getenv("WMT_SVC_NAME", "WMTLLMGATEWAY"),
            wmt_svc_env=os.getenv("WMT_SVC_ENV", "stage"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        ),
        ingestion=IngestionConfig(
            interval_minutes=int(os.getenv("INGESTION_INTERVAL_MINUTES", yaml_data.get("ingestion", {}).get("interval_minutes", 60))),
            backfill_days=int(os.getenv("BACKFILL_DAYS", yaml_data.get("ingestion", {}).get("backfill_days", 90))),
            subreddits_file=os.getenv("SUBREDDITS_FILE", yaml_data.get("ingestion", {}).get("subreddits_file", "data/subreddits_clean.csv")),
            max_comments_per_post=int(os.getenv("MAX_COMMENTS_PER_POST", yaml_data.get("ingestion", {}).get("max_comments_per_post", 10))),
            comment_min_score=int(os.getenv("COMMENT_MIN_SCORE", yaml_data.get("ingestion", {}).get("comment_min_score", 3))),
            comment_max_depth=int(os.getenv("COMMENT_MAX_DEPTH", yaml_data.get("ingestion", {}).get("comment_max_depth", 2))),
            english_only=yaml_data.get("ingestion", {}).get("english_only", True),
            fetcher_provider=os.getenv("FETCHER_PROVIDER", yaml_data.get("ingestion", {}).get("fetcher_provider", "arctic_shift")),
            reddit_client_id=os.getenv("REDDIT_CLIENT_ID", ""),
            reddit_client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
            reddit_user_agent=os.getenv("REDDIT_USER_AGENT", "RetailSentimentIntelligence/1.0"),
        ),
        storage=StorageConfig(
            provider=yaml_data.get("storage", {}).get("provider", "sqlite"),
            cosmos_endpoint=os.getenv("COSMOS_ENDPOINT", ""),
            cosmos_key=os.getenv("COSMOS_KEY", ""),
            cosmos_database=os.getenv("COSMOS_DATABASE", "retail_sentiment"),
            sqlite_path=yaml_data.get("storage", {}).get("sqlite", {}).get("path", "data/local.db"),
        ),
        trust=TrustConfig(
            threshold=float(os.getenv("TRUST_THRESHOLD", yaml_data.get("trust", {}).get("threshold", 0.5))),
            weight_metadata=yaml_data.get("trust", {}).get("weights", {}).get("metadata", 0.4),
            weight_dedup=yaml_data.get("trust", {}).get("weights", {}).get("dedup", 0.3),
            weight_llm=yaml_data.get("trust", {}).get("weights", {}).get("llm", 0.3),
            low_trust_action=yaml_data.get("trust", {}).get("low_trust_action", "flag"),
            gate_formula=os.getenv("TRUST_GATE_FORMULA", yaml_data.get("trust", {}).get("gate_formula", "score_x_confidence")),
            gate_tau=float(os.getenv("TRUST_GATE_TAU", yaml_data.get("trust", {}).get("gate_tau", 0.35))),
            metadata_weight_age=yaml_data.get("trust", {}).get("metadata_weights", {}).get("age", 0.20),
            metadata_weight_karma=yaml_data.get("trust", {}).get("metadata_weights", {}).get("karma", 0.20),
            metadata_weight_length=yaml_data.get("trust", {}).get("metadata_weights", {}).get("length", 0.30),
            metadata_weight_engagement=yaml_data.get("trust", {}).get("metadata_weights", {}).get("engagement", 0.15),
            metadata_weight_base=yaml_data.get("trust", {}).get("metadata_weights", {}).get("base", 0.15),
        ),
        analysis=AnalysisConfig(
            sentiment_classes=yaml_data.get("analysis", {}).get("sentiment_classes", ["positive", "negative", "neutral"]),
            aspects=yaml_data.get("analysis", {}).get("aspects", [
                "delivery", "product_quality", "returns",
                "customer_support", "pricing", "app_website"
            ]),
            confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", yaml_data.get("analysis", {}).get("confidence_threshold", 0.7))),
            multi_aspect=yaml_data.get("analysis", {}).get("multi_aspect", True),
        ),
        privacy=PrivacyConfig(
            hash_usernames=yaml_data.get("privacy", {}).get("hash_usernames", True),
            retention_days=yaml_data.get("privacy", {}).get("retention_days", 365),
        ),
        dashboard=DashboardConfig(
            host=os.getenv("DASHBOARD_HOST", yaml_data.get("dashboard", {}).get("host", "0.0.0.0")),
            port=int(os.getenv("DASHBOARD_PORT", yaml_data.get("dashboard", {}).get("port", 8000))),
            websocket_enabled=yaml_data.get("dashboard", {}).get("websocket_enabled", True),
            auth=yaml_data.get("dashboard", {}).get("auth", "none"),
        ),
    )

    # ── Phase 3: Reddit OAuth (replies) ──────────────────────────────────────
    reddit_yaml = yaml_data.get("reddit_oauth", {}) or {}
    config.reddit_oauth = RedditOAuthConfig(
        enabled=bool(reddit_yaml.get("enabled", True)),
        dry_run=bool(reddit_yaml.get("dry_run", True)) if os.getenv("REDDIT_OAUTH_DRY_RUN") is None
            else os.getenv("REDDIT_OAUTH_DRY_RUN", "true").lower() in ("1", "true", "yes", "on"),
        client_id=os.getenv("REDDIT_OAUTH_CLIENT_ID", reddit_yaml.get("client_id", "")),
        client_secret=os.getenv("REDDIT_OAUTH_CLIENT_SECRET", reddit_yaml.get("client_secret", "")),
        redirect_uri=os.getenv("REDDIT_OAUTH_REDIRECT_URI",
            reddit_yaml.get("redirect_uri", "http://localhost:8000/api/auth/reddit/callback")),
        user_agent=reddit_yaml.get("user_agent", "RetailSentimentIntelligence/1.0"),
        scope=reddit_yaml.get("scope", "identity submit edit history"),
        rate_limit_seconds=int(reddit_yaml.get("rate_limit_seconds", 600)),
    )

    # ── Phase 4: Notifications (Slack + Email) ───────────────────────────────
    notif_yaml = yaml_data.get("notifications", {}) or {}
    slack_yaml = notif_yaml.get("slack", {}) or {}
    email_yaml = notif_yaml.get("email", {}) or {}
    config.notifications = NotificationsConfig(
        auto_lifecycle=bool(notif_yaml.get("auto_lifecycle", True)),
        confidence_threshold=float(notif_yaml.get("confidence_threshold", 0.7)),
        slack=SlackChannelConfig(
            enabled=bool(slack_yaml.get("enabled", False)),
            dry_run=bool(slack_yaml.get("dry_run", True)),
            webhook_url=os.getenv("SLACK_WEBHOOK_URL", slack_yaml.get("webhook_url", "")),
            channel=slack_yaml.get("channel", "#walmart-sentiment-alerts"),
        ),
        email=EmailChannelConfig(
            enabled=bool(email_yaml.get("enabled", False)),
            dry_run=bool(email_yaml.get("dry_run", True)),
            smtp_host=os.getenv("SMTP_HOST", email_yaml.get("smtp_host", "")),
            smtp_port=int(os.getenv("SMTP_PORT", email_yaml.get("smtp_port", 587))),
            smtp_user=os.getenv("SMTP_USER", email_yaml.get("smtp_user", "")),
            smtp_password=os.getenv("SMTP_PASSWORD", email_yaml.get("smtp_password", "")),
            use_tls=bool(email_yaml.get("use_tls", True)),
            from_addr=email_yaml.get("from_addr", "alerts@retail-sentiment.local"),
            recipients=list(email_yaml.get("recipients", []) or []),
        ),
    )

    # ── Load the model registry (config/models.yaml) ─────────────────────────
    # This is the flexible per-stage config. Each stage can be enabled/disabled
    # and the model can be swapped via YAML. Env vars override:
    #   MODEL_<STAGE>_PROVIDER, MODEL_<STAGE>_MODEL, MODEL_<STAGE>_ENABLED
    models_path = (path.parent if config_path else CONFIG_PATH.parent) / "models.yaml"
    if models_path.exists():
        with open(models_path) as f:
            models_yaml = yaml.safe_load(f) or {}

        def _stage(stage_name: str, defaults: dict) -> ModelStageConfig:
            data = (models_yaml.get("models", {}) or {}).get(stage_name, {}) or {}
            merged = {**defaults, **data}
            # Env overrides for the two most-likely-to-change knobs.
            env_provider = os.getenv(f"MODEL_{stage_name.upper()}_PROVIDER")
            env_model = os.getenv(f"MODEL_{stage_name.upper()}_MODEL")
            env_enabled = os.getenv(f"MODEL_{stage_name.upper()}_ENABLED")
            if env_provider:
                merged["provider"] = env_provider
            if env_model:
                merged["model"] = env_model
            if env_enabled:
                merged["enabled"] = env_enabled.lower() in ("1", "true", "yes", "on")
            # Keep only fields the dataclass actually has, to be forgiving of
            # forward-compat YAML keys we haven't wired up yet.
            allowed = {f.name for f in ModelStageConfig.__dataclass_fields__.values()}
            merged = {k: v for k, v in merged.items() if k in allowed}
            return ModelStageConfig(**merged)

        config.models = ModelsConfig(
            sentiment=_stage("sentiment", {
                "enabled": True, "provider": "huggingface",
                "model": "cardiffnlp/twitter-roberta-base-sentiment-latest",
            }),
            aspects=_stage("aspects", {
                "enabled": True, "provider": "huggingface",
                "model": "MoritzLaurer/deberta-v3-base-zeroshot-v2.0",
                "fallback_model": "facebook/bart-large-mnli",
            }),
            vision=_stage("vision", {
                "enabled": True, "provider": "ollama",
                "model": "gemma3:4b", "fallback_model": "llava:7b",
            }),
            reply=_stage("reply", {
                "enabled": True, "provider": "ollama",
                "model": "mistral:7b-instruct",
            }),
            embeddings=_stage("embeddings", {
                "enabled": False, "provider": "huggingface",
                "model": "sentence-transformers/all-MiniLM-L6-v2",
            }),
        )

        tools_yaml = (models_yaml.get("tools", {}) or {})
        ing = tools_yaml.get("ingestion", {}) or {}
        prep = tools_yaml.get("preprocessing", {}) or {}
        stor = tools_yaml.get("storage", {}) or {}
        priv = tools_yaml.get("privacy", {}) or {}
        trst = tools_yaml.get("trust", {}) or {}
        config.tools = ToolsConfig(
            ingestion_source=ing.get("source", "arctic_shift"),
            ingestion_interval_minutes=int(ing.get("interval_minutes", 60)),
            ingestion_backfill_days=int(ing.get("backfill_days", 90)),
            ingestion_english_only=bool(ing.get("english_only", True)),
            ingestion_min_text_chars=int(ing.get("min_text_chars", 10)),
            preprocess_dedup=prep.get("dedup", "md5_content_hash"),
            preprocess_language_detect=prep.get("language_detect", "langdetect"),
            storage_provider=stor.get("provider", "sqlite"),
            storage_sqlite_path=stor.get("sqlite_path", "data/local.db"),
            privacy_hash_usernames=bool(priv.get("hash_usernames", True)),
            privacy_retention_days=int(priv.get("retention_days", 365)),
            trust_formula=trst.get("formula", "score_x_confidence"),
            trust_tau=float(trst.get("tau", 0.30)),
            trust_threshold_legacy=float(trst.get("threshold_legacy", 0.5)),
            trust_low_trust_action=trst.get("low_trust_action", "flag"),
        )

    return config
