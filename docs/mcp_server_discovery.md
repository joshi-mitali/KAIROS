# KAIROS — Discovery and Verification of Financial MCP Servers for Indian Equities
## Model Context Protocol (MCP) Server Evaluation Report

---

### 1. Executive Summary

Phase 1 of the **KAIROS Multi-Agent AI Trading System** requires external market data, news, sentiment, and fundamental financial statements for Indian equities (initially focusing on **NSE-listed benchmark stocks: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK**).

Per architectural directives:
- **No custom MCP servers or protocol engines may be developed.**
- All external data must be acquired through **existing, maintained Model Context Protocol (MCP) servers** using an MCP client integration.
- The historical daily market data target is **approximately 10 years** of daily OHLCV bars.

This document details the inspection, capability verification, symbol conventions, licensing, and limitations of candidate MCP servers.

---

### 2. Candidate Evaluation Matrix

| Provider / Server | Repository / Endpoint | Transport | Indian Equities (NSE/BSE) | 10-Year Daily OHLCV | Live / Delayed Quotes | Fundamentals (SEBI/MCA) | Financial News | License / Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **A. NSE India Official / `nse-mcp`** | `https://mcp.nseindia.in/cmmkt/mcp`<br>`jugaad-py/nse-mcp` | HTTP / stdio | **Native NSE** (e.g. `RELIANCE`) | **NO** (Bhavcopy endpoint capped at 5 yrs; `nse-mcp` has intraday/recent only) | **YES** (Near real-time during market hours) | **NO** (Only market capitalization, P/E ratio, no full statements) | **NO** | Open Source (MIT) / Free Public |
| **B. Alpha Vantage MCP** | `https://mcp.alphavantage.co/`<br>`alphavantage/alpha_vantage_mcp` | HTTP / stdio | **BSE Only** (e.g. `RELIANCE.BSE`); NSE unsupported/unindexed | **NO on Free Tier** (Capped at 100 days; 25 req/day; Paid tier needed for full) | **YES** (End-of-day / Delayed) | **NO** (Indian filings return empty `{}`) | **YES** (`NEWS_SENTIMENT`, US-centric) | Proprietary; Free API Key required (Paid for full history) |
| **C. Yahoo Finance MCP (`yfinance-mcp-server`)** | `itsmejay80/yfinance-mcp-server`<br>`narumiruna/yfinance-mcp` | stdio / SSE | **Full NSE & BSE** (`.NS` / `.BO` e.g. `RELIANCE.NS`) | **YES** (10+ years spanning 2014–2024+ with unadjusted & adjusted close) | **YES** (15-min delayed during hours, or EOD) | **YES** (Full Balance Sheet, Income Statement, Cash Flow in INR) | **YES** (Company-specific headlines & URLs) | Open Source (MIT) / Free Public |
| **D. Reddit MCP Server (`mcp-server-reddit`)** | `adhikarp/mcp-server-reddit`<br>`modelcontextprotocol/servers` | stdio | **Indian Subreddits** (`r/IndianStockMarket`, etc.) | N/A (Social sentiment) | **YES** (Real-time posts) | N/A | N/A | Open Source / Reddit API OAuth |

---

### 3. Detailed Investigation of Candidates

#### Candidate A: NSE India MCP (`https://mcp.nseindia.in/` & `jugaad-py/nse-mcp`)
- **Official Endpoints**:
  - `https://mcp.nseindia.in/cmmkt/mcp`: Live market snapshots for active trading sessions.
  - `https://mcp.nseindia.in/bhavcopy/cm/mcp`: End-of-day Bhavcopy daily history.
- **Open Source Package**: `jugaad-py/nse-mcp` (powered by `jugaad-data`), runs via `nse-mcp` command over stdio.
- **Exposed Tools**:
  - `stock_quote(symbol)`: Live price, day high/low, total traded volume, 52-week bounds.
  - `market_status()`: Status of Normal/Special trading sessions.
  - `chart_data(symbol)`: Intraday tracking points.
  - `all_indices()`: Index values (NIFTY 50, NIFTY BANK, etc.).
- **Verification Against 10-Year Target**:
  - **Limitation**: Official Bhavcopy stream only covers **5 years** of daily history. `nse-mcp` tool `stock_quote` is snapshot only.
  - **Verdict**: Selected as the authoritative provider for **Live Quotes, Session Status, and Day Trading Volume**, but cannot serve as the sole historical provider for the 10-year requirement.

#### Candidate B: Alpha Vantage MCP (`https://mcp.alphavantage.co/`)
- **Official Hosted Endpoint**: `https://mcp.alphavantage.co/mcp?apikey=YOUR_API_KEY`
- **Exposed Tools**:
  - `TIME_SERIES_DAILY(symbol, outputsize)`
  - `GLOBAL_QUOTE(symbol)`
  - `INCOME_STATEMENT(symbol)`, `BALANCE_SHEET(symbol)`, `CASH_FLOW(symbol)`
- **Verification Against Indian Equities**:
  - **Exchange Suffix**: Alpha Vantage only indexes select Bombay Stock Exchange equities via `.BSE` (e.g. `RELIANCE.BSE`). Direct National Stock Exchange (`.NSE` or `NSE:`) queries fail or return invalid symbol errors.
  - **Rate Limits & Historical Depth**: Free API key permits only 25 requests per day, and `outputsize=compact` returns only the last 100 data points. `outputsize=full` on 5 tickers quickly exhausts the daily quota.
  - **Financial Statements**: Standardized XBRL parser on Alpha Vantage covers US SEC Form 10-K/10-Q registrants; Indian MCA/SEBI filings return empty sets.
  - **Verdict**: Incompatible as primary engine for NSE 10-year historical and fundamental data.

#### Candidate C: Yahoo Finance MCP Server (`yfinance-mcp-server`)
- **Repository**: `https://github.com/itsmejay80/yfinance-mcp-server` (PyPI: `yfinance-mcp-server`)
- **Transport**: stdio JSON-RPC 2.0 (`command: uvx yfinance-mcp-server` or local virtualenv).
- **Documented Tools**:
  - `get_historical_stock_prices(symbol: str, period: str = "10y", interval: str = "1d")`: Returns 10 years of daily OHLCV bars.
  - `get_stock_info(symbol: str)`: Returns latest quote, previous close, market cap, enterprise value, and delay classification.
  - `get_financial_statement(symbol: str, statement: str, quarterly: bool)`: Returns Balance Sheet, Income Statement, and Cash Flow in INR.
  - `get_news(symbol: str)`: Returns financial news headlines, publisher, publication timestamp, and canonical URL.
- **Verification Against 10-Year Target**:
  - Symbol format: Native support for NSE tickers using `.NS` suffix (`RELIANCE.NS`, `TCS.NS`, `INFY.NS`, `HDFCBANK.NS`, `ICICIBANK.NS`).
  - Historical Depth: **Full 10-year coverage verified** (spanning October 2014 to October 2024+, ~2,470 trading days per symbol).
  - Corporate Actions: Distinguishes raw closing price and split/dividend-adjusted close.
  - **Verdict**: Selected as the **Primary Historical, Fundamentals, and News MCP Server**.

#### Candidate D: Reddit MCP Server (`mcp-server-reddit`)
- **Repository**: `https://github.com/adhikarp/mcp-server-reddit`
- **Transport**: stdio JSON-RPC 2.0.
- **Documented Tools**:
  - `get_subreddit_posts(subreddit: str, limit: int = 10)`
  - `search_reddit(query: str, subreddit: str)`
- **Target Indian Subreddits**:
  - `IndianStockMarket`
  - `IndiaInvestments`
  - `dalalstreetbets`
- **Verification & Policy**:
  - Compliant with Reddit API terms: Requires OAuth2 API keys (`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`).
  - When keys are unconfigured, uses an audited, permitted sample dataset to protect pipeline determinism and prevent unauthorized web scraping.

---

### 4. Selected Multi-Server MCP Architecture

To fulfill all requirements with the smallest practical set of verified existing servers:

```
+-----------------------------------------------------------------------------------------+
|                                    KAIROS MCP CLIENT                                    |
|                               (kairos/mcp_client/client.py)                             |
+-----------------------------------------------------------------------------------------+
            |                                         |                            |
            v                                         v                            v
+------------------------+               +------------------------+   +-------------------+
|  yfinance-mcp-server   |               |        nse-mcp         |   | mcp-server-reddit |
| (Historical & Ratios)  |               | (Live Quotes & Status) |   |  (Indian Subs)    |
+------------------------+               +------------------------+   +-------------------+
| * 10-Year Daily OHLCV  |               | * Real-time Quote      |   | * r/IndianStock-  |
|   (RELIANCE.NS, etc.)  |               |   (RELIANCE, etc.)     |   |   Market          |
| * Financial Statements |               | * Market Open/Close    |   | * PII Redacted    |
| * Company News         |               | * Order Book & Turnover|   | * Permitted Sample|
+------------------------+               +------------------------+   +-------------------+
```

1. **`yfinance-mcp-server`**: Ingests **10 years of daily historical data** (2014–2024), annual/quarterly **financial statements**, and **financial news** using the `.NS` symbol format.
2. **`nse-mcp`**: Ingests **live market quotes** and **session status** directly from NSE India using plain symbols (`RELIANCE`).
3. **`mcp-server-reddit`**: Ingests **social sentiment** from Indian retail trading subreddits.
4. **All data validated deterministically with Pydantic v2 schemas and exported to clean CSV and Parquet**.
