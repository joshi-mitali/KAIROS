"""Root compatibility exports for collectors."""

from kairos.collectors.market_collector import MarketCollector
from kairos.collectors.news_collector import NewsCollector
from kairos.collectors.reddit_collector import RedditCollector
from kairos.collectors.fundamentals_collector import FundamentalsCollector

__all__ = [
    "MarketCollector",
    "NewsCollector",
    "RedditCollector",
    "FundamentalsCollector",
]
