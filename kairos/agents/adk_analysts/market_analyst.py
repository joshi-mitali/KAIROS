"""Google ADK Market Analyst Agent for KAIROS.
Consumes 10-year OHLCV bars and live quotes to generate technical analysis reports.
"""

from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
import pandas as pd

from kairos.a2a.contract import A2AMessageType
from kairos.agents.adk_analysts.base_analyst import BaseADKAnalyst
from kairos.processors.validate_market import validate_market_data
from kairos.schemas.analyst_reports import (
    MarketAnalysisReport,
    SignalStrength,
    TechnicalIndicatorsSnapshot,
    TrendDirection,
)
from kairos.config.agent_definitions import render_task
from kairos.utils.logging_config import get_logger

logger = get_logger("kairos.agents.adk_analysts.market")


class MarketAnalyst(BaseADKAnalyst):
    """Specialist Analyst evaluating technical price action, momentum, and key support/resistance."""

    agent_name: str = "google_adk.market_analyst"
    config_key: str = "market_analyst"
    task_message_type: A2AMessageType = A2AMessageType.MARKET_REPORT
    output_schema = MarketAnalysisReport

    def _load_historical_bars(self, ticker: str) -> pd.DataFrame:
        market_dir = self.data_dir / "processed" / "market"
        pq_path = market_dir / f"{ticker.lower()}_10y_clean.parquet"
        csv_path = market_dir / f"{ticker.lower()}_10y_clean.csv"

        if pq_path.exists():
            return pd.read_parquet(pq_path)
        elif csv_path.exists():
            return pd.read_csv(csv_path)
        else:
            raise FileNotFoundError(
                f"No historical market data found for {ticker} in {market_dir}"
            )

    def _load_live_quote(self, ticker: str) -> Optional[dict]:
        live_dir = self.data_dir / "processed" / "live"
        pq_path = live_dir / f"{ticker.lower()}_live.parquet"
        csv_path = live_dir / f"{ticker.lower()}_live.csv"

        if pq_path.exists():
            df = pd.read_parquet(pq_path)
            return df.iloc[-1].to_dict()
        elif csv_path.exists():
            df = pd.read_csv(csv_path)
            return df.iloc[-1].to_dict()
        return None

    def run_analysis(
        self, ticker: str, trace_id: Optional[str] = None
    ) -> MarketAnalysisReport:
        df_hist = self._load_historical_bars(ticker)
        live_quote = self._load_live_quote(ticker)

        # Enforce market data integrity guardrails
        validation = validate_market_data(ticker, df_hist, live_quote)
        if not validation.is_valid:
            raise ValueError(
                f"MarketAnalyst rejected invalid market data for {ticker}: {'; '.join(validation.errors)}"
            )

        latest_bar = df_hist.iloc[-1]
        as_of_date = str(latest_bar.get("date", datetime.now(timezone.utc).date().isoformat()))[:10]

        # Use live quote last_price if available, else latest bar close
        if (
            live_quote
            and "last_price" in live_quote
            and pd.notna(live_quote["last_price"])
        ):
            last_price = float(live_quote["last_price"])
            quote_delay = str(live_quote.get("quote_delay", "15_MIN_DELAYED"))
        else:
            last_price = float(latest_bar.get("close", 0.0))
            quote_delay = "15_MIN_DELAYED"

        # Extract or compute indicators
        sma_20 = (
            float(latest_bar.get("sma_20"))
            if pd.notna(latest_bar.get("sma_20"))
            else float(df_hist["close"].tail(20).mean())
        )
        rsi_14 = (
            float(latest_bar.get("rsi_14"))
            if pd.notna(latest_bar.get("rsi_14"))
            else 50.0
        )
        macd_line = (
            float(latest_bar.get("macd")) if pd.notna(latest_bar.get("macd")) else 0.0
        )
        macd_signal = (
            float(latest_bar.get("macd_signal"))
            if pd.notna(latest_bar.get("macd_signal"))
            else 0.0
        )
        macd_hist = (
            float(latest_bar.get("macd_histogram"))
            if pd.notna(latest_bar.get("macd_histogram"))
            else (macd_line - macd_signal)
        )

        # 52-week high / low (approx 250 trading bars)
        bars_250 = df_hist.tail(250)
        high_52w = float(bars_250["high"].max()) if "high" in bars_250 else None
        low_52w = float(bars_250["low"].min()) if "low" in bars_250 else None

        # 60-day support and resistance
        bars_60 = df_hist.tail(60)
        support_level = (
            float(bars_60["low"].min())
            if "low" in bars_60
            else round(last_price * 0.95, 2)
        )
        resistance_level = (
            float(bars_60["high"].max())
            if "high" in bars_60
            else round(last_price * 1.05, 2)
        )

        # Determine trend direction
        if last_price >= sma_20 and macd_line >= macd_signal:
            trend_direction = TrendDirection.BULLISH
        elif last_price < sma_20 and macd_line < macd_signal and rsi_14 < 48.0:
            trend_direction = TrendDirection.BEARISH
        else:
            trend_direction = TrendDirection.NEUTRAL

        # Determine signal strength
        if (rsi_14 >= 65.0 or rsi_14 <= 35.0) and abs(macd_hist) > 2.0:
            signal_strength = SignalStrength.STRONG
        elif abs(rsi_14 - 50.0) >= 5.0 or abs(macd_hist) > 0.5:
            signal_strength = SignalStrength.MODERATE
        else:
            signal_strength = SignalStrength.WEAK

        key_observations = [
            f"Last traded price ₹{last_price:,.2f} ({quote_delay}) vs 20-day SMA of ₹{sma_20:,.2f}.",
            f"14-day RSI stands at {rsi_14:.2f}, indicating {trend_direction.value.lower()} momentum.",
            f"MACD line at {macd_line:.2f} vs signal {macd_signal:.2f} (Histogram: {macd_hist:+.2f}).",
            f"Key 60-day trading range defined by support at ₹{support_level:,.2f} and resistance at ₹{resistance_level:,.2f}.",
            f"52-week range: ₹{low_52w:,.2f} - ₹{high_52w:,.2f}.",
        ]

        indicators = TechnicalIndicatorsSnapshot(
            sma_20=round(sma_20, 2),
            rsi_14=round(rsi_14, 2),
            macd_line=round(macd_line, 2),
            macd_signal=round(macd_signal, 2),
            macd_histogram=round(macd_hist, 2),
        )

        fallback_report = MarketAnalysisReport(
            ticker=ticker,
            as_of_date=as_of_date,
            last_price=round(last_price, 2),
            quote_delay=quote_delay,
            indicators=indicators,
            trend_direction=trend_direction,
            signal_strength=signal_strength,
            support_level=round(support_level, 2),
            resistance_level=round(resistance_level, 2),
            fifty_two_week_high=round(high_52w, 2) if high_52w else None,
            fifty_two_week_low=round(low_52w, 2) if low_52w else None,
            bars_analyzed=len(df_hist),
            key_observations=key_observations,
            execution_mode="DETERMINISTIC_FALLBACK",
        )

        prompt = render_task(
            "market_analysis",
            ticker=ticker,
            last_price=last_price,
            quote_delay=quote_delay,
            sma_20=sma_20,
            rsi_14=rsi_14,
            macd_line=macd_line,
            macd_signal=macd_signal,
            support_level=support_level,
            resistance_level=resistance_level,
        )["description"]

        return self.invoke_gemini_analysis(
            prompt, MarketAnalysisReport, fallback_report
        )
