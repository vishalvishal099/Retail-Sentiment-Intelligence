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
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    ingestion: IngestionConfig = field(default_factory=IngestionConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    trust: TrustConfig = field(default_factory=TrustConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)


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

    return config
