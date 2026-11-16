"""Collector for Indian retail stock discussions and sentiment via Reddit OAuth/RSS and (CLI only) curated fallbacks."""

import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from kairos.config.settings import get_settings
from kairos.mcp_client.adapters import RedditMCPAdapter
from kairos.processors.clean_reddit import CleanRedditProcessor
from kairos.schemas.reddit import RedditPost, SentimentPayload
from kairos.storage.file_store import FileStore
from kairos.utils.logging_config import get_logger
from kairos.utils.security import validate_ticker

logger = get_logger("kairos.collectors.reddit_collector")

# Institutional Indian equity aliases for relevance filtering
TICKER_ALIASES: Dict[str, List[str]] = {
    "RELIANCE": ["RELIANCE", "RIL", "JIO", "MUKESH AMBANI", "AMBANI"],
    "TCS": ["TCS", "TATA CONSULTANCY"],
    "INFY": ["INFY", "INFOSYS", "SALIL PAREKH"],
    "HDFCBANK": ["HDFCBANK", "HDFC BANK", "HDFC"],
    "ICICIBANK": ["ICICIBANK", "ICICI BANK", "ICICI"],
}

# Financial sentiment lexicon for rule-based post classification
BULL_WORDS = {
    "buy", "bull", "bullish", "growth", "profit", "multibagger", "gain", "gains",
    "high", "rally", "surge", "boom", "breakout", "undervalued", "accumulate",
    "outperform", "target", "green", "dividend"
}
BEAR_WORDS = {
    "sell", "bear", "bearish", "loss", "losses", "crash", "fall", "dump",
    "drop", "correction", "devaluation", "overvalued", "dip", "underperform",
    "avoid", "risk", "debt", "down", "red", "inflation"
}


DEFAULT_USER_AGENT = "python:kairos.equity.research:v1.0 (academic institutional finance research agent; +https://github.com/kairos-equity)"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
_COMPANY_SUFFIX = re.compile(r"\b(limited|ltd\.?|inc\.?|corporation|corp\.?|plc)\s*$", re.I)


def reddit_user_agent() -> str:
    return os.environ.get("REDDIT_USER_AGENT") or DEFAULT_USER_AGENT


def reddit_get(url, session=None, headers=None, timeout=(4.0, 8.0), retries=2, **kwargs):
    """GET with a descriptive UA. Retries only 429 (honouring Retry-After, capped at 5s); 403 is permanent."""
    getter = (session or requests).get
    merged = {"User-Agent": reddit_user_agent(), **(headers or {})}
    for attempt in range(retries + 1):
        resp = getter(url, headers=merged, timeout=timeout, **kwargs)
        if resp.status_code != 429 or attempt == retries:
            return resp
        try:
            wait = float(resp.headers.get("Retry-After", 1))
        except (ValueError, TypeError):
            wait = 1.0
        time.sleep(min(5.0, max(0.0, wait)))


def _plain(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup or ""))).strip()


def parse_atom_entries(content: bytes) -> List[Dict[str, Any]]:
    """Parse a Reddit Atom feed into post dicts (id, title, created_iso, url, author, text, subreddit)."""
    posts = []
    for entry in ET.fromstring(content).findall("a:entry", ATOM):
        link = entry.find("a:link", ATOM)
        url = link.get("href", "") if link is not None else ""
        category = entry.find("a:category", ATOM)
        sub = category.get("term", "") if category is not None else ""
        if not sub:
            found = re.search(r"/r/([^/]+)/", url)
            sub = found.group(1) if found else ""
        posts.append({
            "id": entry.findtext("a:id", "", ATOM), "title": entry.findtext("a:title", "", ATOM).strip(),
            "created_iso": entry.findtext("a:updated", "", ATOM), "url": url, "subreddit": sub,
            "author": (entry.findtext("a:author/a:name", "", ATOM) or "").strip(),
            "text": _plain(entry.findtext("a:content", "", ATOM)),
        })
    return [p for p in posts if p["id"] and p["title"]]


def _terms(symbol: str, company_name: str) -> List[str]:
    base = symbol.rsplit(".", 1)[0].upper() if symbol.upper().endswith((".NS", ".BO")) else symbol.upper()
    name = _COMPANY_SUFFIX.sub("", company_name or "").strip()
    terms = [base, *TICKER_ALIASES.get(base, [])]
    if len(name) > 3 and name.upper() != base:
        terms.append(name)
    return list(dict.fromkeys(t.upper() for t in terms))


def _fresh_matching(posts, terms, now, seen):
    """Keep posts within 7 days that mention a term; dedupe by id across calls via `seen`."""
    pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b", re.I)
    kept = []
    for post in posts:
        try:
            when = datetime.fromisoformat(post["created_iso"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < now - timedelta(days=7) or when > now + timedelta(minutes=5) or post["id"] in seen:
            continue
        if pattern.search(post["title"] + " " + post["text"]):
            seen.add(post["id"])
            kept.append(post)
    return kept


def fetch_reddit_evidence(symbol, company_name, now=None, session=None, settings=None):
    """Acquire live Reddit posts: OAuth search, then RSS search, then per-subreddit new feeds.

    Returns (posts, meta). meta['status'] is 'OK', 'NO_RECENT_DISCUSSION', or 'UNAVAILABLE' (every method
    failed to reach Reddit; meta['reason'] lists the statuses). Never returns curated or archived data.
    """
    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    terms = _terms(symbol, company_name)
    base = terms[0]
    subs = list(settings.reddit_subreddits)
    name = _COMPANY_SUFFIX.sub("", company_name or "").strip()
    query = f'{base} OR "{name}"' if len(name) > 3 and name.upper() != base else base
    attempts, seen, reached = [], set(), []

    def attempt(method, url, call):
        try:
            resp = call()
            attempts.append({"method": method, "url": url, "status": resp.status_code})
            return resp if resp.status_code == 200 else None
        except (requests.RequestException, ValueError) as exc:
            attempts.append({"method": method, "url": url, "status": f"error: {type(exc).__name__}"})
            return None

    def done(method, posts):
        latest = max((p["created_iso"] for p in posts), default=None)
        status = "OK" if posts else "NO_RECENT_DISCUSSION"
        return posts, {"source": "REDDIT", "method": method, "status": status, "posts": len(posts),
                       "latest_post": latest, "attempts": attempts}

    if settings.reddit_authorized:
        token_url = "https://www.reddit.com/api/v1/access_token"
        resp = attempt("oauth_search", token_url, lambda: (session or requests).post(
            token_url, auth=(settings.reddit_client_id, settings.reddit_client_secret),
            data={"grant_type": "client_credentials"}, headers={"User-Agent": reddit_user_agent()}, timeout=(4.0, 8.0)))
        token = resp.json().get("access_token") if resp is not None else None
        if token:
            url = "https://oauth.reddit.com/r/" + "+".join(subs) + "/search?" + urlencode(
                {"q": query, "restrict_sr": 1, "sort": "new", "t": "week", "limit": 100})
            resp = attempt("oauth_search", url.split("?")[0], lambda: reddit_get(
                url, session, headers={"Authorization": f"bearer {token}"}))
            if resp is not None:
                reached.append("oauth_search")
                posts = [{"id": c["data"]["name"], "title": c["data"].get("title", "").strip(),
                          "created_iso": datetime.fromtimestamp(c["data"]["created_utc"], timezone.utc).isoformat(),
                          "url": "https://www.reddit.com" + c["data"].get("permalink", ""),
                          "subreddit": c["data"].get("subreddit", ""), "author": c["data"].get("author", ""),
                          "text": c["data"].get("selftext", "")} for c in resp.json()["data"]["children"]]
                kept = _fresh_matching(posts, terms, now, seen)
                if kept:
                    return done("oauth_search", kept)

    url = "https://www.reddit.com/r/" + "+".join(subs) + "/search.rss?" + urlencode(
        {"q": query, "restrict_sr": "on", "sort": "new", "t": "week"})
    resp = attempt("rss_search", url, lambda: reddit_get(url, session))
    if resp is not None:
        reached.append("rss_search")
        try:
            kept = _fresh_matching(parse_atom_entries(resp.content), terms, now, seen)
        except (ET.ParseError, TypeError):
            attempts[-1]["status"] = "error: ParseError"
            reached.pop()
            kept = []
        if kept:
            return done("rss_search", kept)

    collected = []
    for index, sub in enumerate(subs):
        if index:
            time.sleep(0.5)
        url = f"https://www.reddit.com/r/{sub}/new/.rss?limit=100"
        resp = attempt("rss_subreddit_new", url, lambda: reddit_get(url, session))
        if resp is None:
            continue
        try:
            collected += _fresh_matching(parse_atom_entries(resp.content), terms, now, seen)
            reached.append("rss_subreddit_new")
        except (ET.ParseError, TypeError):
            attempts[-1]["status"] = "error: ParseError"
    if collected:
        return done("rss_subreddit_new", collected)
    if not reached:
        statuses = ", ".join(f"{a['method']} HTTP {a['status']}" for a in attempts)
        return [], {"source": "REDDIT", "method": None, "status": "UNAVAILABLE", "posts": 0, "latest_post": None, "attempts": attempts,
                    "reason": f"Fresh Reddit evidence is unavailable ({statuses}). No curated sentiment was substituted."}
    return done(reached[-1], [])


def score_sentiment_text(text: str) -> Tuple[str, float]:
    """Scores financial text into POSITIVE, NEGATIVE, or NEUTRAL with a normalized score (-1.0 to +1.0)."""
    lower = text.lower()
    bull = sum(1 for w in BULL_WORDS if re.search(r"\b" + re.escape(w) + r"\b", lower))
    bear = sum(1 for w in BEAR_WORDS if re.search(r"\b" + re.escape(w) + r"\b", lower))
    if bull > bear:
        return "POSITIVE", min(1.0, round((bull - bear) * 0.35, 2))
    elif bear > bull:
        return "NEGATIVE", max(-1.0, round((bear - bull) * -0.35, 2))
    return "NEUTRAL", 0.0


class RedditCollector:
    """Collects social sentiment across Indian finance communities (r/IndianStockMarket, r/IndiaInvestments, etc.)
    using Reddit OAuth/RSS, with strict source attribution and fallback handling.
    """

    def __init__(
        self,
        file_store: Optional[FileStore] = None,
        session: Optional[requests.Session] = None,
        timeout: Tuple[float, float] = (4.0, 7.0),
        max_retries: int = 2,
    ):
        self.settings = get_settings()
        self.file_store = file_store or FileStore()
        self.reddit_adapter = RedditMCPAdapter()
        self.clean_processor = CleanRedditProcessor(file_store=self.file_store)
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries

    def _get_user_agent(self) -> str:
        """Returns a descriptive, application-specific User-Agent compliant with Reddit guidelines."""
        return reddit_user_agent()

    def fetch_community_sentiment(
        self,
        symbol: str,
        subreddits: Optional[List[str]] = None,
        limit_per_sub: int = 5,
    ) -> SentimentPayload:
        """
        Gathers Reddit posts referencing an Indian equity across retail trading subreddits.
        1. Tries live OAuth search (when credentials are set) or public RSS via fetch_reddit_evidence.
        2. If that succeeds, exports posts tagged LIVE_REDDIT_JSON / LIVE_REDDIT_ATOM_FEED.
        3. Otherwise (this CLI path only) activates the curated fallback tagged CURATED_FALLBACK.
        """
        clean_symbol = validate_ticker(symbol).replace(".NS", "").replace(".BO", "")
        target_subs = subreddits or self.settings.reddit_subreddits
        logger.info(f"Gathering Reddit sentiment for {clean_symbol} across {target_subs}")

        retrieval_ts = datetime.now(timezone.utc).isoformat()

        # Anonymous .json is login-gated (docs/research_sources.md), so go straight to OAuth/RSS.
        rss_posts, meta = fetch_reddit_evidence(clean_symbol, "", session=self.session, settings=self.settings)
        if rss_posts:
            label = "LIVE_REDDIT_JSON" if meta["method"] == "oauth_search" else "LIVE_REDDIT_ATOM_FEED"
            selected = []
            for p in rss_posts[: limit_per_sub * len(target_subs)]:
                lbl, sc = score_sentiment_text(f"{p['title']} {p['text']}")
                created = datetime.fromisoformat(p["created_iso"].replace("Z", "+00:00")).timestamp()
                selected.append(RedditPost(
                    id=p["id"], title=p["title"], snippet=p["text"][:600], score=0, num_comments=0,
                    subreddit=p["subreddit"] or "unknown", permalink=p["url"], created_utc=created,
                    retrieval_timestamp=retrieval_ts, is_synthetic=False, source_status=label,
                    sentiment_label=lbl, sentiment_score=sc,
                    relevance_level="TICKER_SPECIFIC", author=p["author"] or "[anonymous]"))
            self.file_store.save_raw("reddit", f"{clean_symbol.lower()}_sentiment.json", {
                "symbol": clean_symbol, "subreddits": target_subs, "permission_status": label,
                "retrieval_timestamp": retrieval_ts, "live_posts_count": len(selected),
                "fallback_posts_count": 0, "posts": [p.model_dump() for p in selected]})
            payload = SentimentPayload(ticker=clean_symbol, posts=selected, is_live_data=True,
                                       permission_status=label, live_posts_count=len(selected), fallback_posts_count=0)
            self.clean_processor.process_and_export(payload)
            return payload

        # Step 2: live access failed -> curated fallback (CLI only; the web pipeline never uses it)
        error_detail = meta.get("reason") or "Reddit returned 0 matching posts"
        logger.warning(
            f"Live Reddit access unavailable ({error_detail}). "
            "Activating curated fallback mechanism with explicit CURATED_FALLBACK attribution."
        )

        # Ensure fallback dataset exists
        ticker_raw_path = self.file_store.raw_dir / "reddit" / f"{clean_symbol.lower()}_sentiment.json"
        if not ticker_raw_path.exists():
            try:
                from kairos.pipeline.refresh import fetch_genuine_reddit_data
                fetch_genuine_reddit_data(self.file_store)
            except Exception as e:
                logger.warning(f"Could not initialize genuine fallback dataset: {e}")

        fallback_posts: List[RedditPost] = []
        if ticker_raw_path.exists():
            try:
                with open(ticker_raw_path, "r", encoding="utf-8") as f:
                    ticker_data = json.load(f)
                posts_raw = ticker_data.get("posts", [])
                max_total = limit_per_sub * len(target_subs)
                for p in posts_raw[:max_total]:
                    post_id = str(p.get("post_id", p.get("id", "")))
                    if not post_id:
                        continue
                    title = str(p.get("title", ""))
                    snippet = str(p.get("snippet", p.get("selftext", "")))
                    combined = f"{title} {snippet}"
                    lbl, sc = score_sentiment_text(combined)

                    post_prov = p.get("source_status") or p.get("alternative_source_provenance") or p.get("source") or ""
                    is_rss = "ATOM" in str(post_prov).upper() or ".RSS" in str(post_prov).upper() or "FEED" in str(post_prov).upper()

                    if is_rss:
                        status_label = "LIVE_REDDIT_ATOM_FEED"
                        is_synth = False
                    elif "JSON" in str(post_prov).upper() and "FALLBACK" not in str(post_prov).upper():
                        status_label = "LIVE_REDDIT_JSON"
                        is_synth = False
                    else:
                        status_label = "CURATED_FALLBACK"
                        is_synth = True

                    author = str(p.get("author") or ("[curated]" if is_synth else "[anonymous]"))

                    post = RedditPost(
                        id=post_id,
                        title=title,
                        snippet=snippet,
                        score=int(p.get("score", 0)),
                        num_comments=int(p.get("num_comments", 0)),
                        subreddit=str(p.get("subreddit", "IndianStockMarket")),
                        permalink=str(p.get("permalink", f"/r/IndianStockMarket/comments/{post_id}")),
                        created_utc=float(p.get("created_utc", 0.0)),
                        retrieval_timestamp=p.get("retrieval_timestamp", retrieval_ts),
                        is_synthetic=is_synth,
                        source_status=status_label,
                        sentiment_label=p.get("sentiment_label", lbl),
                        sentiment_score=float(p.get("sentiment_score", sc)),
                        relevance_level=p.get("relevance_level", "TICKER_SPECIFIC"),
                        author=author,
                    )
                    fallback_posts.append(post)
            except Exception as e:
                logger.warning(f"Error reading curated fallback dataset: {e}")

        # Check if the fallback dataset contains real RSS syndication posts
        has_real_atom = any(p.source_status == "LIVE_REDDIT_ATOM_FEED" for p in fallback_posts)
        if has_real_atom:
            perm_status = "LIVE_REDDIT_ATOM_FEED"
            is_live = True
            live_count = len(fallback_posts)
            fb_count = 0
        else:
            perm_status = "CURATED_FALLBACK"
            is_live = False
            live_count = 0
            fb_count = len(fallback_posts)

        payload = SentimentPayload(
            ticker=clean_symbol,
            posts=fallback_posts,
            is_live_data=is_live,
            permission_status=perm_status,
            live_posts_count=live_count,
            fallback_posts_count=fb_count,
        )
        self.clean_processor.process_and_export(payload)
        return payload
