# KAIROS — Multi-Agent Interoperability & Agent-to-Agent (A2A) Plan
## Integration Blueprint for Indian Stock Market Analysis (Google ADK & CrewAI)

---

### 1. Dual-Framework Division of Labor

The KAIROS multi-agent architecture combines **Google Antigravity SDK (ADK)** and **CrewAI** for institutional Indian equities research:

```
+-----------------------------------------------------------------------------------------+
|                                 GOOGLE ANTIGRAVITY SDK (ADK)                            |
|                          Quantitative Ingestion & Analyst Services                       |
|                                                                                         |
|  [Market Analyst]      [Sentiment Analyst]     [News Analyst]     [Fundamentals Analyst]|
|   - Ingests 10Y OHLCV   - Ingests r/IndianStock - Ingests ET/Mint  - Ingests MCA/SEBI   |
|   - Evaluates SMA/RSI   - Gauges sentiment      - Sector headlines - Evaluates ROCE/D/E |
|   - Connects to MCP     - Connects to MCP       - Connects to MCP  - Connects to MCP    |
+-----------------------------------------------------------------------------------------+
                                             |
                                   A2A Protocol (JSON-RPC)
                         (Signed Payloads, Trace IDs, Pydantic v2)
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                     CREWAI FRAMEWORK                                    |
|                      Debate Crews, Risk Management & Execution Research                 |
|                                                                                         |
|      [Research Crew]                     [Risk Crew]                 [Management]       |
|    * Bull Researcher               * Aggressive Risk Analyst        * Fund Manager      |
|    * Bear Researcher               * Conservative Risk Analyst                          |
|    * Research Manager              * Neutral Risk Analyst                               |
+-----------------------------------------------------------------------------------------+
```

| Component | Framework | Target Indian Market Responsibilities | Tool / Data Access Layer |
| :--- | :--- | :--- | :--- |
| **Analyst Layer** | **Google ADK** | Specialized analytical services performing quantitative analysis on NSE equities (`RELIANCE.NS`, etc.), technical indicators, SEBI financial statements, and retail sentiment. | Connects to existing MCP servers (`yfinance-mcp-server`, `nse-mcp`). |
| **Research Debate & Risk**| **CrewAI** | Role-playing research crews (Bull vs. Bear researcher on Indian macro and sector outlook), multi-scenario risk analysis, portfolio capital allocation. | Consumes analytical synthesis envelopes received via A2A protocol from ADK services. |
| **Tool Protocol** | **MCP (Client)** | Read-only external data acquisition from existing servers. | Standard JSON-RPC 2.0 stdio/SSE client. |

---

### 2. Standardized A2A Communication Contract

All inter-agent communication across ADK and CrewAI processes uses versioned Pydantic v2 schemas:

```python
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class A2ATaskEnvelope(BaseModel):
    trace_id: str = Field(..., description="Distributed tracing identifier (W3C traceparent)")
    sender_agent: str = Field(..., description="e.g. adk.indian_market_analyst")
    recipient_agent: str = Field(..., description="e.g. crewai.research_manager")
    version: str = Field(default="1.0.0", description="Contract schema version")
    task_type: str = Field(..., description="e.g. NSE_EQUITY_ANALYSIS_SUBMISSION")
    payload: Dict[str, Any] = Field(..., description="Typed analyst payload")
    timestamp_utc: str = Field(...)
    signature: Optional[str] = Field(default=None, description="HMAC-SHA256 signature")
```

---

### 3. Future Integration Verification Plan (Phase 2 Roadmap)

Before declaring A2A interoperability production-ready:
1. **A2A Roundtrip Contract Test**:
   - ADK Analyst serializes `IndianMarketReport` (`RELIANCE`, 10Y SMA/RSI/MACD metrics).
   - Envelope delivered to CrewAI `ResearchManager`.
   - Validate deserialization, signature check, and response acknowledgment.
2. **End-to-End Multi-Agent Deliberation**:
   - Bull and Bear agents debate Indian market valuation regimes (e.g. NIFTY P/E vs 10Y bond yields).
   - Risk Analysts evaluate drawdown scenarios.
   - Fund Manager issues allocation decision.
   - Verify that process memory strictly respects VM budgets.
