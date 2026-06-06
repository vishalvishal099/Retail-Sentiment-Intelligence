"""
Retail Sentiment Intelligence — Reddit Client Wrapper
Handles PRAW initialization, rate-limiting, and session management.
"""

import praw
from typing import Optional

from src.utils.config import IngestionConfig
from src.utils.logger import get_logger

log = get_logger("reddit_client")


class RedditClient:
    """Wrapper around PRAW with rate-limit awareness."""

    def __init__(self, config: IngestionConfig):
        self.config = config
        self._reddit: Optional[praw.Reddit] = None

    @property
    def reddit(self) -> praw.Reddit:
        if self._reddit is None:
            self._reddit = praw.Reddit(
                client_id=self.config.reddit_client_id,
                client_secret=self.config.reddit_client_secret,
                user_agent=self.config.reddit_user_agent,
            )
            log.info("reddit_connected", user_agent=self.config.reddit_user_agent)
        return self._reddit

    def get_subreddit(self, name: str):
        """Get a subreddit object."""
        return self.reddit.subreddit(name)

    def is_healthy(self) -> bool:
        """Quick health check."""
        try:
            _ = self.reddit.subreddit("walmart").display_name
            return True
        except Exception as e:
            log.error("reddit_health_failed", error=str(e))
            return False
