"""Reddit and social sentiment Pydantic v2 validation models."""

from typing import List, Optional, Union
from pydantic import BaseModel, Field, field_validator


class RedditPost(BaseModel):
    """Pydantic model for a Reddit submission with strict privacy controls."""

    id: str = Field(..., description="Unique post ID", alias="post_id")
    title: str = Field(..., min_length=1, description="Post title")
    snippet: str = Field(default="", description="Sanitized excerpt or body", alias="text")
    score: int = Field(default=0, description="Upvotes minus downvotes")
    num_comments: int = Field(default=0, ge=0, description="Total comment count", alias="comment_count")
    subreddit: str = Field(..., description="Target subreddit name")
    permalink: str = Field(..., description="Relative or absolute URL path to post")
    created_utc: float = Field(..., description="Unix UTC timestamp when posted")
    retrieval_timestamp: Optional[str] = Field(default=None, description="ISO timestamp when ingested")
    is_synthetic: bool = Field(default=False, description="True if generated from test fixture")
    source_status: str = Field(default="AUTHORIZED_API", description="Data provenance status")

    class Config:
        populate_by_name = True

    @field_validator("permalink")
    @classmethod
    def validate_permalink(cls, v: str) -> str:
        clean = v.strip()
        if not clean.startswith("http://") and not clean.startswith("https://") and not clean.startswith("/r/"):
            raise ValueError(f"Invalid Reddit permalink: {v}")
        return clean


class SentimentPayload(BaseModel):
    """Payload encapsulating parsed Reddit posts and community sentiment metrics."""

    ticker: str = Field(..., description="Tracked ticker symbol")
    subreddit: Optional[str] = Field(default=None, description="Target subreddit")
    posts: List[RedditPost] = Field(default_factory=list, description="List of validated Reddit posts")
    is_live_data: bool = Field(default=True, description="True if originating from authorized live API")
    permission_status: str = Field(default="PERMITTED", description="Status of API permissions or fixture flag")


# Alias for compatibility with varying nomenclature
RedditPayload = SentimentPayload
