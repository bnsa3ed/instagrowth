"""Instagram Graph API v25.0 client — Facebook Login path.

All calls go through `app/utils/retry.py` (exp BUC backoff) and feed `X-*` usage headers
into `app/utils/buc.py`. Uses `views` / `total_views`, never `impressions`.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterator, Optional

import httpx

from app.config import settings
from app.utils import buc
from app.utils.retry import get as retry_get

log = logging.getLogger(__name__)


class InstagramClient:
    def __init__(self, token: Optional[str] = None, ig_user_id: Optional[str] = None,
                 timeout: float = 30.0):
        self.token = token or settings.meta_token
        self.ig_user_id = ig_user_id or settings.ig_user_id
        self.base = settings.graph_base
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "InstagramClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── low-level GET with paging + BUC capture ──────────────────────────────────
    def _get(self, path: str, **params: Any) -> dict:
        params = {"access_token": self.token, **params}
        url = path if path.startswith("http") else f"{self.base}/{path}"
        data = retry_get(self._client, url, **params)
        return data

    def _paged(self, path: str, **params: Any) -> Iterator[dict]:
        """Yield each `data` item across cursor-based pages; capture BUC headers."""
        url = path if path.startswith("http") else f"{self.base}/{path}"
        next_url: Optional[str] = url
        next_params: dict[str, Any] = {"access_token": self.token, **params}
        while next_url:
            resp = self._client.get(next_url, params=next_params,
                                    headers={"Accept": "application/json"})
            buc.update_from_headers(resp.headers)
            resp.raise_for_status()
            body = resp.json()
            for item in body.get("data", []):
                yield item
            paging = body.get("paging", {}).get("cursors", {})
            after = paging.get("after")
            next_url = body.get("paging", {}).get("next")
            if next_url and after:
                next_params = {"access_token": self.token, "after": after, **params}
            else:
                next_url = None

    # ── profile snapshot (1 cheap call) ──────────────────────────────────────────
    def get_profile(self) -> dict:
        return self._get(
            self.ig_user_id,
            fields="followers_count,follows_count,media_count",
        )

    # ── account-level insights (period=day, 90-day window, ~48h data delay) ──────
    def get_account_insights(self, since: int, until: int) -> dict:
        """`since`/`until` are unix timestamps. End the window 48h before now."""
        return self._get(
            f"{self.ig_user_id}/insights",
            metric="reach,views,accounts_engaged,follows_and_unfollows",
            metric_time="end_of_day",
            period="day",
            timeframe="this_month",  # overridden by since/until below when provided
            since=since,
            until=until,
        )

    # ── stories (24h lifetime — MUST capture daily) ──────────────────────────────
    def get_stories(self) -> list[dict]:
        stories = list(self._paged(f"{self.ig_user_id}/stories"))
        out = []
        for s in stories:
            enriched = dict(s)
            insights = self._story_insights(s["id"])
            enriched["insights"] = insights
            out.append(enriched)
        return out

    def _story_insights(self, story_id: str) -> dict[str, int]:
        try:
            data = self._get(
                story_id,
                fields="exits,reach,replies,taps_forward,taps_back,impression_count",
            )
        except httpx.HTTPError as exc:
            log.warning("story insights failed for %s: %s", story_id, exc)
            return {}
        # Map legacy impression_count → views for forward-compat; prefer views.
        return {k: v for k, v in data.items() if k != "id"}

    # ── media master + per-media performance (use views, not impressions) ────────
    def get_media_since(self, since_ts: Optional[int] = None, limit: int = 50) -> list[dict]:
        params: dict[str, Any] = {
            "fields": "id,caption,media_type,media_product_type,permalink,timestamp",
            "limit": limit,
        }
        if since_ts:
            params["since"] = since_ts
        return list(self._paged(f"{self.ig_user_id}/media", **params))

    def get_media_insights(self, media_id: str, media_type: str) -> dict[str, int]:
        # `views` IS valid on the IG Login path (the 400 only rejected `plays`). Try the full
        # set first; if a media type still rejects `views`, fall back without it.
        full = "reach,likes,comments,saved,shares,views"
        baseline = "reach,likes,comments,saved,shares"
        for metrics in [full, baseline]:
            try:
                body = self._get(f"{media_id}/insights", metric=metrics)
            except httpx.HTTPStatusError as exc:
                detail = ""
                try:
                    detail = exc.response.json()
                except Exception:  # noqa: BLE001
                    detail = exc.response.text[:200]
                log.warning("media insights %s/%s → %s; %s",
                            media_id, metrics, exc.response.status_code, detail)
                continue  # fall back to the smaller set
            except httpx.HTTPError as exc:
                log.warning("media insights failed for %s: %s", media_id, exc)
                return {}
            flat: dict[str, int] = {}
            for entry in body.get("data", []):
                name = entry.get("name")
                values = entry.get("values") or []
                if name and values:
                    flat[name] = values[-1].get("value", 0)
            return flat
        return {}

    # ── Business Discovery (competitor top media — used by US2) ──────────────────
    def business_discovery(self, username: str, limit: int = 10) -> dict:
        return self._get(
            self.ig_user_id,
            fields="business_discovery.username(%s){media.limit(%d){id,like_count,comments_count,timestamp,caption,media_type,permalink}}"
            % (username, limit),
        )

    # ── Content Publishing API (US5; scope: instagram_content_publish) ───────────
    # create-container → publish. Supports image, carousel, AND Reels. Public media_url only.
    def create_container(self, media_type: str, media_url: str, caption: str,
                         children: list[str] | None = None, is_carousel_item: bool = False) -> str:
        """Create a media container; returns its id. For carousls, build items then a parent."""
        from app.utils.retry import post as retry_post
        params: dict[str, Any] = {"caption": caption}
        if media_type == "REELS":
            params.update({"media_type": "REELS", "video_url": media_url})
        elif media_type == "CAROUSEL_ALBUM":
            params.update({"media_type": "CAROUSEL_ALBUM", "children": ",".join(children or [])})
        elif is_carousel_item:
            params.update({"image_url": media_url, "is_carousel_item": True})
        else:
            params.update({"image_url": media_url})

        path = "media" if not is_carousel_item else "media"
        body = retry_post(self._client, f"{self.base}/{self.ig_user_id}/{path}",
                          data={"access_token": self.token, **params})
        return body["id"]

    def publish_container(self, container_id: str) -> str:
        """Publish a created container; returns the published media_id."""
        from app.utils.retry import post as retry_post
        body = retry_post(
            self._client,
            f"{self.base}/{self.ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": self.token},
        )
        return body["id"]
