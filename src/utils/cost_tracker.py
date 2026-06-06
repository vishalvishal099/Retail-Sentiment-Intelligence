"""
Retail Sentiment Intelligence — LLM Cost Tracker
Tracks token usage and cost per LLM call. Required per R3.3.
"""

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

log = get_logger("cost_tracker")


@dataclass
class LLMUsageRecord:
    timestamp: float
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    batch_id: Optional[str] = None
    stage: str = "analysis"  # analysis | trust | summarize


# Approximate cost per 1M tokens (input / output)
COST_TABLE = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    # Free / OSS models
    "cardiffnlp/twitter-roberta-base-sentiment-latest": (0.0, 0.0),
    "meta-llama/Meta-Llama-3.1-8B-Instruct": (0.0, 0.0),
    "microsoft/DeBERTa-v3-base": (0.0, 0.0),
}


class CostTracker:
    def __init__(self, log_file: str = "data/llm_costs.jsonl", daily_limit_usd: float = 0.0):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.daily_limit_usd = daily_limit_usd
        self._daily_total: float = 0.0
        self._daily_reset_date: str = ""

    def record(self, provider: str, model: str, input_tokens: int, output_tokens: int,
               stage: str = "analysis", batch_id: Optional[str] = None) -> float:
        """Record a single LLM call's usage. Returns cost in USD."""
        cost = self._calculate_cost(model, input_tokens, output_tokens)

        record = LLMUsageRecord(
            timestamp=time.time(),
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            batch_id=batch_id,
            stage=stage,
        )

        with open(self.log_file, "a") as f:
            f.write(json.dumps(asdict(record)) + "\n")

        self._daily_total += cost
        log.info("llm_usage", model=model, tokens_in=input_tokens, tokens_out=output_tokens, cost_usd=cost)
        return cost

    def check_budget(self) -> bool:
        """Returns True if within daily budget. Always True if limit is 0 (unlimited/free)."""
        if self.daily_limit_usd <= 0:
            return True
        return self._daily_total < self.daily_limit_usd

    def get_daily_spend(self) -> float:
        return self._daily_total

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        rates = COST_TABLE.get(model, (0.0, 0.0))
        input_cost = (input_tokens / 1_000_000) * rates[0]
        output_cost = (output_tokens / 1_000_000) * rates[1]
        return input_cost + output_cost
