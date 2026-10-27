# KAIROS — Framework Interoperability & Agent-to-Agent (A2A) Plan
## Architectural Roadmap for Google Antigravity SDK (ADK) & CrewAI Integration

---

### 1. Architectural Roles & Separation of Concerns

KAIROS adopts a dual-framework architecture designed to leverage the distinct strengths of both **Google Antigravity SDK (ADK)** and **CrewAI**:

```
+-----------------------------------------------------------------------------------------+
|                                 GOOGLE ANTIGRAVITY SDK (ADK)                            |
|                          Quantitative Ingestion & Analyst Services                       |
|                                                                                         |
|  [Market Analyst]      [Sentiment Analyst]     [News Analyst]     [Fundamentals Analyst]|
|   - Ingests prices      - Ingests Reddit        - Ingests feeds    - Ingests SEC XBRL   |
|   - Evaluates SMA/RSI   - Gauges sentiment      - Topic clustering - Evaluates ratios   |
|   - Uses MCP Tools      - Uses MCP Tools        - Uses MCP Tools   - Uses MCP Tools     |
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

| Component | Framework | Primary Responsibilities | Tool Access Layer |
| :--- | :--- | :--- | :--- |
| **Analyst Layer** | **Google ADK** | Specialized analytical agents performing deterministic data extraction, quantitative indicators, SEC ratio verification, and sentiment scoring. | Model Context Protocol (MCP) data server (`KAIROS-Market-Data-MCP`). |
| **Deliberation & Risk**| **CrewAI** | Role-playing research debate (Bull vs. Bear), consensus synthesis, multi-scenario risk analysis, portfolio capital allocation. | Inter-agent messages received via A2A protocol from ADK Analyst services. |
| **Data Ingestion** | **Native Python / FastMCP** | High-throughput, memory-bounded collectors with Pydantic v2 validation. | Underlying Python modules (`kairos.collectors`). |

---

### 2. Distinction: MCP vs. A2A Protocol

- **MCP (Model Context Protocol)**:
  - *Purpose*: Standardized protocol connecting an individual LLM agent to external read-only tools and datasets (e.g., historical price bars, news queries, SEC XBRL facts).
  - *Pattern*: Client-to-Tool request/response.
- **A2A (Agent-to-Agent Protocol)**:
  - *Purpose*: Inter-agent communication, workflow orchestration, task delegation, and structured deliberation between autonomous services across runtime boundaries (ADK service to CrewAI service).
  - *Pattern*: Peer-to-peer asynchronous task negotiation and message passing with trace context.

---

### 3. Versioned Pydantic A2A Contracts

To ensure deterministic communication across boundaries, all A2A payloads adhere to strict Pydantic v2 schemas:

```python
# Conceptual A2A Envelope
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class A2ATaskEnvelope(BaseModel):
    trace_id: str = Field(..., description="Distributed tracing identifier (W3C traceparent)")
    sender_agent: str = Field(..., description="Originating agent e.g. adk.market_analyst")
    recipient_agent: str = Field(..., description="Target agent e.g. crewai.research_manager")
    version: str = Field(default="1.0.0", description="Contract schema version")
    task_type: str = Field(..., description="e.g. ANALYST_REPORT_SUBMISSION")
    payload: Dict[str, Any] = Field(..., description="Typed payload conforming to task_type")
    timestamp_utc: str = Field(...)
    signature: Optional[str] = Field(default=None, description="HMAC-SHA256 payload signature")
```

---

### 4. Task Lifecycle, Authentication & Fault Tolerance

1. **Task Lifecycle**:
   - `DISPATCHED`: Sender emits task envelope over local HTTP/gRPC channel.
   - `ACKNOWLEDGED`: Recipient validates schema and confirms ingestion.
   - `PROCESSING`: Recipient executes analytical reasoning or crew deliberation.
   - `COMPLETED`: Recipient returns response envelope with status `SUCCESS` and typed output.
   - `FAILED`: Recipient catches failure, formats structured error code, and quarantines trace.
2. **Authentication & Integrity**:
   - Shared secret HMAC-SHA256 signature verification over serialized payload bytes.
   - Replay protection with 60-second timestamp freshness window and UUID nonce checking.
3. **Timeouts & Circuit Breaking**:
   - 30-second default request timeout for synchronous agent inquiries.
   - Maximum 3 retries with exponential backoff for transient communication failures.

---

### 5. Future Integration Test Plan (Phase 2 Roadmap)

Before declaring A2A interoperability production-ready, the following deterministic verification suite will be executed:

1. **A2A Contract Roundtrip Test**:
   - Serialize sample ADK `MarketAnalystReport` into `A2ATaskEnvelope`.
   - Deliver envelope to CrewAI `ResearchManager` mock adapter.
   - Validate deserialization, field integrity, and response acknowledgment.
2. **End-to-End Multi-Agent Simulation**:
   - ADK Analyst agents pull Phase 1 market and fundamental data via MCP.
   - Summaries dispatched to CrewAI Bull and Bear researcher agents.
   - CrewAI Risk Analysts debate positions and Fund Manager outputs allocation decision.
   - Verify total latency and confirm memory remains under VM limits.

*(Note: In accordance with Phase 1 constraints, A2A communication is fully documented in this architecture plan and will be validated through live integration tests in Phase 2).*
