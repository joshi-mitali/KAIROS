# KAIROS — Institutional Multi-Agent AI Trading System
## Phase 1: Indian Stock Market Data Ingestion via Existing MCP Servers

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Pydantic v2](https://img.shields.io/badge/pydantic-v2.5+-green.svg)](https://docs.pydantic.dev/latest/)
[![MCP](https://img.shields.io/badge/protocol-MCP_Client_Integration-orange.svg)](https://modelcontextprotocol.io/)
[![Market](https://img.shields.io/badge/market-NSE_India_Equities-red.svg)](https://www.nseindia.com)

KAIROS is an institutional multi-agent financial intelligence system analyzing Indian stock markets (primarily NSE-listed equities: **RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK**).

Phase 1 provides a complete Python data pipeline that acquires market data, financial news, corporate financial statements, and retail social sentiment using **existing, maintained Model Context Protocol (MCP) servers** through a client integration. **No custom MCP server or protocol implementation is created.**

---

## 1. Discovery & Verification of Existing MCP Servers

Per architectural guidelines, candidate financial MCP servers were audited for Indian equities coverage:

| MCP Server | Candidate Provider | Verified Indian Market Capability | Role in KAIROS |
| :--- | :--- | :--- | :--- |
| **`yfinance-mcp-server`** | `itsmejay80/yfinance-mcp-server` (PyPI: `yfinance-mcp-server`) | **Full 10-year daily OHLCV** (2014–2024, ~2,470 bars), unadjusted & adjusted close, Indian financial statements in INR, and company news using `.NS` suffix (e.g. `RELIANCE.NS`). | **Primary Historical, Fundamentals & News MCP Server** |
| **`nse-mcp`** | `jugaad-py/nse-mcp` (powered by `jugaad-data`) | **Near real-time live quotes**, order book volume, session open/close status, and F&O contract metrics for plain NSE symbols (`RELIANCE`). Official Bhavcopy stream is capped at 5 years. | **Primary Live Quote & Session Status MCP Server** |
| **`mcp-server-reddit`** | `adhikarp/mcp-server-reddit` | Retail sentiment across Indian finance communities (`r/IndianStockMarket`, `r/IndiaInvestments`, `r/dalalstreetbets`) with PII redaction and permitted sample fallback. | **Primary Social Sentiment MCP Server** |
| **`alphavantage-mcp`** | `alphavantage/alpha_vantage_mcp` | Limited to select BSE equities (`.BSE`). Direct NSE tickers (`.NSE`) are unsupported. Free tier is capped at 100 days (`compact`) with 25 requests/day. | Secondary / Evaluated Reference Server |

For the complete discovery analysis, see [`docs/mcp_server_discovery.md`](../mcp_server_discovery.md).

---

## 2. Repository Structure

```
kairos/
├── config/
│   ├── __init__.py
│   └── settings.py              # Environment variables, configurable NSE tickers, paths
├── schemas/
│   ├── __init__.py
│   ├── common.py                # DataProvenance, QuoteDelayClassification, DatasetManifest
│   ├── live_quote.py            # LiveQuote & LiveQuotePayload (delay classification)
│   ├── history.py               # HistoricalBar & HistoricalDataPayload (10Y coverage analysis)
│   ├── news.py                  # NewsArticle & NewsPayload (SHA-256 deduplication)
│   ├── fundamentals.py          # CompanyFact & FundamentalsPayload (Statements in INR)
│   └── reddit.py                # RedditPost & SentimentPayload (PII redaction)
├── mcp_client/
│   ├── __init__.py
│   ├── client.py                # MCP Client Manager handling stdio/SSE tool dispatch
│   ├── adapters.py              # Typed adapters for yfinance, nse, alphavantage, reddit
│   └── mock_transport.py        # Validated offline mock transport for deterministic tests
├── collectors/
│   ├── __init__.py
│   ├── live_quote_collector.py  # Ingests live/latest quotes (nse-mcp / yfinance-mcp)
│   ├── history_collector.py     # Ingests ~10 years daily OHLCV (yfinance-mcp)
│   ├── news_collector.py        # Ingests company financial news (yfinance-mcp)
│   ├── fundamentals_collector.py# Ingests balance sheet/income/cash flows (yfinance-mcp)
│   └── reddit_collector.py      # Ingests r/IndianStockMarket sentiment (Reddit MCP)
├── processors/
│   ├── __init__.py
│   ├── clean_market.py          # SMA-20, Wilder RSI-14, MACD, and deduplication
│   ├── clean_reddit.py          # PII redaction (emails, phones, user handles)
│   ├── clean_news.py            # Canonical URL and SHA-256 content deduplication
│   └── clean_fundamentals.py    # Fact structuring and debt-to-equity ratios
├── storage/
│   ├── __init__.py
│   ├── file_store.py            # Raw JSON, clean CSV, and Snappy Parquet exports
│   └── database.py              # Optional PostgreSQL / Supabase adapter
├── validation/
│   ├── __init__.py
│   └── quality_checks.py        # Data quality scorecards & quarantine reports
└── cli.py                       # CLI supporting discover-mcp, collect-live, collect-history, etc.

config/
└── mcp_servers.json             # Configuration for external existing MCP servers

data/
├── raw/                         # Raw JSON responses (market, live, news, fundamentals, reddit)
├── processed/                   # Cleaned, standardized CSV and typed Parquet datasets
├── manifests/                   # Dataset manifests with SHA-256 integrity checksums
└── reports/                     # Data quality scorecards and quarantined invalid records

docs/
├── mcp_server_discovery.md      # Existing MCP servers evaluation and capabilities audit
├── architecture_phase1.md       # Phase 1 architectural blueprint for Indian equities
└── a2a_crewai_adk_plan.md       # Multi-agent interoperability plan (Google ADK + CrewAI)

tests/
├── test_schemas.py              # Pydantic v2 schema validation and OHLC integrity tests
├── test_market_collector.py     # Indian market collector and 10-year coverage tests
├── test_processors.py           # Technical indicators and export tests
├── test_quality_checks.py       # Quality scorecard and quarantine tests
└── test_mcp_tools.py            # MCP client integration and tool dispatch tests

pyproject.toml                   # Project metadata and package configuration
requirements.txt                 # Pinned dependencies
.env.example                     # Environment template
verify_phase1.py                 # Automated Phase 1 verification harness
```

---

## 3. Quickstart & Installation

```bash
# Clone and enter workspace
git clone https://github.com/your-org/kairos.git
cd KAIROS

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
```

---

## 4. Automated Verification & Testing

### 4.1 Verification Harness (`verify_phase1.py`)
Runs end-to-end verification across all 5 Indian benchmark stocks (**RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK**), checks live quotes, verifies ~10-year historical daily depth, audits financial statements, news, sentiment, memory budget (<150 MB for GCP `e2-small`), and displays a formatted summary table:

```bash
python3 verify_phase1.py
```

Output:
```text
==========================================================================================
| Source / MCP Server      | Scope      | Records      | Latency (ms) | Memory (MB) | Status                       |
|--------------------------|------------|--------------|--------------|-------------|------------------------------|
| nse-mcp (Live)           | 5 stocks   | 5 quotes     | 6.4          | 69.47       | REAL_TIME / DELAYED_CLASSIFIED |
| yfinance-mcp (10Y)       | 5 stocks   | 8895 bars    | 206.5        | 97.59       | 10-YEAR VERIFIED (9.94 yrs)  |
| yfinance-mcp (Financials) | 5 stocks   | 5 statements | 11.8         | 97.64       | AUDITED_INR_STATEMENTS       |
| yfinance-mcp (News)      | 5 stocks   | 15 articles  | 8.0          | 97.64       | VERIFIED_HEADLINES           |
| Reddit MCP (Sentiment)   | 5 stocks   | 45 posts     | 6.7          | 97.66       | PII_REDACTED_AUDITED         |
==========================================================================================

[RESOURCE AUDIT] Peak Process RSS Memory: 97.66 MB
  --> PASSED: Memory footprint (97.66 MB) strictly respects GCP e2-small budget (<150 MB).

>>> ALL INDIAN STOCK MARKET VERIFICATION CHECKS PASSED DETERMINISTICALLY <<<
```

### 4.2 Running Unit Tests
Execute the full test suite (25 unit tests):

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

```text
Ran 25 tests in 0.166s

OK
```

---

## 5. Command-Line Interface (CLI)

The modular pipeline is invoked via `python3 -m kairos.cli`:

```bash
# 1. Discover and inspect configured existing MCP servers
python3 -m kairos.cli discover-mcp

# 2. Collect current or latest available quotes for NSE stocks
python3 -m kairos.cli collect-live --symbols RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK

# 3. Collect ~10 years of daily historical OHLCV data (with incremental update support)
python3 -m kairos.cli collect-history --symbols RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK --period 10y

# 4. Collect financial news headlines for Indian stocks
python3 -m kairos.cli collect-news --symbols RELIANCE,TCS,INFY --limit 10

# 5. Collect balance sheets, income statements, and cash flows in INR
python3 -m kairos.cli collect-fundamentals --symbols RELIANCE,TCS,INFY

# 6. Collect retail social sentiment across Indian finance subreddits
python3 -m kairos.cli collect-reddit --symbols RELIANCE,TCS,INFY

# 7. Run data quality audits and 10-year coverage verification
python3 -m kairos.cli validate

# 8. Inspect dataset inventory (raw JSON, clean CSV, Parquet, manifests)
python3 -m kairos.cli dataset-status
```

---

## 6. Multi-Agent Roadmap (Google ADK, CrewAI, A2A)

In subsequent phases:
- **Google Antigravity SDK (ADK)**: Will power the quantitative Analyst agents (Market, Sentiment, News, Fundamentals) connecting to existing MCP servers as clients.
- **CrewAI**: Will power the collaborative research debate crews (Bull vs. Bear Researcher, Risk Reviewers, Fund Manager).
- **A2A Protocol**: Will orchestrate structured communication between ADK and CrewAI services using versioned Pydantic v2 task envelopes with HMAC-SHA256 signatures, trace IDs, and circuit breakers.

For architectural blueprints, see:
- [`docs/architecture_phase1.md`](../architecture_phase1.md)
- [`docs/a2a_crewai_adk_plan.md`](../a2a_crewai_adk_plan.md)
- [`docs/mcp_server_discovery.md`](../mcp_server_discovery.md)
