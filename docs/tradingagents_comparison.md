# KAIROS compared with TradingAgents

Source review: 2026-11-16. Reference: [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents), current main source downloaded for inspection. This compares implementation, not investment returns. Neither project's returns were independently benchmarked here.

## Assessment

TradingAgents is more developed in workflow recovery, date-aware research, independent risk deliberation, decision-outcome tracking and reproducible evaluation. KAIROS has a useful foundation for Indian equities, structured data-quality checks, explicit quote provenance and configurable CrewAI debate. Its biggest gaps are evidence integrity and dependable orchestration, not the number of agents or visual effects.

KAIROS must retain CrewAI and Google ADK to meet the project's rubric. TradingAgents uses LangGraph/LangChain, so importing its orchestration would violate that requirement. Adapt the patterns and validate them in the permitted frameworks.

## Capability comparison

| Area | TradingAgents source | KAIROS baseline before this work | Improvement |
| --- | --- | --- | --- |
| Agent architecture | Analyst team, Bull/Bear research, trader, aggressive/conservative/neutral risk debate, portfolio manager | Four analysts, Bull/Bear, research manager, trader | Add an independent risk gate after proposal generation; more roles are optional, deterministic limits are mandatory |
| State and recovery | Explicit graph state; optional SQLite checkpoints and resume | Python dictionaries passed sequentially; persistent research memory is not resumable workflow state | Typed per-run state with durable stage transitions, events and resumable completed stages |
| Framework requirement | LangGraph and LangChain | Genuine CrewAI; analyst classes labeled ADK called provider SDKs directly | Approved real ADK Market Analyst + standard A2A interoperability; do not copy LangGraph |
| Analyst execution | Selected analysts fan out and join before research | Sequential analyst calls | Run independent analysts concurrently within API rate budgets and preserve per-agent errors |
| Tools | Analysts request data through bounded tool loops and vendor routing | MCP-named adapters plus direct library/HTTP paths; analysis reads prepared files | At least two verified MCP tools used in an actual ADK run, with request/response provenance |
| Historical correctness | Analysis-date context, dated data filtering and point-in-time memory cutoffs | Saved latest datasets; several fixed October 2026 labels; stale-date setting not enforced | `as_of` per run; separate event/publication/retrieval timestamps; reject future or stale evidence |
| Risk and portfolio context | Independent risk debate and a portfolio-aware final manager | Risk-preference templates, technical stops and heuristic sizing strings | Typed risk verdict; position/cash constraints; revalidate model output against deterministic limits |
| Memory | Decision log settles decisions against observed returns and regional benchmark, then reflects | Persistent records with recency weighting and character-hash pseudo-vectors; built-in example trades | Separate demonstration records from verified paper executions; settle only observed outcomes; never call pseudo-vectors semantic embeddings |
| Evaluation | Ticker/date-grid decision evaluation with isolated result logs and post-decision entry timing | Unit/integration checks and per-run latency/RAM; no decision-quality backtest harness | Time-split evaluation, baseline comparisons, ablations, failure rates, token costs and runtime distributions |
| Providers and cost control | Separate quick/deep model tiers and provider configuration | Groq preferred, Gemini alternative; no full per-generation cost ledger | Per-role model budgets and trace-level usage/cost from actual generation responses |
| Outputs and interface | Structured decisions, interactive terminal UI and generated HTML reports | Typed JSON proposals and terminal summaries; no working web UI at baseline | Real-time research workspace, evidence inspector, accessible state transitions and explicit fallback labels |
| Delivery | Docker, Compose, clean-install checks, CI and separate integration-test markers | Packaged CLI and tests; no cloud deployment evidence | Reproducible container, CI, secret-safe runtime configuration, health checks and verified cloud release |

## Concrete KAIROS issues

1. **Old data could pass freshness checks.** `FreshnessGuardrail` had a maximum-age setting but only rejected future dates. Fixed during the Ponytail audit, with regression checks.
2. **Example trades could affect confidence and stop buffers.** Hardcoded seed records were inserted into empty memory and treated as completed-trade evidence. Demo seeding is now opt-in, new seed records are labeled and known old seed IDs are excluded from retrieval. Existing user databases are preserved.
3. **“Undervalued” is inferred partly from profit margin and debt, without a market-price valuation model.** Rename this to a profitability/financial-health assessment or add documented valuation inputs. A strong margin does not establish undervaluation.
4. **Model-generated prices need a final risk gate.** Validate live-model entry, stop, target, sizing and ticker against the grounded data after generation. A Pydantic object can be structurally valid while its prices or rationale are unsupported.
5. **Confidence is not calibrated.** Hardcoded confidence and win/loss adjustments should be labeled conviction, or calibrated against held-out outcomes. Do not present these numbers as measured win probabilities.
6. **The custom message hub is not standard A2A.** HMAC signs the payload and signature checking is conditional. Protocol-compliant messaging, authentication and task lifecycle require separate implementation.
7. **The MCP label is broader than the actual transport.** Direct Yahoo/NSE/Alpha Vantage calls can be useful, but should not be counted as verified remote MCP-tool executions.
8. **Memory retrieval is a heuristic.** The 16-dimensional character vectors are not semantic embeddings. Accurate labels plus ticker/strategy/date filters may be preferable to adding an embedding service before there is a real retrieval problem.
9. **Data refresh and analysis are separate.** The UI must show timestamps and offer an explicit refresh, rather than animate old datasets as a live market feed.

## Recommended order

1. **Evidence integrity:** timestamp enforcement, seed isolation, source citations, grounded output validation and honest confidence labels.
2. **Required frameworks:** complete the approved ADK Market Analyst, real MCP tools and standard A2A exchange with CrewAI. Test the actual transport and session-state updates.
3. **Operational backbone:** durable run state, streamed events, typed failures, meaningful agent/tool/generation spans, token accounting and Langfuse trace links.
4. **User interface:** research-first workflow with a separate evaluator view. Motion follows real events; empty, stale, disconnected and failed states are first-class.
5. **Approval-gated paper trading:** resolve instruments with the provider, preview exact quantity/side/type/price, require expiring session-bound approval, prevent duplicate submissions and reconcile uncertain responses. Entry orders do not imply automatic stop-loss/target orders.
6. **Evaluation and deployment:** compare against simple technical and buy-and-hold baselines for NSE stocks, with time-safe data; report failure rates and costs alongside decision quality; then deploy with authentication and persistent storage.

More agent roles, semantic embeddings, multi-tenant infrastructure and automatic strategy learning should follow measured need. They are not prerequisites for a readable and verifiable first release.

## Limits of the reference

- TradingAgents' backtest module explicitly evaluates decisions; it is not a full execution/portfolio simulator with quantities, fills and a cash ledger. Do not infer live execution from a BUY/SELL result or general README language.
- Docker and CI are evidence of deployability, not evidence that a particular hosted cloud installation is running.
- A richer architecture does not establish better investment performance. Compare both systems on the same universe, dates, data access, execution assumptions, model budget and metrics before making that claim.
- Do not add LangGraph, LangChain agents or another agentic framework to KAIROS as a shortcut around the rubric.

## Primary sources

- [Framework dependencies](https://github.com/TauricResearch/TradingAgents/blob/main/pyproject.toml)
- [Graph setup and fan-out](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/graph/setup.py)
- [Shared agent state](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/state.py)
- [Orchestrator and checkpoint handling](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/graph/trading_graph.py)
- [Date-window enforcement](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/dataflows/date_window.py)
- [Decision evaluation and its limits](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/backtest.py)
- [Outcome settlement](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/memory/settlement.py)
- [Risk-management roles](https://github.com/TauricResearch/TradingAgents/tree/main/tradingagents/agents/risk_mgmt)
- [Dockerfile](https://github.com/TauricResearch/TradingAgents/blob/main/Dockerfile), [CI](https://github.com/TauricResearch/TradingAgents/blob/main/.github/workflows/ci.yml)
