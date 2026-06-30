"""Product Hunt connector — newest AI posts via the public GraphQL API (free tier).

Set PRODUCTHUNT_TOKEN in .env (a developer token) to use; otherwise skips gracefully.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from app.connectors.base import MAX, normalize
from app.utils.retry import retry_call

log = logging.getLogger(__name__)

URL = "https://api.producthunt.com/v2/api/graphql"


def fetch(ig_user_id: str, max_items: int = MAX) -> list[dict]:
    token = os.getenv("PRODUCTHUNT_TOKEN", "")
    if not token:
        log.info("PRODUCTHUNT_TOKEN not set — skipping Product Hunt")
        return []
    query = """
    query ($first: Int!) {
      posts(first: $first, topic: "artificial-intelligence", order: NEWEST) {
        edges { node { id name tagline url website votedAt topics { edges { node { name } } } } }
      }
    }"""
    import httpx
    with httpx.Client(timeout=20.0) as client:
        resp = retry_call(client.post, URL,
                          json={"query": query, "variables": {"first": max_items}},
                          headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/json"})
        resp.raise_for_status()
        body = resp.json()

    out: list[dict] = []
    for edge in body.get("data", {}).get("posts", {}).get("edges", []):
        n = edge["node"]
        out.append(normalize(
            source="producthunt", title=n["name"], url=n.get("url"),
            summary=n.get("tagline"),
            signal_ts=datetime.now(timezone.utc), raw=n))
    return out
