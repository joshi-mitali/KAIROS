"""Financial news Pydantic v2 validation models."""

from typing import List, Optional, Union
from pydantic import BaseModel, Field, field_validator


class NewsArticle(BaseModel):
    """Normalized representation of a financial news article or headline."""

    headline: str = Field(..., min_length=1, description="Article title or headline")
    summary: str = Field(default="", description="Sanitized snippet or lead summary")
    source: str = Field(..., description="Publisher or publication name", alias="source_name")
    url: str = Field(..., description="Canonical article URL", alias="article_url")
    datetime: Union[str, int] = Field(..., description="Publication ISO timestamp or Unix epoch", alias="published_at")
    article_id: Optional[str] = Field(default=None, description="Unique identifier or content SHA256")
    ticker: Optional[str] = Field(default=None, description="Associated ticker symbol")
    provider: Optional[str] = Field(default="news_provider", description="Provider API used")
    retrieved_at: Optional[str] = Field(default=None, description="ISO timestamp when collected")
    language: Optional[str] = Field(default="en", description="Language code")

    class Config:
        populate_by_name = True

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        clean = v.strip()
        if not clean.startswith("http://") and not clean.startswith("https://"):
            raise ValueError(f"Invalid article URL format: {v}")
        return clean


class NewsPayload(BaseModel):
    """Payload encapsulating financial news articles for a given ticker or query."""

    ticker: str = Field(..., description="Target ticker or search symbol")
    articles: List[NewsArticle] = Field(default_factory=list, description="Validated news articles")
    is_live_data: bool = Field(default=True, description="True if collected from live provider")
    provider: Optional[str] = Field(default="gdelt", description="Configured provider name")
