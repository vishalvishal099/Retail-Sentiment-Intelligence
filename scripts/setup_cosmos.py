"""
Setup Cosmos DB containers for Retail Sentiment Intelligence.
Creates: raw_posts, analyses, aggregates, feedback
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from azure.cosmos import CosmosClient, PartitionKey, exceptions


def setup_cosmos():
    endpoint = os.getenv("COSMOS_ENDPOINT")
    key = os.getenv("COSMOS_KEY")
    database_name = os.getenv("COSMOS_DATABASE", "retail_sentiment")

    if not endpoint or not key:
        print("✗ COSMOS_ENDPOINT and COSMOS_KEY must be set in .env")
        sys.exit(1)

    client = CosmosClient(endpoint, key)

    # Create database
    try:
        database = client.create_database_if_not_exists(id=database_name)
        print(f"✓ Database '{database_name}' ready")
    except exceptions.CosmosHttpResponseError as e:
        print(f"✗ Database creation failed: {e.message}")
        sys.exit(1)

    # Container definitions
    containers = [
        {"id": "raw_posts", "partition_key": "/subreddit"},
        {"id": "analyses", "partition_key": "/subreddit"},
        {"id": "aggregates", "partition_key": "/time_window"},
        {"id": "feedback", "partition_key": "/analyst_id"},
    ]

    for container_def in containers:
        try:
            database.create_container_if_not_exists(
                id=container_def["id"],
                partition_key=PartitionKey(path=container_def["partition_key"]),
            )
            print(f"  ✓ Container '{container_def['id']}' (partition: {container_def['partition_key']})")
        except exceptions.CosmosHttpResponseError as e:
            print(f"  ✗ Container '{container_def['id']}' failed: {e.message}")

    print("\n✓ Cosmos DB setup complete.")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    setup_cosmos()
