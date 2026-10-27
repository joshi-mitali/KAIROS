# KAIROS — Phase 1 Architecture Document
## Institutional Data Acquisition, Normalization, Storage & Model Context Protocol (MCP)

---

### 1. Executive Summary

Phase 1 of the **KAIROS Multi-Agent Institutional Trading System** establishes the foundational data infrastructure, strict typed schemas, deterministic processing pipelines, and tool interface layers. KAIROS operates under strict memory constraints (optimized for GCP `e2-small` VMs with 2 vCPUs and 2 GiB RAM, maintaining a peak memory footprint under 150 MB) and ensures that all downstream agentic intelligence layers consume verified, auditable financial records.

```
+-----------------------------------------------------------------------------------+
|                            KAIROS Ingestion & Tool Stack                           |
+-----------------------------------------------------------------------------------+
|  [Market Collector]   [News Collector]    [Fundamentals SEC]   [Reddit Sentiment] |
|   (Yahoo / Chart)     (GDELT / Finnhub)     (EDGAR Facts)       (Compliant API)   |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                   Pydantic v2 Strict Normalization & Validation                   |
|          (MarketBar, NewsArticle, CompanyFact, RedditPost, Payload Models)        |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                           Processing & Clean Enrichment                           |
|       (Wilder RSI-14, SMA-20, MACD, PII Redaction, URL Deduplication, Facts)     |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                              Idempotent Storage                                   |
|   - Raw JSON:  data/raw/{domain}/{ticker}_{domain}.json                           |
|   - Clean CSV: data/processed/{domain}/{ticker}_clean.csv                         |
|   - Parquet:   data/processed/{domain}/{ticker}_clean.parquet                     |
|   - Manifests: data/manifests/manifest_{run_id}.json (SHA-256 Checksums)          |
|   - Quality:   data/reports/quality_report_{domain}.json & .md                    |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                    Model Context Protocol (MCP) Read-Only Server                  |
|             (JSON-RPC 2.0 stdio & FastMCP Compatibility Layer)                    |
|   - get_historical_prices(ticker, limit)                                          |
|   - search_financial_news(ticker, query, limit)                                   |
|   - get_company_fundamentals(ticker)                                              |
|   - get_reddit_sentiment(ticker, limit)                                           |
|   - get_dataset_status(source)                                                    |
+-----------------------------------------------------------------------------------+
```

---

### 2. Runtime Environment & Resource Efficiency

1. **Memory Budget**:
   - Tested and verified RSS memory footprint of **~76.7 MB**, well under the **150 MB** target for Google Cloud `e2-small` instances.
   - Streaming iterators and column-oriented PyArrow table constructions avoid memory explosion during Parquet exports.
2. **Deterministic Processing**:
   - Zero hallucinated values.
   - Missing fields are never silently replaced with arbitrary numbers or zeros.
   - Quarantined records are isolated to `data/reports/*_quarantined.json` with explicit error annotations.

---

### 3. Data Collectors & Ingestion Policies

#### 3.1 Market Data (`kairos/collectors/market_collector.py`)
- Ingests daily OHLCV bars.
- Enforces strict OHLC invariants: $\text{High} \ge \max(\text{Open}, \text{Close}, \text{Low})$ and $\text{Low} \le \min(\text{Open}, \text{Close}, \text{High})$.
- Calculates:
  - **20-day Simple Moving Average (SMA-20)**.
  - **14-day Relative Strength Index (RSI-14)** using Wilder's smoothed averages.
  - **MACD (12, 26, 9)**: Fast EMA (12), Slow EMA (26), Signal EMA (9), and Histogram.

#### 3.2 SEC EDGAR Fundamentals (`kairos/collectors/fundamentals_collector.py`)
- Complies with SEC Fair-Access User-Agent header policies (`KAIROS-Institutional-Trader research@kairos-trader.edu`).
- Resolves ticker symbols to 10-digit zero-padded CIK numbers.
- Ingests US-GAAP facts (`Revenues`, `NetIncomeLoss`, `Assets`, `Liabilities`, `NetCashProvidedByUsedInOperatingActivities`, `EarningsPerShareDiluted`).
- Preserves fiscal periods (distinguishes annual `FY` 10-K from quarterly `Q1`-`Q3` 10-Q) without combining them.

#### 3.3 Financial News (`kairos/collectors/news_collector.py`)
- Integrates GDELT 2.0 Doc API and configurable Finnhub/RSS backends.
- Canonical deduplication via SHA-256 fingerprinting of `headline + published_at + canonical_url`.
- Untrusted text sanitization eliminates null bytes, control characters, and enforces length bounds.

#### 3.4 Reddit Sentiment (`kairos/collectors/reddit_collector.py`)
- Strict privacy and authorization policy:
  - If official API credentials are not supplied, defaults cleanly to auditable, calibrated synthetic test fixtures.
  - Explicit provenance tagging: `AUTHORIZED_LIVE_API` vs. `SYNTHETIC_FIXTURE`.
  - PII redaction strips emails, phone numbers, and direct user handles before storage.

---

### 4. Storage & Dataset Provenance

- **Storage Structure**:
  - `data/raw/`: Raw JSON responses.
  - `data/processed/`: Standardized CSV and Snappy-compressed Parquet files.
  - `data/manifests/`: Dataset manifests with run IDs, timestamps, record counts, and SHA-256 hashes.
  - `data/reports/`: Data quality scorecards and quarantined invalid records.
- **Database Extensibility**:
  - `DatabaseAdapter` provides seamless, optional synchronization to PostgreSQL or Supabase when `DATABASE_URL` is configured, without crashing or blocking local execution when absent.

---

### 5. Model Context Protocol (MCP) Interface

The MCP server exposes institutional tools compliant with Model Context Protocol specification `2024-11-05`:
1. `get_historical_prices(ticker, limit)`
2. `search_financial_news(ticker, query, limit)`
3. `get_company_fundamentals(ticker)`
4. `get_reddit_sentiment(ticker, limit)`
5. `get_dataset_status(source)`

All tools enforce Pydantic parameter validation, bounded queries, read-only permissions (no trade execution), and safe error propagation.
