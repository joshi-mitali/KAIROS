# KAIROS — Institutional Multi-Agent AI Trading System
## Phase 1: Data Acquisition, Normalization, Storage and MCP Integration

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Pydantic v2](https://img.shields.io/badge/pydantic-v2.5+-green.svg)](https://docs.pydantic.dev/latest/)
[![MCP](https://img.shields.io/badge/protocol-MCP_2024--11--05-orange.svg)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

KAIROS is an institutional multi-agent financial intelligence and trading research platform. Designed for high reliability and memory-bounded cloud environments (GCP `e2-small` VM, 2 vCPUs, 2 GiB RAM, <150 MB process footprint), Phase 1 establishes the deterministic data ingestion layer, Pydantic v2 schemas, technical indicator calculations, raw and processed Parquet/CSV storage, dataset manifests with SHA-256 checksums, and a Model Context Protocol (MCP) tool server.

---

## 1. Repository Structure

```
kairos/
├── config/
│   ├── __init__.py
│   └── settings.py              # Environment variables and runtime configuration
├── schemas/
│   ├── __init__.py
│   ├── common.py                # Provenance, Manifest, and Source attribution models
│   ├── market.py                # MarketBar and MarketDataPayload (OHLC checks)
│   ├── reddit.py                # RedditPost and SentimentPayload (PII redaction)
│   ├── news.py                  # NewsArticle and NewsPayload (URL and SHA-256 deduplication)
│   └── fundamentals.py          # CompanyFact and FundamentalsPayload (SEC EDGAR XBRL)
├── collectors/
│   ├── __init__.py
│   ├── market_collector.py      # Historical OHLCV collector with retry/backoff
│   ├── reddit_collector.py      # Reddit sentiment collector (compliant fixture fallback)
│   ├── news_collector.py        # Financial news collector (GDELT / RSS)
│   └── fundamentals_collector.py # SEC EDGAR company facts collector (Fair-Access UA)
├── processors/
│   ├── __init__.py
│   ├── clean_market.py          # SMA-20, Wilder RSI-14, MACD, and deduplication
│   ├── clean_reddit.py          # PII redaction and text sanitization
│   ├── clean_news.py            # Canonical URL and SHA-256 hash deduplication
│   └── clean_fundamentals.py    # XBRL fact structuring and balance sheet ratios
├── storage/
│   ├── __init__.py
│   ├── file_store.py            # Raw JSON, clean CSV, and Snappy Parquet exports
│   └── database.py              # Optional PostgreSQL / Supabase adapter
├── mcp_server/
│   ├── __init__.py
│   ├── server.py                # JSON-RPC 2.0 stdio Model Context Protocol (MCP) server
│   └── tools.py                 # Tool registry with Pydantic validation
├── validation/
│   ├── __init__.py
│   └── quality_checks.py        # Data quality scorecard and invalid record quarantine
├── utils/
│   ├── __init__.py
│   ├── logging_config.py        # Structured logging with secret redaction
│   └── security.py              # Path traversal defense and ticker validation
└── cli.py                       # Command-line interface for pipelines and MCP service

data/
├── raw/                         # Raw ingested JSON responses (market, news, reddit, fundamentals)
├── processed/                   # Cleaned, standardized CSV and typed Parquet datasets
├── manifests/                   # Dataset manifests with SHA-256 integrity checksums
└── reports/                     # Data quality reports and quarantined invalid records

docs/
├── architecture_phase1.md       # Phase 1 architectural specification
└── a2a_crewai_adk_plan.md       # Future Google ADK + CrewAI interoperability plan

tests/
├── test_schemas.py              # Pydantic v2 schema validation and OHLC integrity tests
├── test_market_collector.py     # Market collector and retry logic tests
├── test_processors.py           # Technical indicators (SMA, RSI, MACD) and export tests
├── test_quality_checks.py       # Quality scorecard and quarantine tests
└── test_mcp_tools.py            # MCP tool registry and JSON-RPC dispatch tests

pyproject.toml                   # Project metadata and package configuration
requirements.txt                 # Pinned dependencies
.env.example                     # Sample environment variable template
.gitignore                       # Git exclusions
verify_phase1.py                 # Automated verification harness
```

---

## 2. Quickstart & Installation

### Prerequisites
- Python 3.11+
- Git

### Setup
```bash
# Clone repository
git clone https://github.com/your-org/kairos.git
cd KAIROS

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
```

---

## 3. Running Verification and Tests

### 3.1 Automated Phase 1 Verification Harness
Executes all 4 collectors for ticker `NVDA`, validates Pydantic schemas, asserts memory footprint (<150 MB for GCP `e2-small`), tests all 5 MCP tools, and prints a formatted summary table:

```bash
python3 verify_phase1.py
```

Sample output:
```text
================================================================================
| Source             | Ticker | Records  | Latency (ms) | Memory (MB) | Authenticity Status      |
|--------------------|--------|----------|--------------|-------------|--------------------------|
| Market Data        | NVDA   | 22       | 2033.4       | 76.70       | CALIBRATED_SAMPLE        |
| Financial News     | NVDA   | 5        | 3.9          | 76.70       | CALIBRATED_SAMPLE        |
| Fundamentals       | NVDA   | 10       | 5.3          | 76.70       | AUDITED_SEC_BASELINE     |
| Reddit Sentiment   | NVDA   | 15       | 2.5          | 76.70       | AUDITED_UNCONFIGURED_... |
================================================================================
```

### 3.2 Running Unit Tests
Execute the full test suite (27 unit tests):

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

---

## 4. Command-Line Interface (CLI)

The modular pipeline can be invoked via `python3 -m kairos.cli`:

| Command | Description | Example |
| :--- | :--- | :--- |
| `collect-market` | Collect historical OHLCV bars, compute SMA/RSI/MACD, export CSV/Parquet. | `python3 -m kairos.cli collect-market --tickers NVDA,AAPL` |
| `collect-news` | Collect financial headlines, deduplicate via SHA-256, export CSV/Parquet. | `python3 -m kairos.cli collect-news --tickers NVDA --limit 10` |
| `collect-fundamentals` | Fetch audited SEC EDGAR XBRL company facts and balance sheet ratios. | `python3 -m kairos.cli collect-fundamentals --tickers NVDA,MSFT` |
| `collect-reddit` | Collect discussion posts adhering to compliance rules with PII redaction. | `python3 -m kairos.cli collect-reddit --tickers NVDA` |
| `validate` | Run data quality audits and generate scorecards and quarantine files. | `python3 -m kairos.cli validate` |
| `collect-all` | Execute the complete ingestion, processing, and validation sequence. | `python3 -m kairos.cli collect-all --tickers NVDA,AAPL,MSFT` |
| `dataset-status` | Display local storage inventory (raw files, Parquets, manifests). | `python3 -m kairos.cli dataset-status` |
| `serve-mcp` | Launch the Model Context Protocol (MCP) server over stdio. | `python3 -m kairos.cli serve-mcp` |

---

## 5. Model Context Protocol (MCP) Server

KAIROS includes a standards-compliant Model Context Protocol server exposing read-only financial data tools to AI agents:

### Exposed Tools
1. `get_historical_prices(ticker: str, limit: int = 30)`:
   Returns validated historical price bars, volume, SMA-20, RSI-14, and MACD.
2. `search_financial_news(ticker: str, query: str = "", limit: int = 10)`:
   Searches financial news headlines, publisher metadata, and canonical URLs.
3. `get_company_fundamentals(ticker: str)`:
   Retrieves audited SEC EDGAR corporate facts, balance sheet ratios, revenue, net income, assets, and liabilities.
4. `get_reddit_sentiment(ticker: str, limit: int = 10)`:
   Gathers discussion posts and community sentiment metrics with PII redaction.
5. `get_dataset_status(source: str = "")`:
   Reports inventory of stored raw and processed datasets and manifests.

### Connecting Claude Desktop / Cursor / Antigravity IDE
Add the following to your MCP client configuration file (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "kairos-market-data": {
      "command": "python3",
      "args": ["-m", "kairos.mcp_server.server"],
      "cwd": "/path/to/KAIROS"
    }
  }
}
```

---

## 6. Architecture & Framework Roadmap

In subsequent phases:
- **Google Antigravity SDK (ADK)**: Powers quantitative analyst services (Market Analyst, Sentiment Analyst, News Analyst, Fundamentals Analyst) that consume tools via MCP.
- **CrewAI**: Powers multi-perspective research debate (Bull vs. Bear), risk-review crews, and fund management allocations.
- **A2A Protocol**: Connects ADK Analyst services to CrewAI deliberation crews over versioned Pydantic v2 schemas with distributed trace IDs.

For complete architectural details, see:
- [Phase 1 Architecture Document](docs/architecture_phase1.md)
- [A2A & CrewAI / Google ADK Interoperability Plan](docs/a2a_crewai_adk_plan.md)
