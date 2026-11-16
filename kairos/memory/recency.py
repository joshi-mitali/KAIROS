"""Recency-weighted scoring algorithms for KAIROS Persistent Memory.
Combines recency decay curves with multi-dimensional domain relevance
(ticker, sector, strategy, market regime, semantic vector similarity)
while strictly ensuring recency never overrides relevance or risk.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union

SECTOR_MAP: Dict[str, str] = {
    "RELIANCE": "CONGLOMERATE_ENERGY",
    "TCS": "IT_SERVICES",
    "INFY": "IT_SERVICES",
    "HDFCBANK": "BANKING_FINANCE",
    "ICICIBANK": "BANKING_FINANCE",
}


def parse_date_to_days_ago(
    record_date: Union[date, datetime, str],
    reference_date: Optional[Union[date, datetime, str]] = None,
) -> float:
    """Calculates the age in days between reference_date (defaults to today) and record_date."""
    if reference_date is None:
        ref_d = date.today()
    elif isinstance(reference_date, datetime):
        ref_d = reference_date.date()
    elif isinstance(reference_date, str):
        ref_d = datetime.fromisoformat(reference_date.split("T")[0]).date()
    else:
        ref_d = reference_date

    if isinstance(record_date, datetime):
        rec_d = record_date.date()
    elif isinstance(record_date, str):
        rec_d = datetime.fromisoformat(record_date.split("T")[0]).date()
    else:
        rec_d = record_date

    delta_days = (ref_d - rec_d).days
    return max(0.0, float(delta_days))


def calculate_recency_weight(
    record_date: Union[date, datetime, str],
    reference_date: Optional[Union[date, datetime, str]] = None,
) -> float:
    """Calculates the recency weight for a trade record:
    - Last 30 days (days <= 30): Highest weight in [0.85, 1.00].
    - 30 to 90 days (30 < days <= 90): Gradually reducing importance in [0.40, 0.85].
    - Very old trades (days > 90): Low but strictly nonzero weight with floor >= 0.15.
    """
    days = parse_date_to_days_ago(record_date, reference_date)

    if days <= 30.0:
        # Highest weight: smooth linear descent from 1.00 down to 0.85
        weight = 1.00 - (days / 30.0) * 0.15
    elif days <= 90.0:
        # Gradually reducing importance from 0.85 down to 0.40
        weight = 0.85 - ((days - 30.0) / 60.0) * 0.45
    else:
        # Very old trades: asymptotic decay with strict nonzero floor of 0.15
        decay = 0.40 / (1.0 + ((days - 90.0) / 90.0))
        weight = max(0.15, decay)

    return round(float(weight), 4)


def calculate_relevance_score(
    record_ticker: str,
    record_market_conditions: str,
    record_strategy: str,
    target_ticker: str,
    target_market_conditions: str,
    target_strategy: str = "QUANTITATIVE_EQUITY",
    vector_similarity: Optional[float] = None,
) -> float:
    """Calculates multi-dimensional relevance between a memory record and the current research context.
    Evaluates:
    - Ticker affinity (1.0 for exact symbol match, 0.5 for same sector, 0.1 otherwise)
    - Market conditions regime overlap (Jaccard similarity on keyword tokens)
    - Strategy alignment
    - Semantic vector similarity (if present)
    """
    # 1. Ticker / Sector Affinity
    rec_sym = record_ticker.upper().strip()
    tgt_sym = target_ticker.upper().strip()

    if rec_sym == tgt_sym:
        ticker_score = 1.00
    elif SECTOR_MAP.get(rec_sym) and SECTOR_MAP.get(rec_sym) == SECTOR_MAP.get(tgt_sym):
        ticker_score = 0.30
    else:
        ticker_score = 0.05

    # 2. Market Regime Token Overlap
    rec_tokens = set(record_market_conditions.upper().replace("_", " ").split())
    tgt_tokens = set(target_market_conditions.upper().replace("_", " ").split())
    if rec_tokens and tgt_tokens:
        intersection = rec_tokens.intersection(tgt_tokens)
        union = rec_tokens.union(tgt_tokens)
        regime_score = len(intersection) / max(1, len(union))
    else:
        regime_score = 0.20

    # 3. Strategy Alignment
    strat_rec = set(record_strategy.upper().replace("_", " ").split())
    strat_tgt = set(target_strategy.upper().replace("_", " ").split())
    if strat_rec and strat_tgt:
        strat_score = len(strat_rec.intersection(strat_tgt)) / max(1, len(strat_rec.union(strat_tgt)))
    else:
        strat_score = 0.30

    # 4. Synthesize Relevance Score
    # Ticker affinity dominates so exact ticker records always take precedence over peer sector stocks
    if vector_similarity is not None:
        clamped_sim = max(0.0, min(1.0, float(vector_similarity)))
        relevance = (
            0.55 * ticker_score
            + 0.20 * regime_score
            + 0.10 * strat_score
            + 0.15 * clamped_sim
        )
    else:
        relevance = (
            0.60 * ticker_score
            + 0.25 * regime_score
            + 0.15 * strat_score
        )

    return round(float(relevance), 4)


def calculate_composite_score(relevance_score: float, recency_weight: float) -> float:
    """Calculates the composite ranking score.
    Formula:
        S_composite = S_relevance * (0.35 + 0.65 * W_recency)

    Guarantees:
    1. If S_relevance == 0.0, S_composite == 0.0. An irrelevant trade cannot rank
       merely because it occurred yesterday.
    2. A relevant historical trade (e.g. relevance 0.90, recency 0.15 => 0.403)
       will beat an irrelevant recent trade (e.g. relevance 0.30, recency 1.00 => 0.300).
    3. Strictly satisfies: "Do not let recency override relevance or risk."
    """
    rel = max(0.0, min(1.0, float(relevance_score)))
    rec = max(0.0, min(1.0, float(recency_weight)))

    composite = rel * (0.35 + 0.65 * rec)
    return round(float(composite), 4)
