"""Pydantic models — DB row shapes + Gemini structured-output schemas.

These double as (a) typed row containers for upserts and (b) the JSON-schema contract
passed to `google-genai` structured output (`response_schema=...`).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ── Instagram capture rows (map to DB tables) ──────────────────────────────────


class ProfileMetric(BaseModel):
    model_config = ConfigDict(extra="allow")
    snapshot_date: date
    ig_user_id: str
    followers_count: Optional[int] = None
    follows_count: Optional[int] = None
    media_count: Optional[int] = None
    reach: Optional[int] = None
    profile_views: Optional[int] = None
    total_views: Optional[int] = None
    accounts_engaged: Optional[int] = None
    follows_and_unfollows: Optional[int] = None
    raw_json: Optional[dict[str, Any]] = None


class MediaRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    media_id: str
    ig_user_id: str
    media_type: Optional[str] = None
    caption: Optional[str] = None
    permalink: Optional[str] = None
    publish_date: datetime
    first_seen_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None


class MediaPerformanceRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    media_id: str
    snapshot_ts: datetime
    likes_count: Optional[int] = None
    comments_count: Optional[int] = None
    reach: Optional[int] = None
    views: Optional[int] = None
    saved: Optional[int] = None
    shares: Optional[int] = None
    plays: Optional[int] = None


class StoryRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    story_id: str
    ig_user_id: str
    publish_ts: datetime
    exits: Optional[int] = None
    views: Optional[int] = None
    reach: Optional[int] = None
    replies: Optional[int] = None
    taps_forward: Optional[int] = None
    taps_back: Optional[int] = None


class TrendSignal(BaseModel):
    model_config = ConfigDict(extra="allow")
    ig_user_id: str
    source: str
    title: str
    url: Optional[str] = None
    summary: Optional[str] = None
    signal_ts: Optional[datetime] = None
    momentum: Optional[str] = None
    signal_hash: str
    raw_json: Optional[dict[str, Any]] = None


# ── Gemini structured-output schemas (US1 weekly report) ───────────────────────


class TopPost(BaseModel):
    media_id: str
    why: str


class GrowthOpportunity(BaseModel):
    title: str
    how: str
    effort: Literal["low", "med", "high"]


class WeeklyReport(BaseModel):
    """Structured weekly strategy report (Egyptian Arabic). Pinned to egyptian-strategy-v1."""

    headline: str = Field(description="ملخص سطر واحد بالعامية المصرية")
    engagement_rate_avg: float = Field(
        description="نسبة التفاعل المحسوبة (لايكات+تعليقات+حفظ+مشاركات) ÷ الريتش"
    )
    top_posts: list[TopPost]
    what_works: list[str]
    what_to_fix: list[str]
    growth_opportunities: list[GrowthOpportunity]
    next_week_content: list[str]
    full_report_markdown: str = Field(description="التقرير الكامل بالعامية المصرية بصيغة Markdown")


# ── Gemini structured-output schemas (US2 topic ideation) ──────────────────────


class TopicSuggestion(BaseModel):
    title: str
    angle: str
    trend_hook: str = Field(description="ليه دلوقتي — why now")
    format: Literal["Reel", "Carousel", "Story", "Carousel+Reel"]
    niche_fit: Literal["core", "adjacent"]
    opportunity_score: float = Field(ge=0, le=100)
    suggested_hashtags: list[str]
    why_now: str
    draft_outline: str


class TopicIdeation(BaseModel):
    """Niche-filtered, opportunity-scored topic ideas (3–5). Pinned to topics-vibecoding-v1."""

    topics: list[TopicSuggestion] = Field(min_length=1, max_length=8)


# ── Gemini structured-output schemas (US4 content drafts) ──────────────────────


class ContentDraft(BaseModel):
    caption: str
    hook: str
    body: dict[str, Any] = Field(
        default_factory=dict,
        description="{'slides':[...]} للكاروسيل أو {'script':'...'} للريلز",
    )
    hashtags: list[str]
    variant_label: Optional[str] = None


# ── Anomaly (US3) ──────────────────────────────────────────────────────────────


class Anomaly(BaseModel):
    model_config = ConfigDict(extra="allow")
    ig_user_id: str
    metric: str
    direction: Literal["spike", "drop"]
    severity: float
    expected: Optional[float] = None
    actual: Optional[float] = None
    attributed_media_id: Optional[str] = None
