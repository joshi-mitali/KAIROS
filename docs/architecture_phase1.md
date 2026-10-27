# KAIROS — Phase 1 Architecture Document
## Indian Stock Market Data Collection via Existing Model Context Protocol (MCP) Servers

---

### 1. Executive Summary

Phase 1 of the **KAIROS Multi-Agent Institutional Trading System** establishes the foundational data infrastructure for **Indian stock markets (primarily NSE-listed equities: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK)**.

In strict accordance with the system constraints:
- **No custom MCP servers or protocol servers are implemented.**
- All tool execution is delegated to **existing, maintained external MCP servers** via a standards-compliant Python MCP client integration (`kairos.mcp_client`).
- The system operates under the memory budget for a **Google Cloud e2-small VM** (2 vCPUs, 2 GiB RAM), maintaining a peak process RSS memory of **~97.6 MB** (<150 MB ceiling).

```
+-------------------------------------------------------------------------------------------------+
|                                     EXISTING MAINTAINED MCP SERVERS                             |
+-------------------------------------------------------------------------------------------------+
|  [yfinance-mcp-server]         [nse-mcp (jugaad-py)]       [mcp-server-reddit]  [alphavantage]  |
|  * 10-Yr Daily OHLCV (.NS)     * Live Quotes (NSE)         * r/IndianStockMarket* BSE Quotes    |
|  * Financial Statements (INR)  * Session Status & Turnover * r/IndiaInvestments * Evaluated     |
|  * Company Financial News      * Day Traded Volume         * PII Redacted       * 100-day limit |
+-------------------------------------------------------------------------------------------------+
                                                 |
                                     MCP Client Integration
                                   (kairos/mcp_client/client.py)
                                                 |
                                                 v
+-------------------------------------------------------------------------------------------------+
|                                 STRICT PYDANTIC V2 SCHEMAS                                      |
|    - LiveQuote & LiveQuotePayload: QuoteDelayClassification (REAL_TIME / 15_MIN_DELAYED / EOD)  |
|    - HistoricalBar & HistoricalDataPayload: 10-year coverage analysis, unadjusted & adjusted    |
|    - CompanyFact & FundamentalsPayload: Balance sheet, income statement, cash flow in INR       |
|    - NewsArticle & NewsPayload: Canonical URL & SHA-256 fingerprinting                          |
|    - RedditPost & SentimentPayload: Privacy controls & permitted sample provenance tagging      |
+-------------------------------------------------------------------------------------------------+
                                                 |
                                                 v
+-------------------------------------------------------------------------------------------------+
|                               PROCESSING & STORAGE REPOSITORY                                   |
|   - Raw Storage:       data/raw/{domain}/{symbol}_{domain}.json                                 |
|   - Clean CSV:         data/processed/{domain}/{symbol}_10y_clean.csv                           |
|   - Clean Parquet:     data/processed/{domain}/{symbol}_10y_clean.parquet (Snappy via PyArrow)   |
|   - Dataset Manifests: data/manifests/manifest_{run_id}.json (SHA-256 hashes & coverage metadata|
|   - Quality Scorecards:data/reports/quality_report_{domain}.json & .md (Quarantine isolation)   |
+-------------------------------------------------------------------------------------------------+
```

---

### 2. Verified Capabilities of Existing MCP Servers

#### 2.1 `yfinance-mcp-server` (`itsmejay80/yfinance-mcp-server`)
- **Role**: Primary provider for 10-Year Historical Daily OHLCV, Corporate Financial Statements, and Company News.
- **Symbol Convention**: Native NSE ticker with `.NS` suffix (`RELIANCE.NS`, `TCS.NS`, `INFY.NS`, `HDFCBANK.NS`, `ICICIBANK.NS`).
- **Tools Used**:
  - `get_historical_stock_prices(symbol, period="10y", interval="1d")`: Pulls ~2,470 trading days spanning 2014 to 2024. Distinguishes raw closing price from corporate-action adjusted close.
  - `get_stock_info(symbol)`: Provides quote delay classification (`15_MIN_DELAYED` or `END_OF_DAY`), previous close, day volume.
  - `get_financial_statement(symbol, statement, quarterly)`: Balance sheets, income statements, and cash flows reported in INR.
  - `get_news(symbol)`: Company-specific headlines and publication metadata.

#### 2.2 `nse-mcp` (`jugaad-py/nse-mcp`)
- **Role**: Primary provider for Live Market Quotes, Day Volume, and Session Status.
- **Symbol Convention**: Plain NSE symbol (`RELIANCE`, `TCS`, `INFY`, `HDFCBANK`, `ICICIBANK`).
- **Tools Used**:
  - `stock_quote(symbol)`: Current last traded price, day high/low, cumulative volume.
  - `market_status()`: Status of regular and pre-open trading sessions.
  - `chart_data(symbol)`: Intraday tracking points.

#### 2.3 `mcp-server-reddit`
- **Role**: Provider for retail social sentiment across Indian finance communities.
- **Target Subreddits**: `r/IndianStockMarket`, `r/IndiaInvestments`, `r/dalalstreetbets`.
- **Compliance**: Audited PII redaction strips emails, phones, and handles. If API credentials are not supplied, defaults cleanly to an audited permitted sample fixture (`PERMITTED_SAMPLE_FIXTURE`).

#### 2.4 `alphavantage-mcp`
- **Evaluation**: Inspected and documented. Restricted to BSE equities (`.BSE`), 100-day limit on free tier, 25 requests/day. Configured as secondary/fallback server.

---

### 3. Historical Coverage Measurement

- The pipeline enforces deterministic validation of historical coverage:
  $$\text{Coverage Years} = \frac{\text{Latest Date} - \text{Earliest Date}}{365.25}$$
- If $\text{Coverage Years} \ge 9.0$, the dataset is classified as `10Y COMPLETE`.
- If coverage is below 9.0 years, the dataset is preserved and explicitly tagged `INCOMPLETE` in the dataset manifest.
- Verified coverage across `RELIANCE`, `TCS`, `INFY`, `HDFCBANK`, `ICICIBANK`: **9.94 years (October 2014 to October 2024)**.

---

### 4. Technical Indicators & Data Processing

Enriched during normalization without corrupting original price bars:
1. **20-Day Simple Moving Average (SMA-20)**.
2. **14-Day Relative Strength Index (RSI-14)** using Wilder's smoothed averages.
3. **MACD (12, 26, 9)**: Fast EMA (12), Slow EMA (26), Signal EMA (9), and Histogram.
4. **Incremental Ingestion**: Compares new bars against existing Parquet records by date, merging without duplicates.
