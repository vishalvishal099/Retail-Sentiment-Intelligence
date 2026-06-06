"""
Healthcheck — verify connections to Reddit, Cosmos DB, and LLM provider.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def check_reddit():
    """Verify Reddit API credentials."""
    import praw

    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv("REDDIT_USER_AGENT", "RetailSentimentIntelligence/1.0")

    if not client_id or not client_secret:
        print("✗ Reddit: REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set")
        return False

    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        # Test with a simple read
        sub = reddit.subreddit("walmart")
        _ = sub.display_name
        print(f"✓ Reddit: connected (r/{sub.display_name})")
        return True
    except Exception as e:
        print(f"✗ Reddit: {e}")
        return False


def check_cosmos():
    """Verify Cosmos DB connection."""
    endpoint = os.getenv("COSMOS_ENDPOINT")
    key = os.getenv("COSMOS_KEY")

    if not endpoint or not key:
        print("✗ Cosmos DB: COSMOS_ENDPOINT / COSMOS_KEY not set")
        return False

    try:
        from azure.cosmos import CosmosClient
        client = CosmosClient(endpoint, key)
        # List databases to verify
        list(client.list_databases())
        print("✓ Cosmos DB: connected")
        return True
    except Exception as e:
        print(f"✗ Cosmos DB: {e}")
        return False


def check_llm():
    """Verify LLM provider is accessible."""
    provider = os.getenv("LLM_PROVIDER", "huggingface")

    if provider == "huggingface":
        try:
            from transformers import pipeline
            print("✓ LLM (HuggingFace): transformers library available")
            return True
        except ImportError:
            print("✗ LLM (HuggingFace): transformers not installed")
            return False

    elif provider in ("openai", "azure_openai"):
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        key = os.getenv("AZURE_OPENAI_KEY")
        if not endpoint or not key:
            print("✗ LLM (Azure OpenAI): credentials not set")
            return False
        print("✓ LLM (Azure OpenAI): credentials present (not tested)")
        return True

    print(f"? LLM: unknown provider '{provider}'")
    return False


def main():
    from dotenv import load_dotenv
    load_dotenv()

    print("─── Retail Sentiment Intelligence — Healthcheck ───\n")
    results = [
        check_reddit(),
        check_cosmos(),
        check_llm(),
    ]
    print()
    if all(results):
        print("✓ All systems connected!")
    else:
        failed = sum(1 for r in results if not r)
        print(f"✗ {failed} connection(s) failed. Fix .env and retry.")
        sys.exit(1)


if __name__ == "__main__":
    main()
