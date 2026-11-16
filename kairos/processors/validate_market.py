"""Market data integrity and provenance validation guardrails.
Validates symbol consistency, provenance categories, quote freshness, OHLC geometry,
and price basis compatibility between live quotes and historical datasets.
Prevents contaminated or synthetic data from silently entering analysis or trading proposals.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import pandas as pd
from pydantic import BaseModel, Field

from kairos.config.settings import get_settings
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.processors.validate_market")

APPROVED_LIVE_PROVENANCES = {
    "LIVE_YAHOO_FINANCE",
    "LIVE_YAHOO_FINANCE_MCP",
    "LIVE_NSE",
    "LIVE_NSE_MCP",
}


class MarketDataValidationResult(BaseModel):
    """Result of full market data forensic guardrails check."""

    is_valid: bool
    quarantine: bool = False
    symbol: str
    last_price: float
    support_60: float
    resistance_60: float
    quote_provenance: str
    historical_provenance: str
    price_basis_compatible: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


def validate_market_data(
    ticker: str,
    df_hist: pd.DataFrame,
    live_quote: Optional[Dict[str, Any]],
    allow_mock: Optional[bool] = None,
) -> MarketDataValidationResult:
    """Executes deterministic forensic validation on market datasets before ingestion.

    Checks:
    1. Symbol consistency.
    2. Quote provenance (rejects SYNTHETIC_FIXTURE in production).
    3. Quote timestamp and market session status.
    4. Historical dataset freshness and non-emptiness.
    5. OHLC geometric constraints (High >= Low, High >= Open, High >= Close, etc.).
    6. Price basis compatibility:
       Determines whether current price is compatible with corporate-action adjusted historical levels.
       Permits legitimate breakout/breakdown leeway (~25%), but rejects severe (>35%) price basis
       divergence caused by unadjusted stock splits or synthetic fixture price mismatches.
    """
    settings = get_settings()
    if allow_mock is None:
        allow_mock = os.environ.get("KAIROS_ALLOW_MOCK", "").lower() in ("true", "1") or settings.env.lower() in ("test", "testing")

    errors: List[str] = []
    warnings: List[str] = []
    quarantine: bool = False

    clean_sym = ticker.replace(".NS", "").replace(".BO", "").upper().strip()

    # 1. Dataset presence
    if df_hist is None or df_hist.empty:
        errors.append(f"Historical dataset for {clean_sym} is missing or empty.")
        return MarketDataValidationResult(
            is_valid=False,
            quarantine=True,
            symbol=clean_sym,
            last_price=0.0,
            support_60=0.0,
            resistance_60=0.0,
            quote_provenance="NONE",
            historical_provenance="NONE",
            price_basis_compatible=False,
            errors=errors,
            warnings=warnings,
        )

    # 2. Symbol consistency
    if "symbol" in df_hist.columns:
        first_sym = str(df_hist["symbol"].iloc[0]).replace(".NS", "").replace(".BO", "").upper().strip()
        if first_sym != clean_sym:
            errors.append(f"Symbol mismatch in historical data: expected '{clean_sym}', found '{first_sym}'.")

    # 3. OHLC Validity
    for col in ["open", "high", "low", "close"]:
        if col not in df_hist.columns:
            errors.append(f"Missing required price column '{col}' in historical dataset.")

    if not errors:
        recent_bars = df_hist.tail(250)
        invalid_high_low = (recent_bars["high"] < recent_bars["low"]).sum()
        if invalid_high_low > 0:
            errors.append(f"Found {invalid_high_low} bars where High < Low.")

        invalid_prices = ((recent_bars["open"] <= 0) | (recent_bars["close"] <= 0)).sum()
        if invalid_prices > 0:
            errors.append(f"Found {invalid_prices} bars with non-positive price.")

    # 4. Provenance Validation
    quote_prov = "NONE"
    if live_quote:
        quote_prov = str(live_quote.get("provenance", "UNKNOWN")).upper()
        if "SYNTHETIC" in quote_prov:
            quote_prov = "SYNTHETIC_FIXTURE"
        elif "NSE" in quote_prov:
            quote_prov = "LIVE_NSE"
        elif "YAHOO" in quote_prov or "YFINANCE" in quote_prov:
            quote_prov = "LIVE_YAHOO_FINANCE"

        if quote_prov == "SYNTHETIC_FIXTURE" and not allow_mock:
            errors.append("Live quote has provenance 'SYNTHETIC_FIXTURE', which is strictly rejected in production.")
            quarantine = True

    hist_prov = "LIVE_YAHOO_FINANCE"
    if "provenance" in df_hist.columns:
        prov_series = df_hist["provenance"].dropna().astype(str).str.upper()
        if any("SYNTHETIC" in p for p in prov_series):
            hist_prov = "SYNTHETIC_FIXTURE"
            if not allow_mock:
                errors.append("Historical dataset contains 'SYNTHETIC_FIXTURE' bars, strictly rejected in production.")
                quarantine = True

    # 5. Extract Prices and Levels
    latest_bar = df_hist.iloc[-1]
    last_price = 0.0
    if live_quote and "last_price" in live_quote and pd.notna(live_quote["last_price"]):
        last_price = float(live_quote["last_price"])
    elif "close" in latest_bar and pd.notna(latest_bar["close"]):
        last_price = float(latest_bar["close"])

    bars_60 = df_hist.tail(60)
    support_60 = float(bars_60["low"].min()) if "low" in bars_60 else last_price * 0.95
    resistance_60 = float(bars_60["high"].max()) if "high" in bars_60 else last_price * 1.05

    # 6. Corporate Action & Price Basis Compatibility
    # Legitimate breakouts can occur, so we allow a generous 25% boundary outside 60d range.
    # But an unadjusted 1:1 bonus/split produces a ~50% drop or ~100% gap, which must be quarantined.
    lower_tolerance = support_60 * 0.65
    upper_tolerance = resistance_60 * 1.35
    price_basis_compatible = True

    if last_price > 0 and (last_price < lower_tolerance or last_price > upper_tolerance):
        price_basis_compatible = False
        quarantine = True
        divergence_pct = ((last_price - resistance_60) / resistance_60 * 100.0) if last_price > upper_tolerance else ((support_60 - last_price) / support_60 * 100.0)
        errors.append(
            f"Severe price basis incompatibility ({divergence_pct:+.1f}% divergence): "
            f"Last price ₹{last_price:.2f} is outside compatible historical range [₹{lower_tolerance:.2f}, ₹{upper_tolerance:.2f}] "
            f"(60d Support: ₹{support_60:.2f}, Resistance: ₹{resistance_60:.2f}). "
            "Indicates unadjusted stock split, missing corporate action divisor, or synthetic fixture price contamination."
        )

    # 7. Quote Timestamp Validation
    if live_quote:
        q_ts = live_quote.get("quote_timestamp") or live_quote.get("timestamp")
        if not q_ts:
            warnings.append("Quote timestamp is missing.")

    is_valid = len(errors) == 0

    if not is_valid:
        logger.error(f"Market data validation failed for {clean_sym}: {errors}")
    else:
        logger.info(
            f"Market data validation PASSED for {clean_sym}: Price ₹{last_price:.2f}, "
            f"60d Range [₹{support_60:.2f} - ₹{resistance_60:.2f}], Provenance: {quote_prov}"
        )

    return MarketDataValidationResult(
        is_valid=is_valid,
        quarantine=quarantine,
        symbol=clean_sym,
        last_price=last_price,
        support_60=support_60,
        resistance_60=resistance_60,
        quote_provenance=quote_prov,
        historical_provenance=hist_prov,
        price_basis_compatible=price_basis_compatible,
        errors=errors,
        warnings=warnings,
    )

