# Editing KAIROS

| Responsibility | Location |
|---|---|
| Agent roles, goals and backstories | `kairos_config/agents/*.jsonc` |
| Prompt templates and expected outputs | `kairos_config/prompts/tasks.jsonc` |
| Provider configuration | `kairos_config/providers/` |
| Guard model, threshold, input bounds | `kairos_config/security.jsonc` |
| Trace names, application labels, release | `kairos_config/observability.jsonc` |
| Environment template | `kairos_config/.env.example` |
| JSONC loader and environment settings | `kairos/config/` |
| React workspace | `web/src/App.tsx` |
| Pipeline, reports, debate, charts, search | `web/src/components/` |
| HTTP API, sessions and SSE ledger | `kairos/web/` |
| Real ADK workflow | `kairos/agents/adk_analysts/adk_market_agent.py` |
| MCP market tool server | `kairos/mcp_servers/market_data.py` |
| Standard a2a-sdk endpoints and client | `kairos/a2a/standard.py` |
| CrewAI tasks and debate | `kairos/agents/crewai_research/` |
| Deterministic proposal, model explanation | `kairos/agents/trader_agent.py` |
| Per-run fresh evidence acquisition | `kairos/pipeline/live_research.py` |
| Legacy ingestion and scheduler | `kairos/pipeline/` |
| MegaBull quotes, symbols and approvals | `kairos/trading/` |
| Groq cooldown/key pool | `kairos/providers/groq.py` |
| Langfuse, prompt guards, callbacks | `kairos/observability/` |
| Typed contracts | `kairos/schemas/` |
| Persistent research memory | `kairos/memory/` |
| Verification implementation | `kairos/verification/` |
| Thin launchers and maintenance | `scripts/` |
| Tests | `tests/` |
| Historical data snapshots and quarantine | `data/archive/` |
| Generated runtime data (ignored) | `data/runtime/` |

Root `main.py`, `run.py`, `dataphase1_logic.py`, `collectors/` and `schemas/` preserve compatibility with existing callers. New application logic belongs under `kairos/`.

JSONC resources are packaged independently as `kairos_config`. Definitions support comments and trailing commas, reject duplicate keys, and are validated by Pydantic. Restart after editing cached definitions. Python owns task sequencing, schemas, calculations and framework bindings; changing a task reference alone does not reroute execution.

Keep credentials in the ignored root `.env`, never in config resources, React or trace inputs. Preserve existing datasets. Run behavioral tests in a disposable copy because legacy tests write research exports. Use a new platform-specific virtual environment instead of copying `.venv` between machines.

See [testing record](testing.md), [observability](observability.md), [deployment boundaries](deployment.md), and [TradingAgents comparison](tradingagents_comparison.md).
