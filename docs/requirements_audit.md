# Project requirements audit

Status describes implementation and evidence separately. It is not a claim that research predicts returns.

| Requirement | Implementation | Verification / remaining gap |
|---|---|---|
| Shared context/state | ADK session state stores both market MCP outputs; typed specialist bundle feeds CrewAI tasks and trader | Real ADK/MCP/A2A diagnostic exercised; session evidence inspectable |
| At least two MCP tools | `get_price_history`, `get_live_quote` through ADK McpToolset/stdin server | Two real MCP calls verified |
| Pydantic output | Specialist reports, verdict, proposal and paper orders | Schema and grounding regression checks pass |
| Agentic patterns | Sequential evidence gathering, adversarial debate, manager synthesis, memory retrieval, human approval | Structured workflow implemented; no claim of superior investment performance |
| Callback monitoring | Actual agent/task starts, task outputs, guard decisions and errors → durable SSE ledger | Browser shows source refresh, failure and waiting states |
| Standard A2A interoperability | Actual a2a-sdk AgentCards and JSON-RPC client/server between ADK market and CrewAI research | Protocol diagnostic verified; old signed hub retained for compatibility |
| Both ADK and CrewAI only | ADK Runner/BaseAgent/LlmAgent and CrewAI Agent/Task/Crew | Other specialists are Python helpers, not another agent framework |
| Guardrails | Pydantic, source grounding, freshness, Prompt Guard, exchange validation and explicit order approval | Injection/benign probes and approval tests pass; guard false positives require evaluation |
| Observability | Langfuse US + OpenInference framework tracing + Groq usage | Real observations refetched; intermittent export failures and incomplete pricing mapping remain |
| Evaluation/runtime/cost | Measured latency/memory outputs and saved-run evaluator script | Final targeted regression 99 passed/7 skipped; full live-only run blocked by Reddit HTTP403; return accuracy/calibration and complete costs not established |
| Cloud deployment | Dockerfile, Render Free blueprint and operational notes | Owner deferred deployment; no accessible cloud service claimed |

UI includes research controls, NSE/BSE discovery, chart and proposal overview, live event pipeline, readable specialist reports, streamed draft/contribution debate, history and evidence inspector. Paper trading uses real provider data, polling quotes and charts, and an exact-order approval gate. No actual paper order has been submitted during testing.

See [testing evidence](testing.md), [TradingAgents comparison and improvement priorities](tradingagents_comparison.md), [deployment](deployment.md) and [trace/safeguard notes](observability.md).
